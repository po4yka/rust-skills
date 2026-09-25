---
name: rust-panic-safety
description: Use when guarding an extern "C", extern "system", or JNI entry point with catch_unwind, choosing panic = "unwind" or "abort", installing a panic hook, disposing of a panic payload, or triaging an abort such as "panic in a function that cannot unwind". Also use when a panic can escape a foreign callback, spawned task, thread, or Drop, or when replacing unwrap or expect on an FFI-reachable path. Owns the panic policy at a C ABI boundary.
license: BSD-3-Clause
---

# Rust panic safety

## Start here: find the boundaries

```bash
# Every function that foreign code can call.
rg -n 'extern "(C|system|C-unwind|system-unwind)"|#\[jni_mangle|native_method!' --type rust

# Every symbol that leaves the crate unmangled.
rg -n '#\[unsafe\(no_mangle\)\]|#\[no_mangle\]|#\[export_name|#\[unsafe\(export_name' --type rust

# Every guard that already exists.
rg -n 'catch_unwind|AssertUnwindSafe|with_env' --type rust

# Every panic strategy declared in the tree: manifests, config files, and rustflags.
rg -n --hidden 'panic\s*=\s*"?(abort|unwind)' \
  -g '**/Cargo.toml' -g '**/.cargo/config.toml' -g '**/.cargo/config'
```

Compare list 1 with list 3. A `native_method!` entry has a generated `with_env` guard, unless
it is `raw` or sets `catch_unwind = false`. An entry point in list 1 with no guard and no
documented abort policy (Rule 1) is a finding. Derive the lists from the tree for each review;
do not reuse an old count. This skill names other skills; use them when they are installed.

## Verify a boundary change

| Claim | Check | What a green result does not prove |
|---|---|---|
| Every entry point has a guard | The inventory above, list 1 against list 3 | That the guard maps every outcome |
| The shipped build unwinds | `cargo rustc --locked -p <boundary-crate> --lib --release --target <shipping-triple> -- --print cfg` prints `panic="unwind"` | That every entry point has a guard |
| A panic returns the reserved code | A Rust test that calls the `extern` function itself (Rust can call it directly) with a forced panic and asserts the reserved panic code | That the shipped build unwinds: Cargo builds tests with unwind |
| No new unguarded panic sites | `cargo clippy --locked --all-targets -- -D warnings` with `-p` for every crate on the FFI path (or `--workspace`), with the lints below | That each kept `.expect` invariant holds. Clippy does not see every panic site: overflow, panicking std APIs (`split_at`, `RefCell::borrow_mut`, `copy_from_slice`), dependency panics |
| No std-checked precondition fires on tested paths | `cargo test --locked` in the default debug profile | Soundness: the checks cover a few std preconditions. Run Miri; where Miri cannot run the foreign code, run ASan on the host or HWASan or MTE on a device (the `rust-sanitizers-miri` skill) |

Run the `--print cfg` check with the same `--target`, `--profile`, and environment as the
shipping build. It then reflects every source of the strategy: the root manifest profile,
`[profile.<name>]` in `.cargo/config.toml`, `CARGO_PROFILE_<NAME>_PANIC`, `RUSTFLAGS`,
`CARGO_ENCODED_RUSTFLAGS`, `build.rustflags`, and `target.<triple>.rustflags`. Without
`--target`, Cargo builds for the host and skips the rustflags of the shipping triple, so the
check can print `unwind` for a library that ships with `abort`. Replace `--release` with
`--profile <name>` when the shipping profile is not `release`. When the boundary decodes
untrusted input, fuzz the decoder behind it: a guard turns each panic into a status code and
hides it from every other test. See the `rust-test-tools` skill.

## Done when

- Every inventory entry point has a guard, or a comment that states abort as its policy.
- Every `extern` body is a guard plus a delegation call to a testable plain Rust function.
- The `--print cfg` check prints `panic="unwind"` if any guard uses `catch_unwind`.
- The panic exit differs from every domain error exit.
- The boundary discards the payload through a second guard. Only a run-once loader such as
  `JNI_OnLoad` can leak it instead, with `ManuallyDrop::new`, never `mem::forget`.
- The bootstrap installs the hook once. It emits only a closed site code plus numeric location.
  No shipped log, exception message, or tombstone can carry user data from a panic.
- Every `AssertUnwindSafe` has a comment that names the invariant.
- Every crate on the FFI path denies `clippy::unwrap_used` and `clippy::panic`.
- No `Drop` can panic. Every spawned task or thread reports its panic at a join point or
  through its own guard.

## Failure triage

| Symptom | Likely cause | Action |
|---|---|---|
| Host dies with `SIGABRT` on Unix, or exit status `0xC0000409` (fail fast) on Windows; stderr, when captured, shows `panic in a function that cannot unwind` | A panic reached an unguarded `extern "C"` or `extern "system"` function | Find the entry point in the inventory; add the guard, or document abort as its policy |
| `catch_unwind` never returns `Err`, process still dies | The build uses `panic = "abort"` | Run the `--print cfg` check with the shipping `--target`; fix the profile source, `RUSTFLAGS`, `build.rustflags`, or `target.<triple>.rustflags` |
| `catch_unwind` returns `Ok`, work silently missing | The panic happened on another thread or in a spawned task | Join the handle and inspect `JoinError` |
| `fatal runtime error: Rust cannot catch foreign exceptions, aborting` | A C++ or other foreign exception reached `catch_unwind` | Catch it on the foreign side; never let it enter Rust |
| `panic in a destructor during cleanup`, then `thread caused non-unwinding panic. aborting.` | A `Drop` implementation panicked while a panic was in flight | Make the `Drop` infallible |
| The boundary catches a panic and then aborts | Dropping the caught payload panicked | Dispose of the payload inside a second guard and keep a second payload in `ManuallyDrop` |
| `memory allocation of N bytes failed`, then abort | Allocation failure, which is not a catchable panic | Bound the size; use `Vec::try_reserve` for large or input-driven buffers |
| `unsafe precondition(s) violated: ...`, then abort, when debug assertions are on | An unsafe call broke its precondition. This is undefined behaviour, not a panic path | Fix the call; see the `rust-unsafe` skill. A build without debug assertions skips the check and runs the UB |
| The bounded panic record has no message or backtrace | This is the shipped privacy contract | Reproduce on the host with `RUST_BACKTRACE=full`, or symbolicate the crash artifact offline |
| Every later call fails with a poison error | An earlier panic poisoned a shared lock | Decide the poison policy; report the original panic, not the poison |
| `building tests with panic=abort is not supported without -Zpanic_abort_tests` | `-C panic=abort` in `RUSTFLAGS`, `build.rustflags`, or `target.<triple>.rustflags` reaches the test build. The manifest `panic` key alone cannot cause this | Remove the flag from test runs, for example set it only in the shipping build command. Or use nightly `-Zpanic-abort-tests`, which runs each test in its own process |
| Panic location points into a macro or `core` | The real cause is an index, a slice range, or an overflow | Reproduce with `overflow-checks = true` and a debug build; see the `rust-debugging` skill |

## Silent hazards

A test run rarely shows these defects.

- Treat every panic message as a log line. On Android, `panic = "abort"` copies a `&str` or
  `String` payload into the tombstone `Abort message` through `android_set_abort_message`.
  UniFFI copies it into the foreign exception message. Never put secrets or user data in a
  panic, `expect`, or `unreachable!` message.
- `Result::unwrap` and `Result::expect` append the error's `Debug` text. An error type on an
  FFI path must not carry input data in `Debug`, or the call must map the error before it
  panics.
- The JNI `ThrowRuntimeExAndDefault` policy copies the error's `Display` text and a constant
  panic message into the exception. Use a fixed-message policy when that text can carry input
  data.
- Swift calls a non-throwing UniFFI export through `try!`, so a panic there ends the app. Keep
  such exports panic-free.
- `core::hint::unreachable_unchecked()` with a wrong proof is undefined behaviour, not a panic.
  Use it only with a `SAFETY` comment that proves the branch is impossible.

## Rule 1: decide what a panic does at each foreign entry point

Since Rust 1.81, a panic that reaches an `extern "C"` or `extern "system"` function aborts the
process with `panic in a function that cannot unwind`. The abort is defined behaviour, and the
host sees a native crash, not a Rust error. Before 1.81 the same unwind was undefined behaviour,
so a crate with an MSRV below 1.81 must guard every entry point.

This skill is the catalog's single home for this policy:

- Guard with `catch_unwind` every entry point whose caller must get an error instead of a dead
  process. That is the default for a library that a host process loads: a JNI library, a
  plugin, a `cdylib` behind Swift or C.
- Leave a body unguarded only where an abort is the intended result, for example a callback in a
  standalone binary. Write that intent in a comment on the function.
- `extern "C-unwind"` lets a Rust panic or a foreign exception cross the boundary. Use it only
  when the other side can unwind through it, such as C++ built with exceptions. A Java, Swift,
  or `-fno-exceptions` C caller cannot.
- A foreign exception that unwinds into Rust through a function declared `extern "C"` is
  undefined behaviour. Catch a C++ exception on the C++ side, or declare the import
  `extern "C-unwind"`.

## Choose the panic strategy before you write the guard

- `panic = "unwind"` (default) keeps panics catchable; landing pads add code. Use it when a
  panic must be survived: a shared library inside a host process, a server that isolates a
  request, any FFI boundary that returns an error to the caller.
- `panic = "abort"` aborts at the panic site. It is smaller and marginally faster. Use it when
  no guard depends on catching, for example a standalone binary where a panic is a crash
  anyway. It silently turns every `catch_unwind` guard into dead code.

```toml
[profile.release]
panic = "unwind"                # required if any entry point relies on catch_unwind
overflow-checks = true          # a wrapped length becomes a panic, not a bad slice bound
debug = "line-tables-only"      # file and line when you symbolicate a backtrace offline
```

Rules:

- Cargo reads manifest profiles only from the workspace root. A `[profile]` table in a member
  manifest has no effect, and a per-package override cannot set `panic`. A config-file
  profile, `CARGO_PROFILE_<NAME>_PANIC`, and `-C panic` in any rustflags source override the
  manifest.
- Cargo ignores the `panic` key for tests, benchmarks, build scripts, and proc macros. A
  `#[should_panic]` test therefore runs under unwind even when release aborts. Do not read a
  green test run as proof that the shipped library unwinds.
- State the reason for the strategy in a comment next to the `panic` key.

## What `catch_unwind` catches

`std::panic::catch_unwind` catches an unwinding panic that starts inside the closure, on the
same thread. The panic hook runs first, before unwinding starts. It does not catch:

- A panic on another thread. Join that thread and inspect its result.
- A process abort: a panic inside a `Drop` during unwinding, `panic in a function that cannot
  unwind`, an `unsafe precondition(s) violated` check, or an allocation failure.
- A stack overflow. That is a signal, not a panic.
- A foreign exception, in any reliable way. The result is unspecified: an abort after the
  destructors run, or `Err` with an opaque payload. Do not rely on either. Catch it on the
  foreign side.

Do not remove a guard for speed without a benchmark that shows its cost.

## `UnwindSafe` and `AssertUnwindSafe`

`catch_unwind` requires the closure to be `UnwindSafe`. The bound is a warning, not a proof:
it marks values that a panic could leave in a broken but observable state. `&mut T` and
interior-mutable types are not `UnwindSafe`.

```rust
use std::panic::{catch_unwind, AssertUnwindSafe};

// The compiler cannot prove `state` is consistent after a panic. You must.
let result = catch_unwind(AssertUnwindSafe(|| run(&mut state)));
```

When you write `AssertUnwindSafe`, add a comment that names the invariant you checked, in the
same style as a `SAFETY` comment. If you cannot name one, restore the invariant instead: drop
the object, rebuild it, or mark it poisoned so later calls fail fast.

## The guard pattern: hand-rolled C ABI

Return a status code, never a `Result` and never a panic. Reserve one code for a caught
panic so the caller can tell a domain error from a bug.

```rust
pub const OK: i32 = 0;
pub const ERR_INVALID_INPUT: i32 = -1;
pub const ERR_IO: i32 = -2;
pub const ERR_PANIC: i32 = -99;

fn discard_panic_payload(payload: Box<dyn std::any::Any + Send>) {
    let second = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(payload)));
    if let Err(payload) = second {
        // The destructor of the first payload panicked. Do not drop the second payload here.
        let _leaked = std::mem::ManuallyDrop::new(payload);
    }
}

/// # Safety
/// `ptr` must be non-null, aligned, writable for `len` bytes, and unaliased for
/// this call. `len` must not exceed `isize::MAX`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn lib_render(ptr: *mut u8, len: usize) -> i32 {
    if ptr.is_null() || len > isize::MAX as usize {
        return ERR_INVALID_INPUT;
    }
    let result = std::panic::catch_unwind(|| {
        // SAFETY: the caller guarantees the contract above.
        let buf = unsafe { std::slice::from_raw_parts_mut(ptr, len) };
        render_into(buf)
    });
    match result {
        Ok(Ok(())) => OK,
        Ok(Err(Error::InvalidInput)) => ERR_INVALID_INPUT,
        Ok(Err(Error::Io(_))) => ERR_IO,
        Err(payload) => {
            discard_panic_payload(payload);
            ERR_PANIC
        }
    }
}
```

Keep the `extern` body to a guard plus a delegation call. Put the logic in a plain Rust
function that the tests can call directly.

The payload's destructor can panic, so `discard_panic_payload` drops it inside a second guard.
It leaks the second payload with `ManuallyDrop`, a bounded leak on the double-panic path only,
so no unwind leaves the boundary. Do not inspect or format either payload.

Read `references/boundary-patterns.md` when the entry point returns a pointer or an opaque
handle, writes out-parameters, is a callback that a foreign runtime invokes, drives async work
with `block_on`, or when the crate exports enough functions to need a macro-generated `extern`
layer. It also holds the runnable proof of `discard_panic_payload`.

## JNI and UniFFI boundaries

JNI is the same rule with a Java exit path: throw a Java exception and return a neutral value
(`0`, `-1`, null) that Java never reads. A `jni` 0.22 method export guards with
`EnvUnowned::with_env` and throws only in `resolve::<Policy>()`. `JNI_OnLoad` gets the VM, not
an env, so its only guard is a raw `catch_unwind`. Call `JavaVM::from_raw` inside that guard:
it asserts non-null, and an assert outside the guard aborts. See Silent hazards for the
`ThrowRuntimeExAndDefault` message. Read `references/jni-boundary.md` when you write or
review a JNI export or `JNI_OnLoad`. The `rust-jni` skill owns the templates.

UniFFI generates the `extern "C"` glue and its own panic guard. See Silent hazards for its
message copy and Swift `try!`. Give any hand-rolled `extern "C"` in the same crate the full
guard. Read the UniFFI section of `references/boundary-patterns.md` when the crate uses UniFFI.

## Report the panic without exposing its payload

A guard that returns `-99` with no other signal turns a bug into a mystery. Install a hook
that emits one bounded structured record. Do not inspect the panic payload in shipped code.
It can contain input data, paths, identifiers, or secrets. Read `references/panic-hook.md` when
you install or review a panic hook: it holds the catalog's single copy of the `PanicSite` and
`report_panic` block.

Rules:

- Let the application-owned outermost Rust FFI bootstrap own `set_hook`. An embedded component
  exposes a redacted handler and never replaces an unknown process-global hook.
- Do not chain the default hook in a shipped embedded process. It formats the payload and file
  path. Keep it only in a local host binary whose stderr is not forwarded to telemetry.
- Map the file path to a closed site code. Emit only that code plus the bounded numeric line and
  column. Do not format `PanicHookInfo`, emit a file path, or capture a backtrace into a shipped
  platform log.
- Treat every panic message as a log line. Silent hazards lists the paths that copy it.

## `.unwrap()` and `.expect()` on FFI-reachable paths

The `rust-discipline` skill owns the general `unwrap` and `expect` rule. On a path that a
foreign caller reaches, a panic kills the host process unless a guard catches it.

Not allowed on such a path:

- `.unwrap()` or `.expect()` on a `Result` that input or the environment can make `Err`.
  Propagate with `?` and let the boundary map the error.
- `.unwrap()` or `.expect()` on an `Option` whose `None` comes from input: parsed data, a
  network reply, user configuration, an environment variable, a map lookup keyed by external
  data.
- `.expect("should never happen")`. Either state the invariant in the message, or model it in
  the type system so the case disappears. `unreachable!()` keeps the panic and states the
  intent. For `unreachable_unchecked`, see Silent hazards and the `rust-unsafe` skill.

Deny `clippy::unwrap_used`, `clippy::panic`, `clippy::todo`, `clippy::unimplemented`, and
`clippy::panic_in_result_fn` in every crate on an FFI path. Set `clippy::expect_used` and
`clippy::indexing_slicing` to at least `warn`. Set them as crate-root attributes and keep
`[lints] workspace = true`, so the crate keeps the workspace floor that the `rust-lints` skill
owns. Read `references/unwrap-audit.md` when you roll these lints out or a crate already has
many sites. It holds the crate-root block, the `clippy.toml` test exemptions (and the
`panic_in_result_fn` case, which has none), the reachability ranking, the replacement recipes,
and the `#[expect]` contract. Count the debt with a command, never from memory:

```bash
rg -n --type rust '\.unwrap\(\)|\.expect\(' \
  -g '!target/**' -g '!**/tests/**' -g '!**/benches/**' | wc -l
```

## Errors at the boundary

Keep the panic exit distinct from every error exit. A panic means a bug in Rust; an error means
an expected failure. If they share a code, you cannot triage the crash report. Read the
typed-errors section of `references/unwrap-audit.md` when you design or map the error type of a
crate on an FFI path.

## Keep data valid when a panic passes through

`catch_unwind` returns control, so whatever the closure touched is still alive. Never panic in
`Drop`: a panic in a `Drop` that runs during unwinding aborts the process. State the poisoning
policy at each `std::sync::Mutex` (the `rust-discipline` skill owns it); `parking_lot` locks do
not poison and give no warning. Read `references/unwind-state.md` when the guarded code mutates
shared state, holds a lock, or runs a section that must not half-complete. It has the restore
guard, the torn `&mut` rule, and the abort-on-unwind bomb.

## Panics in async tasks and threads

- A panic in a spawned Tokio task or `std::thread` does not unwind into the caller. It surfaces
  at the join point: `JoinError::is_panic()` or `join()` returning `Err(payload)`. Check every
  handle you keep, and pass the payload to `discard_panic_payload`.
- A panic in the future's own body does unwind through `block_on`. Wrap `block_on` in
  `catch_unwind` when a foreign caller drives it.
- A detached task whose `JoinHandle` you drop reports nothing. Keep the handle, or guard the
  task body.
- A panic that crosses a task boundary loses its location. Only the panic hook still has it, so
  install the hook before any task starts.

Read the async section of `references/boundary-patterns.md` when an entry point drives async
work. The `rust-async-internals` skill covers runtime-level panic handling and cancellation.
