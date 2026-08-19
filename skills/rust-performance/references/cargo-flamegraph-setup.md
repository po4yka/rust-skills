# cargo-flamegraph Setup and Criterion Reference

## cargo-flamegraph setup

### Linux prerequisites

```bash
# Install perf
sudo apt-get install linux-tools-common linux-tools-$(uname -r)  # Debian/Ubuntu
sudo dnf install perf                                            # Fedora
sudo pacman -S perf                                              # Arch

# Allow perf for the current user (choose one)
sudo sh -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'                   # temporary
echo 'kernel.perf_event_paranoid = 1' | sudo tee -a /etc/sysctl.d/perf.conf  # permanent
sudo sysctl -p /etc/sysctl.d/perf.conf

# Allow kernel symbols
sudo sh -c 'echo 0 > /proc/sys/kernel/kptr_restrict'
```

### macOS prerequisites

macOS uses DTrace. It needs `sudo`, and System Integrity Protection can block it.

```bash
# Check that DTrace works
sudo dtrace -n 'BEGIN { exit(0); }'

# If SIP blocks it, boot into recovery and run:
# csrutil enable --without dtrace
```

### Installation

```bash
cargo install flamegraph
```

`cargo flamegraph` folds stacks with `inferno`, which is pure Rust and needs no extra install. If you prefer the original Perl scripts:

```bash
git clone https://github.com/brendangregg/FlameGraph
export PATH="$PATH:/path/to/FlameGraph"
```

### Usage patterns

```bash
# Profile a binary with arguments
cargo flamegraph --locked --bin myapp -- --workers 4 --input data.bin

# Profile one integration test
cargo flamegraph --locked --test integration_tests -- test_name

# Profile a benchmark; everything after -- goes to the Criterion harness
cargo flamegraph --locked --bench my_bench -p my-bench-crate -- --bench decode_large

# Profile an example
cargo flamegraph --locked --example my_example

# Point cargo at a nested workspace while staying at the repository root,
# so that relative fixture paths in the program still resolve
cargo flamegraph --locked --manifest-path path/to/Cargo.toml --bin myapp -- \
    run --input fixtures/sample.bin

# Custom sample frequency. Higher is more accurate and costs more overhead.
# 997 Hz is prime, which avoids aliasing with periodic work.
cargo flamegraph --locked --freq 997 --bin myapp

# Write to a chosen file
cargo flamegraph --locked -o profile.svg --bin myapp

# Write and open
cargo flamegraph --locked -o /tmp/fg.svg --bin myapp && open /tmp/fg.svg      # macOS
cargo flamegraph --locked -o /tmp/fg.svg --bin myapp && xdg-open /tmp/fg.svg  # Linux
```

Build with frame pointers if stacks come out truncated:

```bash
RUSTFLAGS="-C force-frame-pointers=yes" cargo flamegraph --locked --bin myapp
```

### Reading flamegraphs

```text
Wide frames  = more CPU time
Tall stacks  = deep call chains
Plateau tops = CPU time actually spent in that frame

x-axis: NOT time. Frames are sorted alphabetically inside each stack level.
y-axis: call stack depth. The bottom frame was called first.
```

Look for:

- Wide frames near the top. These are hot leaves, where the CPU really is.
- Unexpected `std::alloc` / `dealloc` / `drop` frames. These mean allocation pressure.
- Many thin `<closure>` frames. These mean closure overhead in a tight loop.
- Frames from a third-party rendering, parsing or crypto crate. Expected inside that stage, suspicious anywhere else.

---

## Criterion reference

### Manifest setup

```toml
[dev-dependencies]
# Match the Criterion version already pinned in your workspace.
criterion = { version = "0.7", features = ["html_reports"] }

[[bench]]
name = "decode"
harness = false   # required, or the built-in test harness eats the arguments
```

### Benchmark structure with throughput

```rust
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use std::hint::black_box;   // criterion::black_box is deprecated; use the std one
use std::time::Duration;

fn bench_throughput(c: &mut Criterion) {
    let mut group = c.benchmark_group("decode");

    // Measurement window and sample count
    group.measurement_time(Duration::from_secs(10));
    group.sample_size(100);

    for (label, bytes) in [("small", 8_192usize), ("medium", 65_536), ("large", 262_144)] {
        let data = vec![0u8; bytes]; // replace with a real fixture

        // Report bytes/sec next to the time
        group.throughput(Throughput::Bytes(bytes as u64));
        group.bench_with_input(
            BenchmarkId::new("decode", label),
            &data,
            |b, data| b.iter(|| decode(black_box(data))),
        );
    }
    group.finish();
}

criterion_group!(benches, bench_throughput);
criterion_main!(benches);
```

Use `Throughput::Bytes` for byte streams and `Throughput::Elements` for item counts, such as one rendered frame or one processed record per iteration.

### Per-item benchmark with expensive setup

Build the fixture once, outside the measured closure. Only the work under test belongs inside `iter`.

```rust
fn bench_render(c: &mut Criterion) {
    let scene = load_fixture_scene();   // setup, not measured

    let mut group = c.benchmark_group("render");
    group.measurement_time(Duration::from_secs(15));
    group.sample_size(50);

    for px in [2048u32, 3000, 4500] {
        group.throughput(Throughput::Elements(1));  // one output per iteration
        group.bench_with_input(
            BenchmarkId::new("raster", px),
            &px,
            |b, &px| b.iter(|| render_to_buffer(black_box(&scene), black_box(px))),
        );
    }
    group.finish();
}
```

If the setup must run per iteration, use `iter_batched` so the setup cost stays out of the measurement.

### Statistical configuration

Set the statistics for a whole target through the `criterion_group!` config form. It replaces the plain `criterion_group!(benches, bench_throughput);` line shown above. The builder methods on `Criterion` take `self` by value, so chain them on a fresh `Criterion::default()`:

```rust
criterion_group! {
    name = benches;
    config = Criterion::default()
        .measurement_time(Duration::from_secs(10))  // how long to measure
        .sample_size(200)                           // number of samples
        .warm_up_time(Duration::from_secs(3))       // warm-up before measurement
        .noise_threshold(0.05)                      // 5% noise threshold
        .significance_level(0.05)                   // p-value threshold
        .confidence_level(0.95);                    // confidence interval width
    targets = bench_throughput
}
criterion_main!(benches);
```

The same methods exist on `BenchmarkGroup`, where they take `&mut self`. Use the group form to configure one group only, as the examples above do.

Raise `sample_size` and `measurement_time` when the reported change is not significant. Do not lower `significance_level` to make a result look real.

### Wall time and CPU time

Criterion measures wall time by default. For compute-bound work with no I/O this is the right metric. For work that blocks on I/O, wall time reports the wait, not the cost.

Do not build async benchmarks for synchronous compute-bound code. Add the async harness only when the code under test is genuinely async.

### Async benchmarks with Tokio

```toml
[dev-dependencies]
criterion = { version = "0.7", features = ["async_tokio"] }
tokio = { version = "1", features = ["full"] }
```

```rust
fn bench_async(c: &mut Criterion) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    c.bench_function("async_op", |b| {
        b.to_async(&rt).iter(|| async_operation(black_box(42)))
    });
}
```

### Comparing results

```bash
# Save a baseline on the base branch
cargo bench --locked -p my-crate -- --save-baseline main-branch

# Switch branch and compare against it
git checkout my-feature
cargo bench --locked -p my-crate -- --baseline main-branch
```

Output:

```text
decode/medium           time:   [12.345 µs 12.456 µs 12.567 µs]
                        change: [-5.2312% -4.8956% -4.5600%] (p = 0.00 < 0.05)
                        Performance has improved.
```

Read the `change` interval, not the midpoint. If the interval crosses zero, or `p > 0.05`, there is no measured change.

### Validating benchmark code in review

```bash
# Compile every benchmark target without running measurements
cargo bench --locked --workspace --no-run
```

This is the cheap gate for CI and for review. It catches API drift in benchmark code without paying for a full measurement run.
