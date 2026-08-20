---
name: rust-debugging
description: Use when you debug a native Rust crash, panic, or hang across an FFI boundary. Covers host-first reproduction with RUST_BACKTRACE, rust-lldb and rust-gdb, Android logcat filtering, tombstone analysis, symbolication with llvm-addr2line and atos, LLDB attach from Android Studio and Xcode, panic hooks that work without RUST_BACKTRACE, catch_unwind at JNI exports, UniFFI panic and error propagation into Kotlin and Swift, tracing spans routed to logcat, tokio-console for async stalls, and a panic-to-cause triage table. Triggers on "native crash", "tombstone", "addr2line", "RUST_BACKTRACE", "lldb-server", "JNI panic", "UniFFI panic", "rust-gdb pretty-printers", or "debug async Rust".
license: BSD-3-Clause
---

# Rust Debugging (Host First, Then Android and iOS)

## Purpose

Debug Rust libraries and binaries that crash, panic, or misbehave, including
libraries that run behind an FFI boundary on mobile. Use one order of attack:

1. **Host** (macOS or Linux) — the fastest path. Run a CLI or a test that drives
   the same code, set `RUST_BACKTRACE=1`, attach `rust-lldb` or `rust-gdb`. No
   device, no emulator, no bindings layer.
2. **Android** — logcat, tombstones, `llvm-addr2line` against the `cdylib`, LLDB
   from Android Studio.
3. **iOS** — `atos` against the `.dSYM`, LLDB from Xcode against the `staticlib`.

Move to a device only after you prove the bug does not reproduce on the host.
A host repro gives you a debugger, a backtrace, a sanitizer, and a fast loop.

## Decision Rule: Where To Debug

| Symptom | Start here |
|---|---|
| Panic message and a Rust backtrace are visible | Host. Write a test that calls the same function. |
| Crash only under a specific input file or payload | Host. Feed the input to a CLI or a unit test. |
| Crash only on device, no panic message | Android or iOS. Pull the tombstone or crash report. |
| Signal 11 (SIGSEGV) with no Rust frames | Native memory bug. Symbolicate first, then see [rust-sanitizers-miri](../rust-sanitizers-miri/). |
| Kotlin or Swift gets an error but Rust logs nothing | FFI boundary. See "Panics At The FFI Boundary". |
| Process hangs, no CPU load | Async stall or deadlock. See "Async Debugging". |
| Snapshot or golden test output changed | Not a crash. Diff the output before you open a debugger. |

---

## 1. Host Debugging

### Run with backtraces

```bash
# Backtrace on panic
RUST_BACKTRACE=1 cargo run -p my-cli -- <args>

# Full backtrace, including std and runtime frames (slow, most informative)
RUST_BACKTRACE=full cargo run -p my-cli -- <args>

# Same for tests
RUST_BACKTRACE=1 cargo test -p my-crate -- --nocapture
```

If your workspace root is not the crate root, pass the manifest explicitly:

```bash
RUST_BACKTRACE=1 cargo run --manifest-path path/to/Cargo.toml -p my-cli -- <args>
```

### Attach rust-lldb (macOS) or rust-gdb (Linux)

`rust-lldb` and `rust-gdb` are rustup wrapper scripts that load the Rust
pretty-printers, so `String`, `Vec`, `Option`, and `Result` print in Rust syntax
instead of raw struct fields.

```bash
# Build a debug binary first
cargo build -p my-cli

# Launch under the debugger. Use absolute paths for input files to avoid
# surprises from the debugger working directory.
rust-lldb target/debug/my-cli -- <args>

# Linux
rust-gdb target/debug/my-cli
```

Essential commands inside the session:

```text
# Break on panic
(lldb) b rust_panic
(gdb)  break rust_panic

# Break on a function by full path
(lldb) b my_crate::module::function_name
(gdb)  break my_crate::module::function_name

# Run, then inspect on the break
(lldb) run
(lldb) frame variable
(lldb) p my_vec
(lldb) thread backtrace all

(gdb)  run <args>
(gdb)  bt full
```

For the full command reference, including manual pretty-printer setup, closure
and trait-method breakpoints, thread commands, CodeLLDB launch configurations,
and symbol demangling, read
[references/rust-gdb-pretty-printers.md](references/rust-gdb-pretty-printers.md).

### The dbg! macro

```rust
let result = dbg!(decode(&data));
// prints: [src/lib.rs:171] decode(&data) = Ok(Decoded { .. })
```

`dbg!` writes to stderr and prints file, line, expression, and value. It is fine
on the host. It is **not visible in logcat** on Android, and it is noise in a
release build. Use `tracing::debug!` for anything that must survive on a device.
Remove `dbg!` calls before you commit — `clippy::dbg_macro` catches leftovers
(see [rust-lints](../rust-lints/)).

### Build for debugging

```bash
# Host debug build, fastest iteration
cargo build -p my-cli

# Release build. It carries debug info only with the profile settings below.
cargo build --locked --release
```

A release build carries no debug info by default, which makes every device
backtrace useless. Turn it on:

```toml
# Cargo.toml of the workspace
[profile.release]
debug = true          # emit DWARF in release
strip = false         # do not strip symbols from the artifact you symbolicate
```

Keep the unstripped artifact. Ship the stripped one, archive the unstripped one,
and symbolicate against the archived copy. An address means nothing without the
exact binary that produced it.

### Structured logging with tracing

A `tracing` span records entry, exit, and the fields you attach. That is what
you need for a bug that only appears under concurrency or under one input.

```rust
use tracing::{debug, error, info, instrument, warn};

#[instrument(skip(payload))]           // auto-trace entry and exit with arguments
fn decode(payload: &[u8]) -> Result<Decoded, DecodeError> {
    info!(len = payload.len(), "decoding");
    if payload.is_empty() {
        warn!("empty payload");
    }
    // ...
}
```

`skip` the large arguments. A `#[instrument]` without `skip` formats every
argument on every call, which is slow and floods the log.

Filter at run time with `RUST_LOG`:

```bash
RUST_LOG=my_crate=debug,my_other_crate=trace cargo run -p my-cli -- <args>
```

Add `tracing-subscriber` with the `env-filter` feature to make `RUST_LOG` work.
See [rust-observability](../rust-observability/) for the full subscriber setup.

---

## 2. Panics At The FFI Boundary

**Rule: a Rust panic must never unwind across an `extern` boundary.** Unwinding
into non-Rust frames is undefined behavior. On `extern "C"` and `extern "system"`
functions the compiler inserts an abort, so the process dies with SIGABRT and you
lose the panic message unless you logged it first.

Two protections, and you need both:

1. Catch the unwind at every export.
2. Install a panic hook that logs the message and a backtrace before the unwind
   starts.

### Catch the unwind at raw JNI exports

Wrap the body of every `extern "system"` export:

```rust
use std::panic::{catch_unwind, AssertUnwindSafe};

#[unsafe(no_mangle)]
pub extern "system" fn JNI_OnLoad(_vm: JavaVM, _reserved: *mut c_void) -> jint {
    match catch_unwind(|| {
        ignore_sigpipe();
        init_android_logging("my-native-tag");
        install_panic_hook();
        jni::sys::JNI_VERSION_1_6
    }) {
        Ok(version) => version,
        Err(_) => jni::sys::JNI_ERR,
    }
}
```

For individual JNI methods, `jni` 0.22 gives you `jni::EnvUnowned::with_env`,
which catches the panic and returns a `#[must_use]` `EnvOutcome`. Exit through
`resolve`, which rebuilds an `Env` and lets an `ErrorPolicy` log and throw:

```rust,ignore
env.with_env(|env| { /* body */ })
    .resolve::<jni::errors::ThrowRuntimeExAndDefault>()
```

Write your own `ErrorPolicy` when an error and a caught panic need different
log lines. `into_outcome()` gives the raw tri-state, but then nothing can throw.

When you add a new JNI export, use `EnvUnowned::with_env` or wrap the body in
`catch_unwind(AssertUnwindSafe(|| { ... }))`. There is no third option. See
[rust-jni](../rust-jni/) and [rust-panic-safety](../rust-panic-safety/).

### UniFFI panic and error propagation

UniFFI generates the boundary scaffolding, so you do not write `catch_unwind`
at each export. You still must know what the other side sees:

| Rust value | Kotlin | Swift |
|---|---|---|
| `Ok(v)` | the return value | the return value |
| `Err(E)` where `E` is your `#[uniffi(flat_error)]` or exported error enum | a sealed exception hierarchy, one subclass per variant | `enum E: Error`, one case per variant |
| `panic!(..)` caught by the scaffolding | UniFFI's own internal exception, **not** a subclass of your error type | UniFFI's own internal error, **not** a case of your error enum |

Consequences for triage:

- An exception that is **not** one of your declared error variants means a Rust
  panic, not a handled error. The panic message rides in the exception text.
- Do not add an `Internal` variant to your boundary error enum and expect
  panics to arrive in it. They do not. Convert the panic into a real `Err` on
  the Rust side if the caller must handle it.
- Keep the internal error type separate from the boundary error type. Map the
  internal type to the boundary enum in the FFI crate, so the host never sees
  internal variants and a new internal variant is not a breaking API change.
  See [uniffi-boundary](../uniffi-boundary/) and
  [ffi-error-progress-cancel](../ffi-error-progress-cancel/).

### Panic hook that works without RUST_BACKTRACE

```rust
use std::backtrace::Backtrace;

pub fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let backtrace = Backtrace::force_capture();
        log::error!("PANIC: {info}\n{backtrace}");
    }));
}
```

`Backtrace::force_capture()` captures unconditionally and ignores
`RUST_BACKTRACE`. This is the only way to get a backtrace inside an app process
that you cannot pass environment variables to. Call the hook from your library
init, and route `log` or `tracing` output to the platform log (below).

### SIGPIPE

A Rust library inside an app process inherits the host process signal
disposition. If a socket peer disconnects while you write, the default `SIGPIPE`
handler kills the process with no Rust panic and no useful log. Restore the
ignore disposition during init:

```rust
pub fn ignore_sigpipe() {
    unsafe { libc::signal(libc::SIGPIPE, libc::SIG_IGN) };
}
```

Then handle `ErrorKind::BrokenPipe` from the write call like a normal error.

---

## 3. Android Debugging

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

## 4. iOS Debugging

### Crash symbolication

Frames from a Rust `staticlib` linked into the app binary appear unsymbolicated
in Xcode Organizer or a crash-reporting service. Symbolicate against the `.dSYM`
produced with the app binary:

```bash
# One address from a crash report; -l is the load address of the image
atos -arch arm64 -o MyApp.app.dSYM/Contents/Resources/DWARF/MyApp \
    -l <load_address> <crash_address>
```

The `.dSYM` is the only reliable input for a crash address, because the linker
moves the archive code into the app binary. Use `llvm-addr2line` against the
unstripped static archive only for an offset that you already know is inside one
archive member, for example an offset printed by your own code:

```bash
llvm-addr2line -Cfe target/aarch64-apple-ios/debug/libmy_ffi.a 0x12345
```

### Build for iOS

```bash
cargo build -p my-ffi --target aarch64-apple-ios       # device
cargo build -p my-ffi --target aarch64-apple-ios-sim   # simulator (Apple silicon)
```

### LLDB via Xcode

1. Open the app project or the SwiftPM package in Xcode. If the Rust library is
   linked as an XCFramework binary target, breakpoints in Rust still resolve
   through the DWARF in the linked slice.
2. Product > Scheme > Edit Scheme > Run > Diagnostics — enable **Address
   Sanitizer** or **Thread Sanitizer** when you chase a memory or race bug. Do
   not enable both at once.
3. Run on device or simulator with the debugger attached.
4. Set breakpoints in the Rust source files, or from the LLDB console
   (Debug > Activate Console):

```text
(lldb) b my_crate::module::function_name
(lldb) b rust_panic
(lldb) thread backtrace all
```

When you must debug only the Rust library, do not use Xcode. Run the same code
from a host CLI under `rust-lldb` instead (section 1).

---

## 5. Async Debugging

Use `#[instrument]` spans first. The enter and exit events tell you which task
stopped making progress, and with what arguments.

`tokio-console` shows live task state, poll counts, and busy time. It needs the
`tokio_unstable` cfg and it opens a TCP port, so treat it as a local development
tool and never ship it in a mobile or production build:

```bash
# Add console-subscriber as a temporary dev dependency, then:
RUSTFLAGS="--cfg tokio_unstable" cargo run -p my-cli
tokio-console
```

Triage rules:

- A task with a high poll count and near-zero busy time is spinning on a waker.
- A task that never polls again after a known point is waiting on a channel or a
  lock that no one releases.
- Blocking work inside an async task starves the runtime. Move it to
  `spawn_blocking`.

See [rust-async-internals](../rust-async-internals/) for the poll and waker model
behind these symptoms.

---

## 6. Snapshot And Golden Test Failures

A byte diff against the fixture means behavior changed: read the diff, and
re-bless the fixture only in the same commit that explains why. A panic inside
the test is a crash bug: leave the fixture alone and reproduce on the host with
a debugger. See [rust-test-tools](../rust-test-tools/).

---

## 7. Panic Triage Quick Reference

| Signal or message | Likely cause | Next step |
|---|---|---|
| `called Option::unwrap() on a None value` | Unwrap on `None` | Find the optional field. Replace with `ok_or` plus `?`. |
| `called Result::unwrap() on an Err value` | Unwrap on error | Propagate with `?` and keep the source error. |
| `index out of bounds: the len is N but the index is M` | Slice or `Vec` out of range | Check the index math against a length that came from untrusted input. |
| `attempt to subtract with overflow` | Integer underflow, debug build | Use `checked_sub` or `saturating_sub`. The release build wraps silently, so this is a real bug either way. |
| `attempt to multiply with overflow` | Integer overflow in size math | Use `checked_mul` before you allocate. |
| Signal 6 (SIGABRT), no Rust frames | Abort: double panic, explicit `abort()`, `panic = "abort"` profile, or a panic that crossed an `extern` boundary | Install the panic hook, then reproduce. See section 2. |
| Signal 11 (SIGSEGV) | Null or dangling pointer, use-after-free in `unsafe` or in a C dependency | Symbolicate, then run the host repro under ASan. See [rust-sanitizers-miri](../rust-sanitizers-miri/). |
| Signal 7 (SIGBUS) | Misaligned or invalid memory access, often a bad pointer cast | Audit the `unsafe` cast. See [rust-unsafe](../rust-unsafe/). |
| Process killed silently while writing to a socket | `SIGPIPE` | Call `ignore_sigpipe()` during init. See section 2. |
| Host exception or error that is not one of your declared FFI error variants | Rust panic caught by the UniFFI scaffolding | The panic message is in the error text. Fix the panic; do not add a catch-all variant. |
| `JNI DETECTED ERROR IN APPLICATION` in logcat | Wrong JNI usage: stale local ref, wrong signature, missing exception check | See [rust-jni](../rust-jni/). |
| Deadlock or hang, no CPU load | Lock ordering or a channel with no sender | Attach the debugger and run `thread backtrace all`. |

---

## Checklist Before You Say "Cannot Reproduce"

- [ ] You tried a host repro with `RUST_BACKTRACE=full`.
- [ ] The build under test has `debug = true` and is not stripped.
- [ ] A panic hook with `Backtrace::force_capture()` is installed in the library init.
- [ ] Logging is initialized before the code path you suspect runs.
- [ ] You symbolicated against the exact binary that crashed, not a rebuild.
- [ ] You checked the tombstone or crash report signal, not only the app-level message.
- [ ] You ran the host repro under a sanitizer if the signal was 11 or 7.

---

## Related Skills

- [rust-panic-safety](../rust-panic-safety/) — `catch_unwind`, unwind safety, abort profiles
- [rust-jni](../rust-jni/) — JNI export patterns, local refs, exception handling
- [uniffi-boundary](../uniffi-boundary/) — error enums and boundary type mapping
- [ffi-error-progress-cancel](../ffi-error-progress-cancel/) — error, progress, and cancellation across FFI
- [rust-unsafe](../rust-unsafe/) — `unsafe` review and raw-pointer FFI patterns
- [rust-sanitizers-miri](../rust-sanitizers-miri/) — ASan, TSan, and Miri
- [rust-async-internals](../rust-async-internals/) — `Future`, poll model, waker debugging
- [rust-observability](../rust-observability/) — `tracing` subscriber and span design
- [rust-android-build](../rust-android-build/) — NDK targets, ABI packaging, stripping
- [rust-performance](../rust-performance/) — flamegraphs, `cargo-bloat`, Criterion
- [rust-test-tools](../rust-test-tools/) — snapshot tests, fixtures, test harnesses
