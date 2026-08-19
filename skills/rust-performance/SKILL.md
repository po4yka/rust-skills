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
| Host (Linux) | `cargo flamegraph`, `perf record` | `heaptrack`, DHAT | `perf_event_paranoid <= 1` required |
| Host (macOS) | `cargo flamegraph` (DTrace), Instruments | DHAT through the `dhat` crate, Instruments Allocations | DTrace needs `sudo` and SIP consideration |
| Android | `simpleperf`, Perfetto | Android Studio native allocations, HWASan for errors | `perf`, `heaptrack` and DHAT do not work here |
| iOS | Instruments Time Profiler, `os_signpost` | Instruments Allocations and Leaks | No `simpleperf`; MetricKit for production data |

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

# Profile a specific integration test
cargo flamegraph --locked --test integration_tests -- test_name

# Point cargo at a nested workspace from the repository root
cargo flamegraph --locked --manifest-path path/to/Cargo.toml --bin myapp

# Custom sample frequency; 997 Hz avoids aliasing with periodic work
cargo flamegraph --locked --freq 997 --bin myapp

# Write to a chosen file
cargo flamegraph --locked -o /tmp/fg.svg --bin myapp
```

On macOS `cargo flamegraph` uses DTrace and needs `sudo`. On Linux it uses `perf`.

See [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md) for the Linux and macOS prerequisites.

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
- DHAT through the `dhat` crate — gate it behind a feature and run on nightly:

```bash
cargo +nightly run --locked -p myapp --features dhat-heap -- <args>
# Writes dhat-heap.json on exit.
# View at https://nnethercote.github.io/dh_view/dh_view.html
```

- DTrace on macOS — `cargo flamegraph` calls it for you.
- Instruments on macOS — Allocations and Leaks templates also work on host builds.

---

## 2. Android on-device profiling

Host tools such as `perf`, `heaptrack` and DHAT do not work for Android targets. Use `simpleperf` or Perfetto.

### Prerequisites

| Requirement | Why | How |
|-------------|-----|-----|
| `-C force-frame-pointers=yes` for every Android target | `simpleperf` cannot walk ARM64 stacks reliably without it | Set `rustflags` per target in `.cargo/config.toml` |
| Debug symbols kept in the debug APK | Otherwise the profiler shows raw addresses | Enable the Android Gradle `keepDebugSymbols` packaging option for your `.so` |
| An unstripped `.so` kept on the host | Needed for offline symbolication | Keep the copy under `target/<triple>/<profile>/` before Gradle strips it |
| A global panic hook that captures a backtrace | Native panics otherwise reach logcat with no stack | Install it in `JNI_OnLoad` or at library init |

The frame pointer cost is negligible. One general-purpose register (`x29` on ARM64) is reserved.

### simpleperf (CPU profiling)

The Android NDK ships `simpleperf` at `$ANDROID_NDK_HOME/simpleperf/`.

`mobile-dev` and `mobile-release` in the examples are profile names of your own choosing. Section 8 defines them.

```bash
# Push the unstripped .so built with the on-device debug profile
adb push target/aarch64-linux-android/mobile-dev/libmycrate.so /data/local/tmp/

# Record with a call graph while the app runs.
# The app must be debuggable, or the device must be rooted.
adb shell simpleperf record \
  -p $(adb shell pidof com.example.app) \
  --call-graph dwarf \
  --duration 30 \
  -o /data/local/tmp/perf.data

adb pull /data/local/tmp/perf.data .
```

`-g` is the short form of `--call-graph dwarf`.

Generate a flamegraph with Inferno, which the NDK bundles:

```bash
python3 $ANDROID_NDK_HOME/simpleperf/inferno.py -sc --record_file perf.data
# Opens flamegraph.html
```

Or with the standalone Rust `inferno` tool:

```bash
cargo install inferno
simpleperf report-sample --show-callchain perf.data | inferno-flamegraph > flame.svg
```

To convert the recording for other viewers:

```bash
simpleperf report-sample --protobuf perf.data -o perf.trace
```

### Perfetto (system-wide tracing)

Use Perfetto when you need the native profile next to scheduler, binder and app frame data.

```bash
adb shell perfetto -c - --txt -o /data/local/tmp/trace <<'EOF'
buffers { size_kb: 65536 }
data_sources { config {
    name: "linux.process_stats"
    target_buffer: 0
}}
data_sources { config {
    name: "linux.perf"
    target_buffer: 0
    perf_event_config {
        timebase { frequency: 999 }
        callstack_sampling { kernel_frames: true }
    }
}}
duration_ms: 10000
EOF

adb pull /data/local/tmp/trace .
# Open at https://ui.perfetto.dev
```

### Symbolication and memory debugging

Offline symbolication with `ndk-stack` and `llvm-addr2line`, HWASan builds, Android Studio LLDB and the native memory profiler are covered in [references/android-profiling.md](references/android-profiling.md).

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

Benchmark structure, `Throughput` reporting, statistical configuration and async benchmarks are in [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md).

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
| `lto = false` | Fast | Baseline | Dev builds |
| `lto = "thin"` | Moderate | +5-15% | Most release builds |
| `lto = "fat"` | Slow | +15-30% | Maximum performance or minimum size |
| `codegen-units = 1` | Slowest | Best | Always pair with LTO for release |

`opt-level = "z"` trades throughput for size. Measure it. On a compute-bound hot path `opt-level = 3` can be the better ship setting even on mobile.

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
| `simpleperf record` gives permission denied | App is not debuggable | Set `android:debuggable="true"`, or run `adb shell` as root |
| ASan build fails on Android | ASan is unsupported since NDK r26 | Use HWASan |
| HWASan does nothing on an emulator | HWASan is ARM64-only | Use a physical ARM64 device or an ARM64 emulator image |
| Panic reaches logcat with no backtrace | Panic hook not installed, or installed before logging init | Install the hook after logging init |
| `cargo flamegraph` fails on Linux | `perf_event_paranoid` too high | Set it to 1 or lower |
| `cargo flamegraph` fails on macOS | DTrace blocked | Run with `sudo`; check SIP |
| Benchmark results swing by more than 10% between runs | Thermal or scheduler noise | Fix the power state, close background load, raise `sample_size` |
| Binary grew after a dependency bump | New monomorphizations or new codegen | `cargo bloat --crates` then `cargo llvm-lines` on the top crate |

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
| Save a benchmark baseline | `cargo bench --locked -p my-crate -- --save-baseline before` |
| Build timing report | `cargo build --locked --release --timings` |
| Cache hit rate | `sccache --show-stats` |

---

## References

- [references/cargo-flamegraph-setup.md](references/cargo-flamegraph-setup.md) — flamegraph prerequisites, install, and the Criterion authoring reference.
- [references/android-profiling.md](references/android-profiling.md) — HWASan, offline symbolication, panic backtraces, Android Studio LLDB and native memory profiler.
- [references/build-time-optimization.md](references/build-time-optimization.md) — sccache, cross-compilation matrix, workspace splitting, linkers.
- Android NDK simpleperf documentation: `$ANDROID_NDK_HOME/simpleperf/doc/`
- Perfetto UI: https://ui.perfetto.dev
- DHAT viewer: https://nnethercote.github.io/dh_view/dh_view.html

## Related skills

- `cargo-workflows` — workspace layout, feature flags, profile plumbing.
- `rust-discipline` — allocation and clone anti-patterns on hot paths.
- `rust-sanitizers-miri` — HWASan, ASan, TSan and Miri for correctness under optimization.
- `rust-debugging` — backtraces, LLDB, and crash triage.
- `rust-observability` — tracing spans and structured timing in production.
- `rust-android-build` — NDK toolchain, target matrix, Gradle packaging.
- `rust-jni` and `uniffi-boundary` — FFI surface size and panic handling at the boundary.
- `rust-panic-safety` — `catch_unwind` at the boundary and the `panic` profile setting.
- `rust-test-tools` — benchmark harness setup and regression gating.
