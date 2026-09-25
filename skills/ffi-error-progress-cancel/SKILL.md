---
name: ffi-error-progress-cancel
description: Use when designing or reviewing typed errors, progress streaming, or cooperative cancellation for a long-running Rust FFI or UniFFI call in Kotlin or Swift, or tying such a call to a mobile UI owner through Activity lifecycle, ViewModel.onCleared, Dispatchers.Main, background deadlines, process death, or a callback release race. Triggers on flat_error, callbackFlow, awaitClose, trySend, AsyncThrowingStream, onTermination, CancellationException, CancellationError, cancel_job, job_id, progress events, or engine error text or stack traces that reach the UI.
license: BSD-3-Clause
---

# FFI error, progress, and cancellation

The error taxonomy, the progress stream, and cooperative cancellation of a
long-running operation are one contract. Design them together. Separate designs
give an error enum that cannot say "the user pressed Cancel", a progress stream
that leaks a worker when the consumer goes away, and a cancel call that blocks
the UI thread.

Related skills, when they are installed:

- `uniffi-boundary`: binding mechanics, derives, and the full `ProgressListener`
  foreign-trait declaration.
- `memory-model`: the reasoning behind the cancel-flag `Ordering`.
- `rust-panic-safety`: the panic policy at a C ABI boundary.
- `rust-jni` and `rust-swift-ffi`: the raw binding mechanics (thread
  attachment, callbacks, handle and context lifetime). Apply this skill's error,
  progress, and cancel protocol on top of them.
- `rust-observability`: the `tracing` subscriber that receives redacted events.

## Pipeline

```text
core error crate  ──>  FFI crate (UniFFI)                ──>  Kotlin engine wrapper  ──> Flow
  CoreError              EngineError (flat_error)              (callbackFlow)
  CoreErrorKind          ProgressEvent / ProgressStage
                         ProgressListener (foreign trait)  ──>  Swift engine client    ──> AsyncThrowingStream
                         Engine::reserve_job / cancel_job       (actor, Task.detached)
```

The core crate defines the kinds. The FFI crate translates them to the wire
enum, exposes the progress listener as a foreign trait
(`#[uniffi::export(foreign)]`), and hosts `reserve_job(job_id)` and
`cancel_job(job_id)` on the engine object. The host never releases a
reservation. The worker guard releases it on every exit path, and a short TTL
reaps a reservation whose engine call never starts, for example a Kotlin
`launch` that is cancelled before its body runs.

**Exactly one layer touches generated types.** The platform engine wrapper (one
Kotlin module, one Swift package) is the only code that sees UniFFI-generated
types. Feature modules see idiomatic `Flow` / `AsyncSequence` and
platform-native error types. A generated exception that escapes into a feature
module is a review blocker, because the whole app then depends on the binding
generator's naming.

## Gotchas

Each item prevents a defect that a green Rust test suite does not show.

- **Render only the mapped app error.** The UI never renders a generated error
  object, a Swift `localizedDescription` (the debug form with module, type, and
  case names), or a panic message. The boundary message is the one engine
  string that can reach the UI, through the mapped error. Treat it as
  user-visible text, and keep `Box<dyn Error>`, verbatim paths, and backtraces
  out of it.
- **Map `Cancelled` to platform cancellation.** Kotlin gets
  `CancellationException` and Swift gets `CancellationError`. A
  `CancellationException` wrapped in a domain error stops cancellation
  propagation up the coroutine tree. Cancellation is not failure: no error-level
  log, no error dialog, no automatic retry, no failure metric.
- **Mappers have no `else` or `default` arm.** Match the generated subtype or
  case exhaustively, so a regenerated binding with a new variant fails the build.
  Send every error that is not a generated boundary error to the engine-bug
  bucket: a Rust panic (Kotlin `InternalException`, a private Swift error type)
  and binding and library version skew (the generated reader rejects an unknown
  variant before any mapper runs).
- **`cancel_job` never panics.** It is a non-throwing export, and UniFFI turns a
  panic inside a non-throwing Swift call into a fatal error that Swift cannot
  catch. Recover registry lock poison there with
  `lock().unwrap_or_else(PoisonError::into_inner)`; a `lock().expect(...)`
  crashes the app. The registry release in the worker guard's `Drop` follows the
  same rule. Map poison to a typed error on throwing paths such as `reserve_job`.
- **One cancel path per bridge.** Only `awaitClose` (Kotlin) and
  `onTermination` (Swift) call `cancelJob`. A consumer that drops the stream
  without an explicit cancel then still stops the worker.
- **A fresh caller-supplied `job_id` per invocation.** The termination hook can
  cancel before the call returns a handle. A reused id makes a late cancel kill
  the next job.
- **A cancel after completion is a no-op.** It must not resurrect state or
  delete the finished output.
- **Progress never changes output.** Never derive output from progress state.
  Never let a slow or absent progress consumer change what gets written.
- **Never cancel by panicking or by killing a thread.** Since Rust 1.81 a panic
  that reaches an `extern "C"` boundary aborts the process, and a killed thread
  leaks every lock it held. The `rust-panic-safety` skill owns the panic policy.
- **Teardown never blocks.** Mobile teardown only signals cancel and callback
  release. It never joins a worker in `onCleared`, `deinit`, or on the main
  thread (section 4).

## Verification

Run the check that proves the claim you changed. A green Rust test suite does
not prove anything about the Kotlin or Swift wrapper, because it compiles
neither.

| Claim | Check |
| --- | --- |
| Pre-cancel, unknown-id no-op, bounded reservations, poison recovery | Rust unit tests on the registry type, for example `cargo test -p <ffi-crate> registry`. Include a test that poisons the lock, then calls cancel and release. |
| Kind parity | A contract test that every declared `code()` has one boundary variant and one bucket. |
| Determinism | A golden test: output bytes are identical with a no-op listener and a recording listener. |
| Cancel latency and cleanup | A test that cancels mid-stage, expects `Cancelled` within the written budget, and finds no partial output. Run it in a stress loop. |
| Kotlin bridge | A `kotlinx-coroutines-test` `runTest` that collects, then cancels the Flow, and asserts one `cancelJob` call and no live worker. Add the drop-without-cancel case. |
| Swift bridge | An XCTest or Swift Testing case that cancels the consuming `Task`, plus one that drops the stream. Build the wrapper in Swift 6 language mode, with the same default isolation as the app target that compiles it. |

Run device or emulator lanes when the change touches threading or lifecycle
teardown; a JVM host test does not exercise the platform UI executor. When no device or
emulator is available, report that lane as not run, not as passed.

The change is complete when every row that matches a changed claim passes. Read
[`references/review-checklist.md`](references/review-checklist.md) when you
review a boundary change, and close every item that applies to it.

---

## 1. Error model

### Stable kinds

Internal `anyhow` chains, `thiserror` source chains, and backtraces stay inside
the crate. The FFI surface is a closed, versioned set of kinds. Adding a kind is
a contract change; removing or renaming one is a breaking change.

Give every kind a stable `code()` string, such as `invalid_request`. **The kind
identity is the cross-language contract, not the message.** On the wire that
identity is the boundary enum variant name, which becomes a Kotlin exception
subclass and a Swift enum case. The `code()` string is the same identity in
text form for logs, telemetry, and the kind-to-bucket table. Mark the core kind
enum `#[non_exhaustive]`.

Read [`references/error-taxonomy.md`](references/error-taxonomy.md) when you
add, split, rename, or remove a kind, or wire a host log sink across the
boundary. It holds the `CoreErrorKind` enum with its `code()` table, the rule
for each split, and the redacting-sink contract. The sink admits only
allowlisted fields (enum cases, counts, booleans), never a message or a source
chain.

### The boundary enum is flat

The boundary error is a separate type from the core kind. Make it a **flat**
UniFFI error: UniFFI exposes only the variant names and sends the error's
`ToString` (its `Display`) text as the single field of each variant.

```rust
#[derive(Debug, thiserror::Error, uniffi::Error)]
#[uniffi(flat_error)]
pub enum EngineError {
    #[error("{0}")] InvalidRequest(String),
    #[error("{0}")] InvalidData(String),
    #[error("{0}")] NotFound(String),
    #[error("{0}")] OutOfMemoryRisk(String),
    #[error("{0}")] ResourceLimitExceeded(String),
    #[error("{0}")] IoFailed(String),
    #[error("{0}")] InvalidArchive(String),
    #[error("{0}")] ArchiveAuthenticationFailed(String),
    #[error("{0}")] ProcessingFailed(String),
    #[error("{0}")] OutputFailed(String),
    #[error("{0}")] Cancelled(String),
    #[error("{0}")] Unexpected(String),
}
```

- One variant per core kind. If the core and boundary enums live in the same
  crate, keep them in step with an exhaustive `match` so adding a kind fails the
  build. A downstream crate cannot exhaustively match a `#[non_exhaustive]`
  enum. It must map the wildcard to `Unexpected` and use a contract test that
  compares the declared stable codes with the boundary variants.
- **No `diagnostic` field on the wire.** The boundary type then has no field
  that can carry a trace to the UI by accident.
- `Cancelled` is a first-class variant, not a panic and not a generic failure.
  It is the expected outcome of cooperative cancellation.
- `EngineError` carries only the message. Correlate a failure with its job
  through the `job_id` in the request record, not through the error.

### The five native semantic buckets

Every kind lands in exactly one UX bucket on the native side. This contract
stops "show the raw error string" from becoming the default.

| Bucket | Kinds | UX |
| --- | --- | --- |
| Recoverable user error | `InvalidRequest`, `OutOfMemoryRisk`, `ResourceLimitExceeded` | Inline validation, reduce the workload, fix and retry. |
| Recoverable file or data error | `InvalidData`, `NotFound`, `InvalidArchive`, `ArchiveAuthenticationFailed`, `IoFailed` | Re-pick the file, prompt for the passphrase, re-import. Explain what to do. |
| Engine bug | `ProcessingFailed`, `OutputFailed`, `Unexpected`, a Rust panic, binding and library version skew | Generic "something went wrong" plus a log entry. Never blame the user. |
| Programmer error | A contract violation that the wrapper detects, such as a progress event for another `job_id`. | Must never ship. Assert in debug builds. |
| Cancellation | `Cancelled` | Silent, or a short "Cancelled". Never an error dialog. |

The bucket set stays stable when the kind set grows. Assign a bucket to a new
kind in the same change that adds it.

UniFFI turns `EngineError` into a sealed Kotlin `EngineException` hierarchy and
a Swift `enum EngineError: Error` with one `case InvalidRequest(message: String)`
per variant. End every Kotlin wrapper `try` with a `catch (e: Exception)` that
maps to the engine-bug bucket. Read
[`references/platform-bridges.md`](references/platform-bridges.md) ("Error
translation") when you write a mapper. It holds both mappers and explains why
`omit_localized_error_conformance` does not make `localizedDescription` safe.

---

## 2. Progress

### Rust side

Long-running engine methods take an `Arc<dyn ProgressListener>`. Declare it as
a foreign trait with
`fn on_progress(&self, event: ProgressEvent) -> Result<(), ProgressCallbackError>`,
because a Kotlin or Swift implementation can throw. The `uniffi-boundary` skill
holds the full declaration and the `UnexpectedUniFFICallbackError` conversion.

This skill owns the listener-failure policy. The default: convert
`ProgressCallbackError` to `EngineError::Unexpected` (engine-bug bucket), stop
the job with `?` at the call, and let the worker take its normal failure path,
which deletes the partial output. The bridges never throw, because `trySend`
and `yield` do not throw. A throw is a host bug, not a slow consumer. The output
is then absent, never different, so the determinism rules hold.

This skill also owns the event contract:

```rust
#[derive(uniffi::Enum, Clone, Copy, PartialEq, Eq)]
pub enum ProgressStage {
    Validating,
    Loading,
    Decoding,
    Processing,
    Building,
    Rendering,
    Encoding,
    Writing,
    Done,
}

#[derive(uniffi::Record, Clone)]
pub struct ProgressEvent {
    pub job_id: String,
    pub stage: ProgressStage,
    pub fraction: f64, // 0.0..=1.0
}
```

- **Three fields, no more.** `job_id`, `stage`, `fraction`. A progress event is
  not a place for partial results, byte counts, or file names. Every field you
  add is a field somebody renders in the UI.
- **A closed stage enum with a terminal `Done`.** Stages name phases of work,
  not internal function names. Renaming a stage is a contract change.
- Clamp `fraction` to `0.0..=1.0` and keep it monotonic within a stage. Do not
  send `NaN`; a stage with unknown length reports `0.0` until it can do better.
- Emit at stage transitions and at bounded intervals inside long inner loops
  (per chunk, per block, per batch). Do not emit per item when items are cheap.
- **Keep the callback cheap and non-blocking.** The foreign callback runs on the
  engine worker thread. Heavy work there stalls the job, and a blocking call
  there can deadlock against the host's own locks.
- Progress events are **observational**. Their number and timing can vary
  across runs, machines, and devices; the final result bytes must not.

### Platform bridges

Read [`references/platform-bridges.md`](references/platform-bridges.md) when you
write or review the Kotlin or Swift wrapper. It holds the complete
`callbackFlow` and `AsyncThrowingStream` bridges, the error mappers, the Swift
isolation rules, listener lifetime, and the test matrix. Each bridge keeps these
rules:

- Kotlin: use `callbackFlow`, not `flow {}`, because the engine pushes events
  from its own worker thread. Fuse it with `buffer(Channel.CONFLATED)`, so
  `trySend` replaces an older pending event and never blocks the worker. Without
  conflation, a full buffer rejects the current event and keeps stale progress.
- Kotlin: end the block with `awaitClose { engine.cancelJob(jobId) }`.
  `callbackFlow` throws `IllegalStateException` if the block returns while the
  channel is still open.
- Kotlin: call `reserveJob` synchronously in the `callbackFlow` block, before
  `launch` and before `awaitClose`, so a pre-cancel finds the reservation. Run
  the engine call on `Dispatchers.Default` or `Dispatchers.IO`, never on
  `Dispatchers.Main`, because engine calls block.
- Swift: pass `bufferingPolicy: .bufferingNewest(1)`. The default policy is
  `.unbounded`, so a slow consumer grows memory without limit.
- Swift: call `reserveJob` in the build closure, then assign `onTermination`
  before the task starts. The stream calls the handler once, on the first of
  `finish()`, `finish(throwing:)`, consumer cancellation, or deallocation. A
  handler assigned after the stream already finished runs only when the storage
  deallocates, and with `.cancelled` (Swift 6.4 probe; `AsyncStreamBuffer.swift`
  storage `deinit`). The handler can run during task cancellation, so it must
  not block.
- Swift: run the blocking call in `Task.detached`, not in a `nonisolated async`
  helper. Under Swift 6.2 approachable concurrency, such a helper runs on the
  caller's actor, which can be the main actor. In a module with MainActor default
  isolation, mark every helper that the closures call (`toDomain`, `toFfi`, and
  the error `map`) `nonisolated`; otherwise the bridge does not compile.
- Swift: make `ProgressListenerImpl` a `final class` that holds a `@Sendable`
  closure, and keep captured values such as `ExportRequest` `Sendable`. Rust
  calls the listener on its own worker thread.

---

## 3. Cancellation

Cancellation is **cooperative**. Check it between expensive stages and inside
inner loops.

- A shared `AtomicBool` cancel flag per job lives behind the `job_id`. The
  engine checks it at every stage boundary and inside per-chunk loops, then
  returns the `Cancelled` error promptly. Store it with `Release` and load it
  with `Acquire`. Use `Relaxed` only with a comment that states the flag
  publishes no other data; the `memory-model` skill owns that reasoning.
- `cancel_job(job_id)` is **idempotent and non-blocking**. It sets the flag and
  returns. It does not join the worker and it does not wait for the job to
  notice. Cancelling an unknown or already-finished job is a no-op success, not
  an error.
- Support **pre-cancel** through an explicit bounded reservation. Reserve the
  caller-supplied `job_id` synchronously before you expose cancellation or
  launch the worker. A cancel between reservation and worker start sets that
  reserved flag. A cancel for an unreserved id stays a no-op and must not add a
  map entry. Reject empty or oversized ids, duplicate ids, and reservations
  above the active-job limit. When Rust launches the worker, release the
  reservation if the launch fails (the `LaunchReservation` guard). A
  host-launched call that never starts waits for the TTL. Reap reservations
  that do not start within a short TTL; never expire running jobs.
- **Latency budget.** A cancel must be observed within one stage or a bounded
  number of inner iterations. If one stage is long, add interior checkpoints.
  Write the budget down and test against it.
- **Clean up partial output on the `Cancelled` path.** The worker deletes or
  discards the half-written file itself. Write to a temporary path and rename on
  success, so the cancel path only has to delete the temporary.
- Keep `cancel_job` for a UniFFI `async fn` export too, because Kotlin and Swift
  cancellation never reaches Rust as a cooperative cancel.

Read [`references/platform-bridges.md`](references/platform-bridges.md)
(section 1) when you implement the job registry, the checkpoint helper, or an
`async fn` export. It holds a runnable registry model with the TTL, the launch
guard, and poison recovery.

---

## 4. Mobile lifecycle

Treat a screen owner as a consumer of process-scoped Rust work, not as the
owner of a Rust thread or runtime.

Read [`references/mobile-lifecycle.md`](references/mobile-lifecycle.md) when a
job or callback follows an Android or iOS owner lifecycle. Choose no Rust
runtime or one process-scoped runtime. Keep teardown non-blocking, deliver UI
state on `Dispatchers.Main` or `@MainActor`, make restart initialization
idempotent, and write a callback release-race policy. The reference contains
the complete contract, the required lifecycle tests, and a failure triage table.
