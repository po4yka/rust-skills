---
name: rust-panic-safety
description: Use when you add or review an extern "C", extern "system", JNI, or UniFFI entry point, set a Cargo panic strategy, install a panic hook, replace unwrap or expect, debug an abort, or handle a panic in an async task, spawned thread, or Drop implementation. Covers Rust panic policy, unwind versus abort, catch_unwind at FFI boundaries, panic payload disposal, typed errors, foreign status mapping, and invariant preservation.
license: BSD-3-Clause
---

# Rust panic safety

## Purpose

Use this skill when a panic can leave Rust and reach code that cannot handle it. That
includes every `extern` entry point, every callback that a foreign runtime calls, every
spawned task, and every `Drop` implementation.

The skill gives you four things:

1. A panic strategy decision for the crate and the profile.
2. A guard pattern for each boundary shape.
3. A policy for `.unwrap()`, `.expect()`, and typed errors.
4. An audit checklist and a failure triage table.

Derive the current state of the workspace from the source tree. Do not trust a memory of
where the boundaries are, and do not carry a panic count from one review to the next.

## Start here: find the boundaries

```bash
# Every function that foreign code can call.
rg -n 'extern "(C|system|C-unwind|system-unwind)"' --type rust

# Every symbol that leaves the crate unmangled.
rg -n '#\[unsafe\(no_mangle\)\]|#\[no_mangle\]|#\[export_name|#\[unsafe\(export_name' --type rust

# Every guard that already exists.
rg -n 'catch_unwind|AssertUnwindSafe|with_env' --type rust

# Every panic strategy declared in the workspace.
rg -n 'panic\s*=\s*"(abort|unwind)"' -g '**/Cargo.toml'
```

Compare list 1 with list 3. Any entry point in list 1 with no guard is a finding.

## Rule 1: a panic must never unwind out of a function the foreign side calls

Rust 1.81 and later insert an abort shim on an `extern "C"` boundary. The process dies with
`SIGABRT`. Compilers before 1.81 treat the same unwind as undefined behaviour. Both results
are fatal, and both destroy the diagnostic value of the crash: the host runtime reports a
corrupt stack, not a Rust panic message.

Never write a bare `extern` body. Wrap it, always.

The only exception is `extern "C-unwind"`, which permits an unwind to pass through when both
sides support it. Use it only when the foreign side truly expects a forced unwind. It does
not make a Rust panic safe for a C, Java, or Swift caller.

## Choose the panic strategy before you write the guard

| Strategy | `catch_unwind` | Binary size and speed | Use when |
|---|---|---|---|
| `panic = "unwind"` (default) | Works. Panics are catchable. | Landing pads add code. | You must survive a panic: a shared library inside a host process, a server that isolates a request, any FFI boundary that returns an error to the caller. |
| `panic = "abort"` | Dead. The process aborts at the panic site. | Smaller, marginally faster. | A standalone binary where a panic is a crash anyway, and no guard depends on catching. |

```toml
[profile.release]
panic = "unwind"     # required if any entry point relies on catch_unwind
overflow-checks = true
debug = 1            # keep line tables so the panic location resolves
```

Rules:

- A `cdylib` that a host runtime loads must build with `panic = "unwind"` if any entry point
  uses `catch_unwind`. `panic = "abort"` silently turns every guard into dead code.
- Cargo ignores the `panic` key for the `test` and `bench` profiles. A `#[should_panic]`
  test therefore still runs under unwind even when release aborts. Do not read that as proof
  that the shipped library unwinds.
- Set the strategy once, in the workspace root manifest, and state the reason in a comment.
  A per-crate override that disagrees with the boundary crate is a defect.

## What `catch_unwind` catches

`std::panic::catch_unwind` catches an unwinding panic that starts inside the closure, on the
same thread. It does not catch:

- A panic on another thread. Join that thread and inspect its result.
- A process abort, including a double panic and an allocation failure.
- A stack overflow. That is a signal, not a panic.
- A foreign exception. Rust aborts with `fatal runtime error: Rust cannot catch foreign
  exceptions`. Catch a C++ exception on the C++ side.
- Anything at all when the crate builds with `panic = "abort"`.

`catch_unwind` costs nothing measurable on the success path. Never skip a guard for
performance.

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
        std::mem::forget(payload);
    }
}

/// # Safety
/// `ptr` must be non-null, aligned, writable for `len` bytes, and unaliased for this call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn lib_render(ptr: *mut u8, len: usize) -> i32 {
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
function that the tests can call directly. See `references/boundary-patterns.md` for opaque
handles, out-parameters, string transfer, and Rust callbacks that a foreign runtime invokes.

The payload from `catch_unwind` is not harmless. Its destructor can panic. Dispose of it inside
a second guard, as above, and forget the second payload if that destructor also panics. This
bounded leak occurs only on the double-panic path and prevents an unwind from leaving the
boundary. Do not inspect or format either payload.

## Worked example: a JNI boundary

JNI is the same rule with a platform-specific exit path: convert the panic into a Java
exception instead of a status code.

### Loader entry point

`JNI_OnLoad` receives the VM, not an env handle, so raw `catch_unwind` is the only guard
available. Store the VM handle before the guard, and keep the whole initialization inside it
so a failed init returns `JNI_ERR` instead of unwinding into the JVM. A panic that fires
before `install_panic_hook()` runs is still contained, but the custom hook cannot report it;
do not claim otherwise in a review. The code is in
[references/boundary-patterns.md](references/boundary-patterns.md).

### Per-method entry point

`jni` 0.22 catches the panic inside `EnvUnowned::with_env` and returns a `#[must_use]`
`EnvOutcome`. You exit through `resolve`, which rebuilds an `Env` and applies an `ErrorPolicy`
to the error and to the caught panic. It is the only place an exception can be thrown.

```rust
use jni::errors::ThrowRuntimeExAndDefault;
use jni::objects::{JObject, JString};
use jni::sys::jlong;
use jni::{Env, EnvUnowned};

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_example_app_NativeBridge_nativeCreate<'local>(
    mut env: EnvUnowned<'local>,
    _thiz: JObject<'local>,
    config_json: JString<'local>,
) -> jlong {
    env.with_env(|env| -> jni::errors::Result<jlong> { create_session(env, config_json) })
        .resolve::<ThrowRuntimeExAndDefault>()
}

fn create_session(_env: &mut Env<'_>, _config: JString<'_>) -> jni::errors::Result<jlong> {
    todo!()
}
```

`ThrowRuntimeExAndDefault` throws `java.lang.RuntimeException` for an error and for a caught
panic, then returns the default value. It throws nothing when an exception is already pending.
Write your own `ErrorPolicy` when the two cases need different messages or different logging;
`jni::errors` also gives `LogErrorAndDefault` and `LogContextErrorAndDefault`.

Rules for this boundary:

- Never write a bare `extern "system" fn` body. A bare body aborts the process at the first
  panic, and the JVM reports a native crash instead of a Rust panic.
- `into_outcome()` gives the raw `Outcome::{Ok, Err, Panic}` instead of a resolved value. Take
  it only when the exit does not throw: after that call there is no `Env` left to throw with.
- Read the `with_env` documentation for the `jni` version in your lock file. The helper
  names, and the point at which the exception is thrown, changed between versions.
- On `jni` 0.21 and earlier, which has no `with_env`/`resolve`, wrap the body in `catch_unwind`
  and throw in the `Err` arm. The exit path is what matters, not the helper.
- Throw one exception type unless the caller needs to branch. A single `RuntimeException`
  keeps one catch site on the managed side. A new exception class per panic class fragments
  that handling for no gain.
- Return a neutral sentinel (`0`, `-1`, null) with the exception. The JVM raises the pending
  exception when control returns; the value is never read. Any `AndDefault` policy does this.
- Generate the `extern` layer with a macro when the crate exports many methods, so no
  hand-written body can drift from the pattern.

UniFFI generates the `extern "C"` glue and its own panic guard. Trust it for generated
scaffolding, and apply the full guard yourself to any hand-rolled `extern "C"` inside the
same crate. See the `uniffi-boundary` and `rust-jni` skills for the binding rules, and
`ffi-error-progress-cancel` for the error-object shape.

## Report the panic without exposing its payload

A guard that returns `-99` with no other signal turns a bug into a mystery. Install a hook
that emits one bounded structured record. Do not inspect the panic payload in shipped code.
It can contain input data, paths, identifiers, or secrets.

```rust
use std::sync::Once;

static HOOK: Once = Once::new();

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
    HOOK.call_once(|| {
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
    });
}
```

Rules:

- Install the hook once, at the first entry point the host calls. `set_hook` replaces the
  previous hook globally.
- Do not chain the default hook in a shipped embedded process. It formats the payload and file
  path. Keep it only in a local host binary whose stderr is not forwarded to telemetry.
- The hook runs before unwinding starts. Map the file path to a closed site code. Emit only
  that code plus the bounded numeric line and column.
- Do not format `PanicHookInfo`, inspect its payload, emit a file path, or capture a backtrace
  into a shipped platform log.
- Use `RUST_BACKTRACE=full` in a local host repro. Symbolicate a tombstone or crash report
  offline against the exact unstripped binary for an app process.
- Route the structured record through the platform sink. See the `rust-observability` skill.

## `.unwrap()` and `.expect()` policy

Every `.unwrap()` on a path a foreign caller can reach is a latent process kill. Treat the
existing count as debt, and stop the growth first.

### Allowed

- `.expect()` on a `Mutex` or `RwLock` `lock()` result. A poisoned lock is a fatal invariant
  violation, and recovery is usually wrong.
- `.unwrap()` on a conversion the compiler cannot prove but you can, with the proof written
  as a comment.
- `.unwrap()` inside a closure that a `catch_unwind` guard already wraps at the entry point.
- Anything in `#[cfg(test)]` blocks, integration tests, benchmarks, and fuzz harnesses.

### Not allowed

- `.unwrap()` or `.expect()` on a `Result<_, E>` where `E: std::error::Error`. Propagate with
  `?` and let the boundary decide.
- `.unwrap()` on an `Option<T>` where `None` comes from input: parsed data, a network reply,
  user configuration, an environment variable, a map lookup keyed by external data.
- `.expect("should never happen")`. Either prove it and write the proof, or model the
  invariant in the type system so the case disappears. `unreachable!()` keeps the panic and
  states the intent. Use `core::hint::unreachable_unchecked()` only with a `SAFETY` comment
  that proves the branch is impossible; a wrong proof there is undefined behaviour, not a
  panic. See the `rust-unsafe` skill.

### Protocol for a new `.unwrap()`

Write the infallibility proof directly above the call.

```rust
// Infallible: `buf.len() <= MAX_U32` is checked above.
let len: u32 = buf.len().try_into().unwrap();
```

A bare `.unwrap()` with no proof fails review. Enforce it with lints rather than with
vigilance:

```toml
# Cargo.toml of a crate on an FFI path
[lints.clippy]
unwrap_used = "deny"
expect_used = "warn"
panic = "deny"
todo = "deny"
unimplemented = "deny"
indexing_slicing = "warn"
panic_in_result_fn = "deny"
missing_panics_doc = "warn"
```

```toml
# clippy.toml at the workspace root
allow-unwrap-in-tests = true
allow-expect-in-tests = true
allow-panic-in-tests = true
```

Count the debt with a command, never from memory:

```bash
rg -n --type rust '\.unwrap\(\)|\.expect\(' \
  -g '!target/**' -g '!**/tests/**' -g '!**/benches/**' | wc -l
```

`references/unwrap-audit.md` holds the triage workflow, the replacement recipes, and the
rules for `#[allow]` with a justification comment.

## Typed errors: `thiserror` and `anyhow`

| Context | Use | Why |
|---|---|---|
| Library crate that anything on an FFI path depends on | `thiserror` | Callers match on variants. The compiler forces exhaustive handling when a variant is added. |
| Application crate, CLI, integration test, top-level orchestration | `anyhow` | One propagation type, one human-readable report at the top. |
| FFI adapter crate | `thiserror` inside, flatten at the throw or return site | The boundary flattens to a code or a string anyway. Variants matter during propagation, not at the exit. |

Derive the current split from the manifests, never from memory:

```bash
rg -n '^\s*(thiserror|anyhow)\s*=' -g '**/Cargo.toml'
```

A crate that depends on neither still needs the same review for `Result<_, String>` and for
bare unwraps on a public path.

Rules:

- A library `src/lib.rs` that exposes `anyhow::Result` in its public API is a smell. The
  caller loses every variant and must match on strings.
- `Result<_, String>` in a public signature is the same defect with fewer dependencies.
- Map the typed error to the foreign representation in exactly one place per boundary crate.
  A second mapping site drifts.
- Keep the panic exit distinct from every error exit. A panic means a bug in Rust; an error
  means an expected failure. If they share a code, you cannot triage the crash report.

## Keep data valid when a panic passes through

`catch_unwind` returns control, so whatever the closure touched is still alive. Panic safety
of data is a separate problem from panic safety of the boundary.

- **Lock poisoning.** `std::sync::Mutex` marks itself poisoned when a holder panics. Later
  `lock()` calls return `Err`. Decide once per lock: propagate the poison as a fatal error,
  or recover with `PoisonError::into_inner()` and a comment that says why the data is still
  valid. `parking_lot` locks do not poison — you get no warning, so state the invariant in
  the type.
- **Restore the invariant with a guard.** Move the "put it back" step into a `Drop`
  implementation so unwinding runs it. Set the flag, spawn the guard, do the work.
- **Never panic in `Drop`.** A panic inside a `Drop` that runs during unwinding is a double
  panic, and the runtime aborts. A `Drop` implementation must be infallible: log the failure
  and continue.
- **Force an abort where an unwind is unacceptable.** In a critical section that must not
  half-complete, arm a bomb and disarm it on success.

  ```rust
  struct AbortOnUnwind;
  impl Drop for AbortOnUnwind {
      fn drop(&mut self) {
          std::process::abort();
      }
  }

  let bomb = AbortOnUnwind;
  // ... section that must complete or kill the process ...
  std::mem::forget(bomb);
  ```

- **Do not leave a `&mut` in a torn state.** If you split a value into parts and panic in the
  middle, the caller observes the parts. Build the new value first, then commit with a single
  assignment.

## Panics in async tasks and threads

- A panic in a spawned Tokio task does not unwind through `block_on`. It surfaces at the
  join point.

  ```rust
  match handle.await {
      Ok(value) => Ok(value),
      Err(err) if err.is_panic() => {
          drop(err.into_panic());
          Err(Error::TaskPanicked)
      }
      Err(_) => Err(Error::TaskCancelled),
  }
  ```

- Wrap `block_on` itself when a foreign caller drives it. A panic in the future's own body
  does unwind through `block_on`.

  ```rust
  let result = std::panic::catch_unwind(AssertUnwindSafe(|| runtime.block_on(fut)));
  ```

- A detached task whose `JoinHandle` you drop reports nothing. Keep the handle, or wrap the
  task body in its own guard that records the panic.
- `std::thread::spawn` returns the payload from `join()` as `Box<dyn Any + Send>`. Discard the
  payload after you classify the result as a fatal internal error.
- A panic that crosses a task boundary loses its location. The panic hook is the only place
  that still has it, which is why the hook must be installed before any task starts.

See the `rust-async-internals` skill for runtime-level panic handling and cancellation.

## Failure triage

| Symptom | Likely cause | Action |
|---|---|---|
| Host process dies with `SIGABRT` and no Rust backtrace | A panic reached an unguarded `extern` function | Find the entry point in the boundary inventory; add the guard |
| `catch_unwind` never returns `Err`, process still dies | The crate builds with `panic = "abort"` | Inspect the workspace and the member manifests, and `RUSTFLAGS`; set `panic = "unwind"` |
| `catch_unwind` returns `Ok`, work silently missing | The panic happened on another thread or in a spawned task | Join the handle and inspect `JoinError` |
| `fatal runtime error: Rust cannot catch foreign exceptions` | A C++ or foreign unwind entered Rust frames | Catch it on the foreign side; never let it enter Rust |
| Abort during unwinding, second panic in the log | A `Drop` implementation panicked while a panic was in flight | Make the `Drop` infallible |
| The boundary catches a panic and then aborts | Dropping the caught payload panicked | Dispose of the payload inside a second guard and forget a second panic payload |
| `memory allocation of N bytes failed`, then abort | Allocation failure, which is not a catchable panic | Bound the size; use `Vec::try_reserve` for large or input-driven buffers |
| The bounded panic record has no message or backtrace | This is the shipped privacy contract | Reproduce on the host with `RUST_BACKTRACE=full`, or symbolicate the crash artifact offline |
| Every later call fails with a poison error | An earlier panic poisoned a shared lock | Decide the poison policy; report the original panic, not the poison |
| `#[should_panic]` test kills the test runner | `-C panic=abort` reached the test build through `RUSTFLAGS` or `-Z panic-abort-tests` | Build the tests under unwind; the manifest `panic` key alone cannot cause this |
| Panic location points into a macro or `core` | The real cause is an index, a slice range, or an overflow | Reproduce with `overflow-checks = true` and a debug build; see the `rust-debugging` skill |

## Review checklist

- [ ] Every `extern` function in the boundary inventory has a guard.
- [ ] Every `extern` body is a guard plus a delegation call, with the logic in a testable
      plain Rust function.
- [ ] The shipped profile sets `panic = "unwind"` if any guard uses `catch_unwind`.
- [ ] The panic exit path has a status code, an exception, or an error object distinct from
      every domain error.
- [ ] The panic boundary discards the raw payload and returns a distinct panic result.
- [ ] Discarding a caught payload cannot let a second panic leave the boundary.
- [ ] The panic hook is installed once and emits only a closed site code plus numeric location.
- [ ] No shipped platform log contains a panic payload, file path, or backtrace.
- [ ] Every `AssertUnwindSafe` carries a comment that names the invariant.
- [ ] Every new `.unwrap()` or `.expect()` outside tests carries an infallibility proof.
- [ ] The crate denies `clippy::unwrap_used` and `clippy::panic` on FFI paths.
- [ ] A library crate declares `thiserror` variants for its public `Result` types and does
      not return `anyhow::Result` or `Result<_, String>` publicly.
- [ ] No `Drop` implementation can panic.
- [ ] Every spawned task or thread reports its panic at a join point or through its own guard.

## References

- `references/boundary-patterns.md` — guard shapes per boundary: status codes, out-params,
  opaque handles, string transfer, callbacks into Rust, the macro-generated `extern` layer,
  and the JNI and UniFFI variants in full.
- `references/unwrap-audit.md` — the audit workflow, the replacement recipes for each
  `.unwrap()` category, lint rollout order, and the `#[allow]` justification rules.

## Related skills

- `rust-unsafe` — raw pointers, SAFETY comments, and the soundness rules around the same
  `extern` functions.
- `rust-jni` — JNI binding rules, signatures, and local reference handling.
- `uniffi-boundary` — the generated scaffolding and its type mapping.
- `ffi-error-progress-cancel` — the error object, progress, and cancellation contract across
  a binding layer.
- `rust-async-internals` — panic propagation inside a runtime and across task boundaries.
- `rust-lints` — the workspace lint floor and how to roll a new `deny` out.
- `rust-debugging` — turning an abort or a panic location into a root cause.
- `rust-test-tools` — `#[should_panic]`, fuzzing, and property tests that hunt panics.
- `rust-observability` — where the panic log line goes.
