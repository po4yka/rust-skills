---
name: rust-performance
description: Profile and optimize Rust code and native libraries. Covers host flamegraphs with cargo-flamegraph and perf, Android on-device profiling with simpleperf, Perfetto, HWASan and ndk-stack symbolication, iOS profiling with Instruments, os_signpost and MetricKit, binary size analysis with cargo-bloat, monomorphization bloat with cargo-llvm-lines, Criterion microbenchmarks and baselines, heap profiling with heaptrack and DHAT, data-parallel work with rayon, and build-time tuning with cargo --timings, sccache, LTO, codegen-units and linker choice. Use when a workload is slow, a binary or app bundle grew, a benchmark regressed, a flamegraph needs reading, a native crash needs symbolication, or a cross-compilation build is slow. Triggers on "flamegraph", "simpleperf", "Perfetto", "Instruments", "cargo-bloat", "binary size", "build time", "LTO", "monomorphization", or any performance question.
license: BSD-3-Clause
---

# Rust Performance

Profiling and optimization for Rust workloads on the host, on Android, and on iOS.

## Rules of engagement

1. Measure before you change code. A profile or a benchmark must name the hotspot.
2. Write down the metric first. Choose one number per concern: items/sec, MB/s, ms per pass, peak MB, or KB added to the app bundle. An optimization without a metric is a guess.
3. Profile the profile that ships. Size and speed numbers from `dev` do not transfer to `release`.
4. Change one thing per measurement. Save a baseline, apply one change, compare.
5. Keep the same machine, the same power state, and the same device for A/B runs.
6. Optimize the algorithm before the constant factor. LTO gives 5-30%; a better data structure gives more.

## Tool selection

| Target | CPU profile | Heap profile | Notes |
|--------|-------------|--------------|-------|
| Host (Linux) | `samply`, `cargo flamegraph`, `perf record` | `heaptrack`, DHAT | `perf_event_paranoid <= 1` required |
| Host (macOS) | `samply`, `cargo flamegraph` (DTrace), Instruments | DHAT through the `dhat` crate, Instruments Allocations | DTrace needs `sudo` and SIP consideration; `samply` does not |
| Android | `simpleperf`, Perfetto | Android Studio native allocations, HWASan for errors | `perf`, `heaptrack` and DHAT do not work here |
| iOS | Instruments Time Profiler, `os_signpost` | Instruments Allocations and Leaks | No `simpleperf`; MetricKit for production data |

`samply` 0.13.1 is the lowest-friction sampling profiler on the host. It runs on macOS and Linux, needs no DTrace, no `sudo` and no Instruments, and opens the result in the Firefox Profiler:

```bash
cargo install samply
samply record ./target/release/app
```

The Firefox Profiler is also a viewer for raw `perf` data on Linux.

---

## 1. Host profiling

### cargo-flamegraph

`cargo flamegraph` works for host-target binaries, tests, examples and benchmarks. It does not work for Android or iOS targets.

```bash
cargo install flamegraph

# Profile a binary with arguments
cargo flamegraph --locked --bin myapp -- --workers 4 --input data.bin

# Profile a benchmark (pass --bench through to the harness)
cargo flamegraph --locked --bench my_bench -p my-bench-crate -- --bench

# Custom sample frequency; 997 Hz avoids aliasing with periodic work
cargo flamegraph --locked --freq 997 --bin myapp
```

On macOS `cargo flamegraph` uses DTrace and needs `sudo`. On Linux it uses `perf`.

See [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md) for the Linux and macOS prerequisites, and for the test, example, `--manifest-path` and output-file invocations.

### Reading flamegraphs

| Axis | Meaning |
|------|---------|
| X (width) | Proportion of samples, so proportion of CPU time. Wider is hotter. |
| X (order) | Alphabetical inside each stack level. It is NOT a time sequence. |
| Y (height) | Call stack depth. The bottom frame is the entry point. |

| Pattern | Meaning | Action |
|---------|---------|--------|
| Wide plateau at the top | Leaf hotspot | Optimize that function |
| Wide frame with tall narrow towers above it | Hot dispatch | Reduce call overhead, inline, or devirtualize |
| Unexpected `alloc` / `dealloc` / `drop` frames | Excessive allocation | Pool or reuse buffers |
| Many thin `<closure>` frames | Closure overhead in a tight loop | Extract to a named function |
| Empty or truncated stacks | Unwinding failed | Build with `-C force-frame-pointers=yes` |

Differential flamegraphs use color: red marks a regression, blue marks an improvement.

### Other host tools

- `perf stat` and `perf record` — Linux only. Build with `RUSTFLAGS="-C force-frame-pointers=yes"` for reliable call graphs.
- `heaptrack` — Linux heap profiler. Run `heaptrack ./target/release/myapp`.
- DHAT through Valgrind — Linux only. Run `valgrind --tool=dhat ./target/debug/myapp`.
- DHAT through the `dhat` crate — version 0.3.3 builds and runs on stable. No nightly is needed. Keep the feature gate so the profiler and its global allocator stay out of the shipped binary:

```bash
cargo run --release --locked -p myapp --features dhat-heap -- <args>
# Writes dhat-heap.json on exit.
# View at https://nnethercote.github.io/dh_view/dh_view.html
```

The same crate also turns a heap measurement into a regression test. Build the profiler in testing mode, then assert on `dhat::HeapStats`:

```rust,ignore
let _p = dhat::Profiler::builder().testing().build();
// run the code under test
dhat::assert_eq!(dhat::HeapStats::get().total_blocks, 1);
```

`dhat::assert_eq!` is not a no-op outside testing mode. Under a non-testing profiler it panics with `dhat: asserting while not in testing mode`, and with no profiler running it panics with `dhat: asserting when no profiler is running`. For what to change in the code once DHAT names the allocation sites, see `rust-hot-path`.

- DTrace on macOS — `cargo flamegraph` calls it for you.
- Instruments on macOS — Allocations and Leaks templates also work on host builds.

---

## 2. Android on-device profiling

Host tools such as `perf`, `heaptrack` and DHAT do not work for Android targets. Use `simpleperf` for a CPU profile of one process. Use Perfetto when you need the native profile next to scheduler, binder and app frame data.

Set two things before you record:

- `-C force-frame-pointers=yes` for every Android target, as per-target `rustflags` in `.cargo/config.toml`. Without it `simpleperf` cannot walk ARM64 stacks and the flamegraph comes out empty. The cost is one reserved register (`x29` on ARM64).
- An unstripped `.so` kept on the host, under `target/<triple>/<profile>/`. Gradle packages a stripped copy, and every symbolication step needs the unstripped one.

The `simpleperf` and Perfetto commands, the full prerequisites table, offline symbolication with `ndk-stack` and `llvm-addr2line`, HWASan builds, Android Studio LLDB and the native memory profiler are in [references/android-profiling.md](references/android-profiling.md).

---

## 3. iOS on-device profiling

iOS profiling uses Instruments for sampling and `os_signpost` for in-code interval markers. There is no `simpleperf` on iOS.

### Instruments

```text
Product -> Profile (Cmd-I) in Xcode
Time Profiler   -> CPU flamegraphs and call trees
Allocations     -> heap growth and allocation counts
Leaks           -> retain cycles
```

For usable symbols in Instruments:

- Build the Rust static library with the on-device debug profile, so debug line tables survive.
- Turn off "Strip Swift Symbols" in the Xcode scheme for the profiling run.

### os_signpost markers

Mark the boundaries of major native stages so Instruments shows named intervals in the Points of Interest track. Emit the signposts from the platform side around each call into the Rust library:

```swift
import os.signpost

let log = OSLog(subsystem: "com.example.app", category: "engine")
let id = OSSignpostID(log: log)

os_signpost(.begin, log: log, name: "HeavyStage", signpostID: id)
// call into the Rust library
os_signpost(.end, log: log, name: "HeavyStage", signpostID: id)
```

Emit the signposts from Rust only through a platform shim, gated behind a build feature or `cfg`. Keep the shim out of the Android and host builds.

### MetricKit

MetricKit gives aggregated on-device performance data from real users. Wire `MXMetricPayload` in the app delegate to collect hang rate, CPU time and memory metrics in production without instrumentation overhead. Use it to confirm that a local win is real on shipped devices.

---

## 4. Binary size (cargo-bloat)

Always pass the profile that ships. Numbers from `release` do not match a size-optimized mobile profile.

```bash
# Per-crate breakdown; this is what maps to app bundle growth
cargo bloat --locked --profile mobile-release --target aarch64-linux-android --crates

# Top 20 functions by size
cargo bloat --locked --profile mobile-release --target aarch64-linux-android -n 20

# iOS device slice
cargo bloat --locked --profile mobile-release --target aarch64-apple-ios --crates

# Compare before and after
cargo bloat --locked --profile mobile-release --target aarch64-linux-android --crates > before.txt
# apply the change
cargo bloat --locked --profile mobile-release --target aarch64-linux-android --crates > after.txt
diff before.txt after.txt
```

### Strip and debug trade-offs

| Setting | Binary size | Debuggable | Use when |
|---------|-------------|------------|----------|
| `strip = "symbols"` | Smallest | No | Ship builds with no on-device profiling need |
| `strip = "debuginfo"` | ~5-10% larger | Partial | Keeps symbol names for profiling |
| `strip = "none"` + `debug = 0` | ~10-15% larger | No | ELF symbols remain for `ndk-stack` |
| `strip = "none"` + `debug = "line-tables-only"` | ~30-50% larger | Yes | Profiling sessions, or ship builds with packaged symbol sidecars |

If you strip the shipped library, archive the unstripped copy alongside the release so crashes can still be symbolicated offline.

### FFI scaffolding

Generated FFI scaffolding is not free. Each type that crosses the boundary generates code. If the FFI crate dominates `cargo bloat --crates`, audit the public surface and narrow the number of enums and records that cross. See `uniffi-boundary` and `rust-jni`.

---

## 5. Monomorphization bloat (cargo-llvm-lines)

`cargo llvm-lines` counts LLVM IR lines per function. High IR volume costs both compile time and binary size.

```bash
cargo install cargo-llvm-lines
cargo llvm-lines --locked --release -p my-crate | head -30
```

A high `Copies` count means the generic was instantiated many times. Fix it with the thin-wrapper pattern: keep the generic surface, move the body into a concrete inner function.

```rust
// Before: the whole body is monomorphized for every T.
fn send<T: AsRef<[u8]>>(data: T) {
    // ... large body ...
}
```

```rust
// After: a thin generic wrapper plus one concrete inner copy.
fn send<T: AsRef<[u8]>>(data: T) {
    fn inner(data: &[u8]) {
        // ... large body, compiled once ...
    }
    inner(data.as_ref())
}
```

Check the crates with the heaviest generic iterator chains and the widest trait-bound surfaces first.

---

## 6. Criterion microbenchmarks

### Pick the harness first

| Harness | Measures | Reach for it when |
|---------|----------|-------------------|
| Criterion | Wall clock, in process | The default. Baselines, statistics, HTML reports |
| Divan 0.1.21 | Wall clock, in process | You want a lighter in-process harness with less code per benchmark |
| Hyperfine 1.20.0 | Wall clock of a whole process | The unit of work is one CLI invocation, not one function |
| Gungraun 0.19.4 | Valgrind instruction counts | You need a number that does not move with machine noise, inside `cargo bench` |

Two naming traps:

- Gungraun is the rename of `iai-callgrind`. `iai-callgrind` is still published separately at 0.16.1, so pin the crate you mean instead of taking whichever name you remember.
- Rust's built-in `#[bench]` attribute is nightly-only. On stable it fails with E0554.

### Running Criterion

Declare `harness = false` for every benchmark target in the crate manifest, otherwise the built-in test harness intercepts the arguments.

```bash
# Compile every benchmark without measuring. Use this in review and in CI.
cargo bench --locked --workspace --no-run

# Run one suite
cargo bench --locked -p my-crate --bench decode

# Filter to one benchmark function
cargo bench --locked -p my-crate --bench decode -- decode_large

# Save a baseline, change the code, then compare against it
cargo bench --locked -p my-crate --bench decode -- --save-baseline before
cargo bench --locked -p my-crate --bench decode -- --baseline before

# HTML report
open target/criterion/report/index.html
```

Criterion prints the verdict with a p-value:

```text
decode/medium           time:   [12.345 µs 12.456 µs 12.567 µs]
                        change: [-5.2312% -4.8956% -4.5600%] (p = 0.00 < 0.05)
                        Performance has improved.
```

Do not read a change with `p > 0.05` as a result. Increase `sample_size` or `measurement_time` instead.

A low p-value is not proof either. Wall-clock variance caused by memory layout — symbol order, environment size, stack alignment — is systematic within one build, so it repeats across samples and Criterion reports `p < 0.05` on it. The result is reproducible and still wrong. Instruction counts do not have that failure mode, so confirm a small wall-clock win with Gungraun before you keep the change.

Benchmark structure, `Throughput` reporting, statistical configuration and async benchmarks are in [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md).

### Prove the benchmark measured something

`black_box` on the input and on the output does not prove the work ran. LLVM rewrites an arithmetic reduction such as `(0..n).sum()` into the closed form `n * (n - 1) / 2`, so the routine really becomes O(1), and a `black_box` on each end does not bring the loop back. Measured under `cargo +nightly bench`, `black_box` on both sides: `closed_form_2m` 0.58 ns/iter and `closed_form_20m` 0.57 ns/iter. A 10x input moved the time by 1.02x. The same 10x change on a pre-built `Vec<u64>` moved it 11.5x to 13.2x over four runs. A `black_box` inside the reduction, as in `(0..black_box(n)).map(black_box).sum::<u64>()`, does emit the loop again, but then the barrier is what you measure.

Run the identical routine at two problem sizes 10x apart, as two benchmark functions in the same binary. Real work moves the time. Folded work does not.

```rust
use std::hint::black_box;
use std::time::Instant;

/// Seconds per call of `f`, averaged over `reps` calls.
fn per_call<T>(reps: u32, mut f: impl FnMut() -> T) -> f64 {
    let start = Instant::now();
    for _ in 0..reps { black_box(f()); }
    start.elapsed().as_secs_f64() / f64::from(reps)
}

fn main() {
    // Folded: LLVM rewrites `(0..n).sum()` into n * (n - 1) / 2.
    let folded = per_call(1_000_000, || black_box((0..black_box(20_000_000u64)).sum::<u64>()))
        / per_call(1_000_000, || black_box((0..black_box(2_000_000u64)).sum::<u64>()));

    // Real: the sum reads memory that the compiler cannot fold away.
    let small: Vec<u64> = (0..2_000_000).collect();
    let large: Vec<u64> = (0..20_000_000).collect();
    let real = per_call(50, || black_box(&large).iter().sum::<u64>())
        / per_call(50, || black_box(&small).iter().sum::<u64>());

    // Eighteen release runs: folded ratio 0.93 to 1.27, real ratio 11.8 to 14.7.
    println!("folded ratio = {folded:.2}, real ratio = {real:.2}");
}
```

Read the ratio in one direction only. A ratio near 1.0 for a 10x input change means the benchmark measured nothing. Do not require a ratio near 10: cache effects make it superlinear, and fixed per-iteration overhead makes it sublinear for a cheap routine.

The Criterion examples in [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md) pass every fixture through `black_box`. That guards against a discarded result. It does not guard against a folded loop. Apply this scaling check to each of them before you trust the number.

### Long correctness tests as a regression signal

Full-pipeline correctness tests, such as golden-output tests, are not benchmarks, but they do measure wall-clock time. If such a test starts taking more than twice its usual time, treat it as a performance regression and profile it. See `rust-test-tools`.

---

## 7. Data-parallel work with rayon

Use `rayon` when the work is compute-bound and splits into independent units.

```rust
use rayon::prelude::*;

let results: Vec<_> = items
    .par_iter()
    .map(|item| process(item, &config))
    .collect();
```

Rules for mobile targets:

- Cap the pool. The default `rayon` pool is unbounded relative to what a phone should run. Build the global pool once at library init:

```rust
rayon::ThreadPoolBuilder::new()
    .num_threads(num_cpus::get_physical())
    .build_global()
    .expect("rayon global pool already initialized");
```

- On iOS, size the pool from `ProcessInfo.processInfo.activeProcessorCount` and pass that value across the FFI boundary at init.
- Never hold an FFI handle or a JNI environment inside a `rayon` closure. Resolve every value you need into owned data before the parallel section.

---

## 8. Profiles and LTO

Profile names are your own convention. Define them once in the workspace `Cargo.toml`.

Cargo reads `[profile.*]` only from the workspace-root manifest. A table in a member crate or in a dependency is discarded, so a library crate cannot ship optimization settings to its consumers.

```toml
[profile.release]
lto = "thin"          # good performance, much faster to link than "fat"
codegen-units = 1     # best optimization; disables parallel codegen
strip = "symbols"
panic = "abort"

[profile.mobile-release]   # this is what ships in the app bundle
inherits = "release"
opt-level = "z"            # size-optimized
lto = "fat"
codegen-units = 1
panic = "unwind"           # required when the FFI boundary catches panics
strip = "none"             # keep ELF symbols for offline symbolication
debug = "line-tables-only"

[profile.mobile-dev]       # on-device debugging and profiling
inherits = "dev"
opt-level = 1
debug = "line-tables-only"
panic = "unwind"

[profile.bench]            # host benchmarks
inherits = "release"
debug = false
lto = "thin"

[profile.dev]
debug = "line-tables-only"     # faster than full debug info
split-debuginfo = "unpacked"   # reduces linker input on macOS
```

Two decisions in that block need a deliberate answer:

- `panic`. Use `"abort"` for the smallest binary and no unwinding overhead. Use `"unwind"` when a panic must be caught at the FFI boundary, as JNI wrappers do with `catch_unwind`. A panic that unwinds out of an `extern "C"` function aborts the process, so the boundary must catch the panic before it escapes. `catch_unwind` cannot catch anything under `panic = "abort"`. See `rust-panic-safety` and `ffi-error-progress-cancel`.
- `strip`. Use `"symbols"` for the smallest artifact only if you archive an unstripped copy. Use `"none"` with `debug = "line-tables-only"` when you profile or symbolicate on device.

LTO comparison:

| Setting | Link time | Runtime performance | Use when |
|---------|-----------|---------------------|----------|
| `lto = "off"` | Fast | Baseline | The true no-LTO baseline for an A/B |
| `lto = false` | Fast | Above the baseline | Dev builds. Thin-local LTO stays on |
| `lto = "thin"` | Moderate | +5-15% | Most release builds |
| `lto = "fat"` | Slow | +15-30% | Maximum performance or minimum size |
| `codegen-units = 1` | Slowest | Best | Always pair with LTO for release |

`opt-level = "z"` trades throughput for size. Measure it. On a compute-bound hot path `opt-level = 3` can be the better ship setting even on mobile.

Where Cargo reads each setting from, why `lto = false` does not turn LTO off, `target-cpu`, profile-guided optimization and the global allocator are in [references/build-configuration.md](references/build-configuration.md).

---

## 9. Build time

Diagnose first:

```bash
cargo build --locked --timings           # writes target/cargo-timings/cargo-timing.html
cargo build --locked --release --timings
```

Read the timeline for long sequential chains, crates over 10 s, and proc-macro crates that block everything downstream.

The full build-time playbook — sccache, the cross-compilation target matrix, workspace splitting, linker choice, and incremental compilation trade-offs — is in [references/build-time-optimization.md](references/build-time-optimization.md).

---

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| Flamegraph shows empty or truncated stacks | No frame pointers | Add `-C force-frame-pointers=yes` for the target in `.cargo/config.toml` |
| Symbolication shows `<unknown>` | Stripped library | Use the unstripped `.so` from `target/<triple>/<profile>/`, not the packaged copy |
| Profiling a release build shows no symbols | The ship profile strips symbols | Profile the on-device debug profile, or symbolicate offline |
| `cargo flamegraph` fails on Linux | `perf_event_paranoid` too high | Set it to 1 or lower |
| `cargo flamegraph` fails on macOS | DTrace blocked | Run with `sudo`; check SIP |
| Benchmark results swing by more than 10% between runs | Thermal or scheduler noise | Fix the power state, close background load, raise `sample_size` |
| Binary grew after a dependency bump | New monomorphizations or new codegen | `cargo bloat --crates` then `cargo llvm-lines` on the top crate |
| An Android profiling or symbolication step fails | Device, NDK or packaging setup | The common-mistakes table in [references/android-profiling.md](references/android-profiling.md) |

---

## Review checklist

Before you claim a performance change:

- [ ] A profile or benchmark named the hotspot before the change.
- [ ] The measurement used the profile that ships, not `dev`.
- [ ] A Criterion baseline was saved before and compared after, with `p < 0.05`.
- [ ] `cargo bloat --crates` was captured before and after if the change touches generics, dependencies, or profile settings.
- [ ] Benchmarks still compile: `cargo bench --locked --workspace --no-run`.
- [ ] The change did not silently switch `panic` or `strip` in a profile that a symbolication or FFI-catch path depends on.
- [ ] Any new `unsafe` or new parallelism was checked with the sanitizers in `rust-sanitizers-miri`.

---

## Quick reference

| Task | Command |
|------|---------|
| Host flamegraph of a binary | `cargo flamegraph --locked --bin myapp -- <args>` |
| Host flamegraph of a benchmark | `cargo flamegraph --locked --bench my_bench -p my-bench-crate -- --bench` |
| Record an Android CPU profile | `adb shell simpleperf record -p $(adb shell pidof com.example.app) --call-graph dwarf --duration 30 -o /data/local/tmp/perf.data` |
| Android flamegraph | `python3 $ANDROID_NDK_HOME/simpleperf/inferno.py -sc --record_file perf.data` |
| Symbolicate a native crash | `adb logcat \| $ANDROID_NDK_HOME/ndk-stack -sym target/aarch64-linux-android/debug/` |
| Per-crate binary size | `cargo bloat --locked --profile mobile-release --target aarch64-linux-android --crates` |
| Monomorphization bloat | `cargo llvm-lines --locked --release -p my-crate \| head -30` |
| Compile all benchmarks | `cargo bench --locked --workspace --no-run` |
| Save a benchmark baseline | `cargo bench --locked -p my-crate --bench decode -- --save-baseline before` |
| Build timing report | `cargo build --locked --release --timings` |
| Cache hit rate | `sccache --show-stats` |

---

## References

- [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md) — flamegraph prerequisites, install, and the Criterion authoring reference.
- [references/android-profiling.md](references/android-profiling.md) — the `simpleperf` and Perfetto commands, offline symbolication, panic backtraces, HWASan, Android Studio LLDB and native memory profiler.
- [references/build-configuration.md](references/build-configuration.md) — where Cargo reads settings from, `opt-level`, `target-cpu`, PGO, global allocator.
- [references/build-time-optimization.md](references/build-time-optimization.md) — sccache, cross-compilation matrix, workspace splitting, linkers.
- Android NDK simpleperf documentation: `$ANDROID_NDK_HOME/simpleperf/doc/`
- Perfetto UI: https://ui.perfetto.dev
- DHAT viewer: https://nnethercote.github.io/dh_view/dh_view.html

## Related skills

- `rust-hot-path` — what to change in the code once a profile names the hotspot. This skill produces the profile; `rust-hot-path` turns it into a diff.
- `cargo-workflows` — workspace layout, feature flags, profile plumbing.
- `rust-discipline` — allocation and clone anti-patterns on hot paths.
- `rust-sanitizers-miri` — HWASan, ASan, TSan and Miri for correctness under optimization.
- `rust-debugging` — backtraces, LLDB, and crash triage.
- `rust-observability` — tracing spans and structured timing in production.
- `rust-android-build` — NDK toolchain, target matrix, Gradle packaging.
- `rust-jni` and `uniffi-boundary` — FFI surface size and panic handling at the boundary.
- `rust-panic-safety` — `catch_unwind` at the boundary and the `panic` profile setting.
- `rust-test-tools` — benchmark harness setup and regression gating.
