# Android native debugging

Everything here needs a device or an emulator and the NDK. Work through it only after the
host reproduction in [SKILL.md](../SKILL.md) has failed, because every step costs more
than the same step on the host.

### Logcat filtering

```bash
# Filter your own native tags (the tags you pass to the logger init in JNI_OnLoad)
adb logcat -s my-native-tag:V my-other-native-tag:V

# Filter crash, panic, and abort output regardless of tag
adb logcat | grep -E "PANIC:|backtrace|signal|SIGABRT|SIGSEGV"

# Native crash, Java runtime, and stdout/stderr redirect channels.
# Quote the specifiers: an unquoted "*" is a glob in the shell.
adb logcat -s 'RustStdoutStderr:V' 'AndroidRuntime:E' 'DEBUG:*' 'libc:*'
```

If the library configures no log tag, nothing Rust prints reaches logcat. The
crash channels (`DEBUG:*`, `libc:*`, `AndroidRuntime:E`) still work, but they
give you a signal and an address, not a panic message. Wire logging first.

### Route tracing to logcat

```text
tracing macros
  -> tracing_subscriber::registry()
       -> a layer that forwards events to android_logger
       -> optional ring-buffer layer that keeps recent events for the UI to poll
log crate (from dependencies that use log, not tracing)
  -> LogTracer -> tracing
```

Initialize once, from `JNI_OnLoad` or the UniFFI init export:

1. Call `android_logger::init_once` with your tag and a default level.
2. Call `LogTracer::init()` so dependencies that use the `log` crate are captured.
3. Build the `tracing_subscriber` registry with your layers and set it global.
4. Install the panic hook, so panics reach the same sink.

Use `Debug` as the default level in debug builds and `Info` in release. Export
your own runtime override from the library, so you can raise one scope without a
rebuild. Give it a set function and a clear function, for example
`set_log_scope_level("network", LevelFilter::Trace)` and
`clear_log_scope_level("network")`. Build both on a
`tracing_subscriber::reload::Layer`, which is the supported way to change a
filter after the subscriber is global.

A ring-buffer layer next to the logcat layer lets the app attach the last N
events to a bug report. That is the only way to get logs from a user who cannot
run `adb`.

### RUST_BACKTRACE on Android

`RUST_BACKTRACE` is **not inherited** by an Android app process. Setting it in
your shell, in Gradle, or in the run configuration does nothing.

Options, in order of preference:

1. Install the panic hook with `Backtrace::force_capture()` (above). This is the
   only option that works inside the app process.
2. For a standalone test binary pushed to the device, the environment does work:

   ```bash
   adb push target/aarch64-linux-android/debug/my_test_binary /data/local/tmp/
   adb shell "cd /data/local/tmp && chmod +x my_test_binary && RUST_BACKTRACE=1 ./my_test_binary"
   ```

### Tombstone analysis after a native crash

```bash
# List and pull the newest tombstone
adb shell ls -lt /data/tombstones/ | head -5
adb pull /data/tombstones/tombstone_00

# Or collect everything, including tombstones, in one archive
adb bugreport bugreport.zip
```

Read the tombstone in this order:

1. `signal` line — 6 (SIGABRT) is an abort or a caught-then-aborted panic,
   11 (SIGSEGV) is a memory fault, 7 (SIGBUS) is usually misalignment.
2. `backtrace:` block — find the first frame inside your `.so`. Note the offset
   in `libmy_ffi.so+0x1234` form; that offset is what you feed to addr2line.
3. `abort message:` — present for `abort()` and for the Android `libc` aborts.
   A Rust panic message appears here only if your hook logged it.

### Symbolicate with addr2line (NDK)

```bash
# Locate the NDK addr2line. The command substitution expands the host glob;
# a plain assignment keeps the "*" literal.
ADDR2LINE=$(echo "$ANDROID_NDK_HOME"/toolchains/llvm/prebuilt/*/bin/llvm-addr2line)

# Symbolicate offsets from the tombstone against the UNSTRIPPED .so
# -C demangles, -f prints the function name, -e names the binary
$ADDR2LINE -Cfe target/aarch64-linux-android/debug/libmy_ffi.so 0x12345 0x67890
```

The `.so` must be the exact build that ran on the device, and it must not be
stripped. Gradle strips the packaged `.so`; symbolicate against the Cargo output
in `target/<triple>/<profile>/`, not against the one unpacked from the APK. See
[rust-android-build](../rust-android-build/).

### Build for a device

```bash
# Build the cdylib crate for the device ABI
cargo build --locked -p my-ffi --target aarch64-linux-android            # debug
cargo build --locked -p my-ffi --target aarch64-linux-android --release  # release, needs profile debug = true
```

### LLDB via Android Studio

1. Open the Android project in Android Studio.
2. Run > Edit Configurations > Debugger tab > Debug type: **Dual (Java + Native)**.
3. Add a symbol search path that points at the Cargo output directory for the
   device ABI, for example `target/aarch64-linux-android/debug/`.
4. Set breakpoints in the Rust source files.
5. Run with the debugger attached. Studio pushes and starts `lldb-server` on the
   device for you.

If breakpoints stay unresolved, the symbol path is wrong or the packaged `.so`
does not match the one in the symbol path. Rebuild both from the same commit.

---

