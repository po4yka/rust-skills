# Hosts, hooks, and tasks

Detail for `SKILL.md` beyond the hand-rolled C guard: JNI and UniFFI entry points, the panic
report, data that a caught panic leaves behind, and panics in tasks and threads.

Contents:

- JNI and UniFFI boundaries
- Report the panic without exposing its payload
- Keep data valid when a panic passes through
- Panics in async tasks and threads

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
