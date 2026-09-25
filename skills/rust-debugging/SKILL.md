---
name: rust-debugging
description: Use when debugging a Rust crash, panic, hang, or unreadable native stack trace, on the host or inside an Android or iOS app behind JNI or UniFFI. Triggers on RUST_BACKTRACE, SIGSEGV, SIGABRT, native crash, tombstone, logcat crash output, addr2line, ndk-stack, atos, dSYM, rust-lldb, rust-gdb, lldb-server, _RNv mangled frames, JNI panic, UniFFI panic, and tokio-console for async stalls. Not for slow code or profiling; use `rust-performance`.
license: BSD-3-Clause
---

# Rust Debugging (Host First, Then Android and iOS)

Reproduce on the host first. A CLI or a test that drives the same code gives you a debugger, a
backtrace, sanitizers, and a fast loop. Move to a device only after the host repro fails. On a
device, go from logs to the tombstone or crash report, then symbolicate, and attach LLDB last.

## Where to start

| Symptom | Start here |
|---|---|
| Panic message and a Rust backtrace are visible | Host. Write a test that calls the same function. |
| Crash only under one input file or payload | Host. Feed the input to a CLI or a unit test. |
| Crash only on device, no panic message | Android or iOS. Pull the tombstone or crash report (sections 3 and 4). |
| SIGSEGV or SIGBUS with no Rust frames | Native memory bug. Symbolicate, then run the host repro under ASan, or the device build under HWASan or MTE (the `rust-sanitizers-miri` skill). |
| Kotlin or Swift gets an error, Rust logs nothing | FFI boundary. See section 2. |
| Process hangs | Deadlock or async stall. Backtrace every thread, then see section 5. |
| Snapshot or golden output changed, no panic | Not a crash. Read the diff. Re-bless only in a commit that explains why (the `rust-test-tools` skill). |

## Panic and signal triage

| Signal or message | Likely cause | Next step |
|---|---|---|
| ``called `Option::unwrap()` on a `None` value`` | Unwrap on `None` | Find the optional field. Replace with `ok_or` plus `?`. |
| ``called `Result::unwrap()` on an `Err` value`` | Unwrap on an error | Propagate with `?` and keep the source error. |
| `index out of bounds: the len is N but the index is M` | Slice or `Vec` out of range | Check the index math against a length that came from input. |
| `attempt to subtract with overflow` | Integer underflow with overflow checks on | Use `checked_sub` or `saturating_sub`. A release build wraps silently, so it is a bug either way. |
| `attempt to multiply with overflow` | Overflow in size math | Use `checked_mul` before you allocate. |
| `panic in a function that cannot unwind` | A panic reached an `extern "C"` or `extern "system"` export with no guard | Guard the export (section 2). |
| Signal 6 (SIGABRT) | Double panic, `abort()`, `panic = "abort"` (the `Abort message` holds the panic text), or an unguarded export (no `Abort message`; a `panic_cannot_unwind` frame after symbolication) | Read the tombstone `Abort message` when it is present. Check the export guards, then reproduce on the host. |
| Signal 11 (SIGSEGV) | Null or dangling pointer, use-after-free in `unsafe` or in a C dependency | Symbolicate, then run the host repro under ASan, or the device build under HWASan or MTE (the `rust-sanitizers-miri` skill). |
| Signal 7 (SIGBUS) | Misaligned or invalid memory access, often a bad pointer cast | Audit the `unsafe` cast (the `rust-unsafe` skill). |
| Process killed while it writes to a pipe or socket | SIGPIPE | Ignore SIGPIPE during init (section 2). |
| Kotlin `InternalException`, or a Swift error outside your error enum | Rust panic caught by the UniFFI guard | Fix the panic. Do not add a catch-all variant. |
| Swift fatal error on a non-throwing UniFFI call | Panic in a non-throwing export | Make the export panic-free, or return `Result`. |
| `JNI DETECTED ERROR IN APPLICATION` in logcat | Wrong JNI usage: stale local ref, wrong signature, missing exception check | See the `rust-jni` skill. |
| Frames print as `_RNv...` or `__RNv...` | The tool predates v0 mangling, the default since 1.97 | Upgrade the tool (binutils 2.36+, Linux perf 6.16+; the perf in Ubuntu 24.04 and Debian 13 is too old), or pipe through `rustfilt`. On macOS, use `c++filt -_`. |
| A grep for `_ZN` finds nothing | v0 symbols start with `_R` (`__R` in Mach-O) | Grep `_R`. `#[no_mangle]` exports keep their literal names. |
| Deadlock or hang, no CPU load | Lock ordering, or a channel with no sender | Attach the debugger and backtrace every thread. |

## Before you say "cannot reproduce"

- [ ] You tried a host repro with `RUST_BACKTRACE=1`, and under a debugger.
- [ ] The build under test has debug info, and it is not stripped.
- [ ] You symbolicated against the exact binary that crashed: same Build ID or UUID, not a rebuild.
- [ ] Logging starts before the suspect code path runs, and one test `log::info!` reaches the sink.
- [ ] You read the tombstone or crash report signal and `Abort message`, not only the app-level
      message.
- [ ] You ran the host repro under a sanitizer when the signal was 11 or 7.

## 1. Host debugging

### Backtraces

```bash
# Short backtrace on panic
RUST_BACKTRACE=1 cargo run --locked -p my-cli -- <args>

# Every frame, with addresses and std internals
RUST_BACKTRACE=full cargo run --locked -p my-cli -- <args>

# One test, with its output shown (--nocapture is deprecated since 1.88)
RUST_BACKTRACE=1 cargo test --locked -p my-crate <test_name> -- --no-capture

# Panic backtraces on, error-value backtraces off
RUST_BACKTRACE=1 RUST_LIB_BACKTRACE=0 cargo run --locked -p my-cli -- <args>
```

- `RUST_LIB_BACKTRACE` wins over `RUST_BACKTRACE` for `std::backtrace::Backtrace::capture`, which
  `anyhow` calls when it creates an error. With `RUST_BACKTRACE=1` alone, every such error pays
  for a capture. Set the variables before the process starts; std caches them at the first capture.
- v0 mangling is the default since 1.97. `RUST_BACKTRACE=full` frames now carry crate hashes, for
  example `std[5d97c59e5e5fafcc]::panicking::default_hook`. The hash changes with the toolchain and
  the build configuration, so diff `RUST_BACKTRACE=1` output, not `full` output.
- Since 1.91 the panic line carries the thread ID: `thread 'main' (6583488) panicked at
  src/lib.rs:4:23:`. Grep for `panicked at`, not for `thread 'main' panicked`.

### Debugger

`rust-lldb` and `rust-gdb` are toolchain scripts (rustup runs them through its proxy) that load the
Rust formatters, so `String`, `Vec`, `Option`, and `HashMap` print as Rust values instead of raw
fields.

```bash
cargo build --locked -p my-cli
rust-lldb target/debug/my-cli -- <args>      # macOS, or Linux with LLDB
rust-gdb --args target/debug/my-cli <args>   # Linux
```

```text
(lldb) b rust_panic                    (gdb) break rust_panic
(lldb) b my_crate::module::function    (gdb) break my_crate::module::function
(lldb) run                             (gdb) run
(lldb) frame variable                  (gdb) info locals
(lldb) thread backtrace all            (gdb) thread apply all bt
```

- In current toolchains (1.88 and later at least), the panic entry is `__rustc::rust_panic`.
  `b rust_panic` still resolves in LLDB on 1.98.1. A tool that sets the breakpoint with a
  legacy-name regex can miss it. In GDB, if `rust_panic` has no location, break on
  `__rustc::rust_panic` or `core::panicking::panic_fmt`.
- Confirm the formatters loaded before you trust a value. `(lldb) type category list` must show
  `Rust (enabled)`. A `Vec` that prints as `buf` and `len` fields means no formatters.
- Rust 1.98 removed `lib/rustlib/etc/lldb_commands`. Inside an IDE, where the wrapper does not
  run, on Rust 1.98 and later, load the formatters with `command script import` of
  `lldb_lookup.py` only. Older toolchains also need the `lldb_commands` line (see the reference).

Read [references/rust-gdb-pretty-printers.md](references/rust-gdb-pretty-printers.md) when you
load formatters by hand (Xcode, Android Studio, plain `gdb`), configure CodeLLDB, set a
closure, trait-method, or conditional breakpoint, or demangle symbols.

### Debug info

A debugger needs variable-level debug info. Symbolication needs line tables and the exact
unstripped binary.

- If `[profile.dev]` sets `debug = "line-tables-only"` or `debug = false`, the debugger shows no
  variables. Override it for one build: `CARGO_PROFILE_DEV_DEBUG=true cargo build --locked -p my-cli`.
- A release build has no debug info by default, so a device backtrace has no file or line.
  Turn it on for the artifact that you archive:

```toml
[profile.release]
debug = "line-tables-only"   # file:line for symbolication; use true to inspect variables
strip = false                # keep symbols in the artifact that you archive
```

- Ship the stripped artifact. Archive the unstripped one and symbolicate against the archived
  copy. An address means nothing without the exact binary that produced it.
- On macOS, Cargo defaults to `split-debuginfo = "unpacked"`: the DWARF stays in the object files
  under `target/`, and the binary alone has no line info. To archive a macOS host binary, build
  with `CARGO_PROFILE_RELEASE_SPLIT_DEBUGINFO=packed` and archive the `.dSYM` next to it.
- Verify the archive. On ELF, `llvm-readelf -S libmy_ffi.so | grep debug_line` prints a section.
  On Apple, `dwarfdump --uuid` prints the same UUID for the binary and its `.dSYM`.

### Logging

`dbg!`, `println!`, and the default panic hook write to stdout or stderr. An Android app process
sends both to `/dev/null`, so none of them reach logcat. Use `tracing` for output that must
survive on a device. Enable `clippy::dbg_macro` (restriction group, allow by default) to catch a
leftover `dbg!`.

For a host repro, install a subscriber that logs span timing. `EnvFilter` needs the `env-filter`
feature of `tracing-subscriber`.

```rust
use tracing_subscriber::{EnvFilter, fmt::format::FmtSpan};

fn main() {
    // Host repro only. On a device, the application bootstrap owns the subscriber.
    // The default writer is stdout; stderr keeps the program's stdout clean.
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(EnvFilter::from_default_env())
        .with_span_events(FmtSpan::CLOSE)
        .init();
}
```

```bash
RUST_LOG=my_crate=debug,my_other_crate=trace cargo run --locked -p my-cli -- <args>
```

- Without `with_span_events`, the `fmt` subscriber logs no span lifecycle. `#[instrument]` then
  only adds context to events.
- `FmtSpan::CLOSE` logs one event per closed span with `time.busy` and `time.idle`. High idle time
  means the span waited. High busy time means it did the work.
- Instrument a suspect function with `#[instrument(skip_all, fields(...))]`. The
  `rust-observability` skill owns the field rules and the device subscriber setup.

## 2. Panics at the FFI boundary

The `rust-panic-safety` skill owns the guard and hook policy. The `rust-jni` skill owns JNI
export patterns. This section maps what you see to the cause.

- Since Rust 1.81, a panic that reaches an `extern "C"` or `extern "system"` function aborts the
  process. This is defined behavior. On the host, stderr shows the panic, then `panic in a
  function that cannot unwind` and `thread caused non-unwinding panic. aborting.`, and the
  signal is SIGABRT. On Android, stderr goes nowhere and the panic text is lost. The tombstone
  shows SIGABRT, and the symbolicated backtrace has `core::panicking::panic_cannot_unwind` above
  the export.
- Fix it at the export, not at the caller. On `jni` 0.22 use
  `EnvUnowned::with_env(...).resolve::<Policy>()`. Otherwise wrap the body in `catch_unwind`.

### UniFFI panic and error propagation

UniFFI generates the boundary guard. You must still know what the foreign side sees:

| Rust value | Kotlin | Swift |
|---|---|---|
| `Ok(v)` | the return value | the return value |
| `Err(E)`, where `E` is an exported error enum | an exception subclass, one per variant | `enum E: Error`, one case per variant |
| a panic in a throwing export | `InternalException` with the panic message, **not** a subclass of your error type | a private UniFFI error, **not** a case of your error enum |
| a panic in a non-throwing export | `InternalException` | a fatal Swift error that no `catch` can handle; the app crashes |

- An exception that is not one of your declared variants is a Rust panic, not a handled error.
- The panic message rides in the Kotlin exception text, in the Swift error description, and in
  the `try!` fatal-error message of a non-throwing Swift call. A crash reporter that records
  one of them records the message.
- Do not add an `Internal` variant and expect panics to arrive in it. They do not. Convert the
  failure into a real `Err` on the Rust side when the caller must handle it. Keep a non-throwing
  export panic-free. See the `uniffi-boundary` and `ffi-error-progress-cancel` skills.

### Panic reports on a device

In a shipped build, report a panic only through the bootstrap's redacted hook: a closed site
code plus the line and the column. The `rust-panic-safety` skill has the one copy of that hook. Never
put the payload, a file path, or a backtrace into a shipped log, because panic text can hold input
data, paths, or secrets. Get the message and the backtrace from a host repro, or symbolicate the
crash offline.

On Android, `panic = "abort"` copies a `&str` or `String` panic payload into the tombstone `Abort
message` line through `android_set_abort_message` (in `panic_abort` as of Rust 1.98.1). The line
helps triage, and every crash report that uploads the tombstone also carries the panic text.
Treat every panic message as a log line.

### SIGPIPE

A write to a pipe or a socket whose peer closed can raise SIGPIPE. Its default action kills the
process with no Rust panic and no log. A host repro hides this. The Rust runtime of a binary or a
test sets SIGPIPE to ignored before `main`, so the same write returns an error there:

```rust,run
use std::io::{ErrorKind, Write};

fn main() {
    let (reader, mut writer) = std::io::pipe().unwrap();
    drop(reader);
    // A Rust `main` starts with SIGPIPE ignored, so this is an error, not a kill.
    let err = writer.write_all(b"x").unwrap_err();
    assert_eq!(err.kind(), ErrorKind::BrokenPipe);
}
```

A `cdylib` or `staticlib` inside a JVM or Swift process gets no such setup. Let the application
bootstrap set the ignore disposition during init, then handle `ErrorKind::BrokenPipe` like any
other error:

```rust
pub fn ignore_sigpipe() {
    // SAFETY: `signal` with `SIG_IGN` installs no handler code. Call it from init only.
    unsafe { libc::signal(libc::SIGPIPE, libc::SIG_IGN) };
}
```

## 3. Android debugging

Reach for the device only after the host attempt fails. The order that works:

1. **Wire logging first.** Without a logcat sink, nothing Rust prints reaches logcat. The crash
   channels still fire, but they give a signal and an address, not a panic record.
2. **Read the record and the signal.** `adb logcat | grep -E "rust_panic|SIGABRT|SIGSEGV"`, and
   `adb logcat -b crash` for the crash dump.
3. **Symbolicate.** A tombstone is addresses until `ndk-stack` or `llvm-addr2line` maps them
   against the unstripped `.so` from the same build.
4. **Attach LLDB** only when the log and the tombstone both fall short.

Read [references/android-debugging.md](references/android-debugging.md) when you filter logcat,
route tracing to logcat, need `RUST_BACKTRACE` on a device, read a tombstone, run `addr2line` or
`ndk-stack`, or attach LLDB from Android Studio.

## 4. iOS debugging

Use the same order as on Android: the crash report, then symbolication, then LLDB in Xcode.

- Symbolicate against the `.dSYM` of the app build, because the linker moves the `staticlib` code
  into the app binary. Its `dwarfdump --uuid` must match the image UUID in the crash report.
- The Xcode ASan and TSan switches do not instrument a prebuilt Rust `staticlib`. Run the
  sanitizers on a host target (the `rust-sanitizers-miri` skill).

Read [references/ios-debugging.md](references/ios-debugging.md) when you symbolicate with `atos`,
check that the `.dSYM` holds Rust lines, build for a device or the simulator, or break in Rust
from Xcode.

## 5. Async debugging

Start with the `FmtSpan::CLOSE` span timing from section 1.

`tokio-console` shows live task state. It needs `console-subscriber`, the tokio `tracing`
feature, and the `tokio_unstable` cfg. It opens a local TCP port, so use it in a local debug
build only and never ship it in a mobile or production build.

1. Add `console-subscriber` to the binary crate, enable `features = ["full", "tracing"]` on
   `tokio`, and call `console_subscriber::init()` first in `main`. `init()` installs the global
   subscriber with its own `fmt` layer, and it panics when a subscriber is already set. Remove
   the section 1 `fmt()...init()` call, or keep your subscriber and add
   `console_subscriber::spawn()` to a `tracing_subscriber::registry()` as a layer.
2. Add the cfg to the rustflags in `.cargo/config.toml`, not to `RUSTFLAGS`. The `RUSTFLAGS`
   variable replaces every config-file rustflag. Matching `[target.<triple>]` rustflags replace
   `[build]` rustflags, so add it to the table that the workspace already uses.

Remove all four changes, the rustflags entry included, before you commit. A committed
`tokio_unstable` flag reaches every CI and release build.

```toml
# .cargo/config.toml
[build]
rustflags = ["--cfg", "tokio_unstable"]
```

```bash
cargo install --locked tokio-console
cargo run --locked -p my-cli -- <args>
tokio-console        # in a second terminal
```

| tokio-console shows | Cause | Next step |
|---|---|---|
| `This task has lost its waker, and will never be woken again.` | A `poll` returned `Pending` and dropped every waker clone | Before `poll` returns `Pending`, store `cx.waker().clone()` where the event source can call `wake`. Replace the stored waker when `will_wake` returns `false` |
| `This task has never yielded (...)`, threshold 1 s | Blocking work holds a worker thread | Move it to `spawn_blocking`. The `rust-async-internals` skill has the blocking-call table |
| `This task has woken itself for more than 50% of its total wakeups` | A self-wake loop: the task busy-polls | Wait on a real event instead of waking itself |
| An idle task, never polled again, no warning | A channel or a lock that nobody releases | Backtrace every thread and find the holder |

On a device or a production build, where tokio-console cannot ship, read the stable
`tokio::runtime::RuntimeMetrics` instead: `num_alive_tasks`, `global_queue_depth`, and the
per-worker `worker_total_busy_duration` and `worker_park_unpark_count` (targets with 64-bit
atomics only). The `rust-observability` skill
covers how to export them.
