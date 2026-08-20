# Android Native Profiling, Symbolication and HWASan

Deep reference for Rust `cdylib` and `staticlib` targets running on Android devices and emulators. SKILL.md section 2 holds the routing rule and the two prerequisites you must set before you record.

## Prerequisites checklist

| Requirement | Why it matters | Where to set it |
|-------------|----------------|-----------------|
| `-C force-frame-pointers=yes` for every Android target | `simpleperf` cannot walk ARM64 stacks reliably without it; flamegraphs come out empty or truncated | Per-target `rustflags` in `.cargo/config.toml` |
| Debug symbols kept in the debug APK | Otherwise the profiler and the debugger see raw addresses | Android Gradle `keepDebugSymbols` packaging option for your `.so` |
| An unstripped `.so` kept on the host | Needed for offline symbolication of release crashes | The copy under `target/<triple>/<profile>/`, before Gradle packages a stripped one |
| A global panic hook with a bounded site record | Native panics otherwise reach logcat with no Rust site | Installed at library init, after logging init |

The frame pointer cost is negligible. One general-purpose register (`x29` on ARM64) is reserved.

Example `.cargo/config.toml` fragment:

```toml
[target.aarch64-linux-android]
rustflags = ["-C", "force-frame-pointers=yes"]

[target.armv7-linux-androideabi]
rustflags = ["-C", "force-frame-pointers=yes"]

[target.i686-linux-android]
rustflags = ["-C", "force-frame-pointers=yes"]

[target.x86_64-linux-android]
rustflags = ["-C", "force-frame-pointers=yes"]
```

---

## Record a CPU profile with simpleperf

The Android NDK ships `simpleperf` at `$ANDROID_NDK_HOME/simpleperf/`.

`mobile-dev` and `mobile-release` in the examples are profile names of your own choosing. SKILL.md section 8 defines them.

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

---

## Record a system trace with Perfetto

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

---

## Offline symbolication

### ndk-stack

`ndk-stack` symbolicates native crash logs straight from logcat. This is the first tool to reach for.

```bash
adb logcat | $ANDROID_NDK_HOME/ndk-stack \
  -sym target/aarch64-linux-android/debug/
```

Point `-sym` at the directory that holds the **unstripped** `.so`, not at the packaged copy that Gradle placed in the build output.

### llvm-addr2line

For a single address from a log line:

```bash
$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/*/bin/llvm-addr2line \
  -e target/aarch64-linux-android/debug/libmycrate.so \
  0x29ba4
```

### Privacy-safe panic records

Install a global panic hook at library init. Emit a bounded structured record
because the default panic output does not reliably reach logcat.

```rust
#[derive(Clone, Copy)]
enum PanicSite {
    Boundary,
    Engine,
    Unknown,
}

fn classify_site(file: &str) -> PanicSite {
    if file.starts_with("src/boundary/") {
        PanicSite::Boundary
    } else if file.starts_with("src/engine/") {
        PanicSite::Engine
    } else {
        PanicSite::Unknown
    }
}

pub fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let (site, line, column) = info
            .location()
            .map(|location| {
                (
                    classify_site(location.file()),
                    location.line(),
                    location.column(),
                )
            })
            .unwrap_or((PanicSite::Unknown, 0, 0));

        write_platform_panic("rust_panic", site, line, column);
    }));
}
```

Call it after the Android platform writer is initialized. The event name and
site are closed vocabulary values. The line and column are bounded integers.
Unknown paths collapse to `Unknown`. Never format `PanicHookInfo`, inspect its
payload, emit its file path, or capture a backtrace into a shipped platform log.

Filter the output:

```bash
adb logcat -s mycrate-native:E | grep 'rust_panic'
```

Preserve the unstripped `.so` for each shipped build. Symbolicate tombstones and
crash reports offline with `ndk-stack` or `llvm-addr2line`. For a local host
repro, keep the default stderr hook and use `RUST_BACKTRACE=full`.

See `rust-panic-safety` for catching the panic at the FFI boundary, and `rust-debugging` for crash triage.

---

## Memory debugging with HWASan

HWASan (Hardware Address Sanitizer) replaces ASan on Android. ASan is unsupported since NDK r26. HWASan requires an ARM64 device or ARM64 emulator image running Android 10 or later.

### Build

```bash
# Requires nightly Rust for -Z build-std
RUSTFLAGS="-Zsanitizer=hwaddress" cargo +nightly build --locked \
  -p my-android-crate \
  --target aarch64-linux-android \
  -Zbuild-std \
  --profile mobile-dev
```

### Run on device

Place a `wrap.sh` script in the APK's native library directory. This start method needs Android 14 or later:

```bash
#!/system/bin/sh
LD_HWASAN=1 exec "$@"
```

### What HWASan detects

- Heap buffer overflow and underflow
- Use-after-free
- Double-free
- Stack use-after-return
- Use of uninitialized memory (partial)

HWASan finds memory errors, not slow code. Use it when a profiling session turns up a crash or corruption, and when reviewing `unsafe`. See `rust-sanitizers-miri` and `rust-unsafe`.

---

## Android Studio integration

### Native debugging with LLDB

1. Open the Android project in Android Studio.
2. Edit the Run/Debug configuration and set the debug type to **Dual (Java + Native)**.
3. Set breakpoints in the Rust source files. Android Studio resolves them from the debug symbols.
4. Run in debug mode. LLDB attaches to the native process automatically.

This only works when the debug APK carries unstripped `.so` files with line tables. That is what the `keepDebugSymbols` packaging option guarantees.

### Native memory profiler

1. Open the **Profiler** tab.
2. Select the app process.
3. Click **Record native allocations**.
4. The profiler shows native memory next to the Java heap.

Stack traces in the native profiler need unstripped symbols. Debug builds have them. Release builds need offline symbolication.

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Flamegraph shows empty stacks | Verify `-C force-frame-pointers=yes` is set for the target in `.cargo/config.toml` |
| Symbolication shows `<unknown>` | Use the unstripped `.so` from `target/<triple>/<profile>/`, not the packaged copy |
| ASan build fails | ASan is unsupported since NDK r26; use HWASan |
| HWASan reports nothing on an x86_64 emulator | HWASan is ARM64-only; use a physical device or an ARM64 emulator image |
| Panic details are missing from logcat | Install the bounded panic-record hook after the platform writer is initialized; symbolicate the crash artifact offline |
| `simpleperf record` gives permission denied | Target a debuggable app (`android:debuggable="true"`), or run `adb shell` as root |
| Profiling a release build shows no symbols | Expected. The ship profile strips symbols. Profile the on-device debug profile instead |
| Profile numbers differ wildly between runs | Thermal throttling. Cool the device, disable background sync, and repeat the run |
