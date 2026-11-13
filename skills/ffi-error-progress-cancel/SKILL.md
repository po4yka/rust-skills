---
name: ffi-error-progress-cancel
description: Use when designing typed errors, progress streaming, or cooperative cancellation for a long-running Rust FFI or UniFFI call in Kotlin or Swift, or tying such a call to a mobile UI owner through Activity lifecycle, ViewModel.onCleared, Dispatchers.Main, background deadlines, process death, or a callback release race. Triggers on flat_error, callbackFlow, awaitClose, trySend, AsyncThrowingStream, onTermination, CancellationException, CancellationError, cancel_job, job_id, or progress events.
license: BSD-3-Clause
---

# FFI error, progress, and cancellation

The error taxonomy, the progress stream, and cooperative cancellation of a
long-running operation are one contract. Design them together.

## Pipeline

The core crate defines the error kinds. The FFI crate maps them to the flat
boundary enum, exposes the progress listener as a foreign trait, and hosts
`reserve_job(job_id)` and `cancel_job(job_id)` on the engine object. The worker
guard releases a reservation on every exit path; the host never does.
[`references/platform-bridges.md`](references/platform-bridges.md) has the diagram.

**Exactly one layer touches generated types:** the platform engine wrapper (one
Kotlin module, one Swift package). Feature modules see `Flow` / `AsyncSequence`
and native error types; a generated exception that reaches one is a review
blocker.

## Gotchas

A green Rust test suite shows none of these defects.

- **Render only the mapped app error.** The UI never renders a generated error
  object, a Swift `localizedDescription`, or a panic message. The boundary
  message is the one engine string that can reach the UI: keep
  `Box<dyn Error>`, verbatim paths, and backtraces out of it.
- **Map `Cancelled` to platform cancellation:** Kotlin `CancellationException`,
  Swift `CancellationError`. A `CancellationException` wrapped in a domain error
  stops propagation up the coroutine tree. Cancellation is not failure: no
  error log, dialog, retry, or failure metric.
- **Mappers have no `else` or `default` arm**, so a regenerated binding with a
  new variant fails the build. Send every error that is not a generated boundary
  error, such as a Rust panic or version skew, to the engine-bug bucket.
- **`cancel_job` never panics:** a panic in a non-throwing Swift call is an
  uncatchable fatal error. Recover registry lock poison there, and in the worker
  guard's `Drop`, with `lock().unwrap_or_else(PoisonError::into_inner)`. Map
  poison to a typed error on throwing paths such as `reserve_job`.
- **One cancel path per bridge.** Only `awaitClose` (Kotlin) and
  `onTermination` (Swift) call `cancelJob`, so a dropped stream still stops the
  worker.
- **A fresh caller-supplied `job_id` per invocation:** a reused id lets a late
  cancel kill the next job.
- **A cancel after completion is a no-op** that keeps the finished output.
- **Progress never changes output.** A slow or absent progress consumer must not
  change what gets written.
- **Never cancel by panicking or by killing a thread.** A panic that reaches an
  `extern "C"` boundary aborts the process (Rust 1.81+), and a killed thread
  leaks every lock it held. The `rust-panic-safety` skill owns the panic policy;
  without it, wrap each export body in `std::panic::catch_unwind` and keep
  `panic = "unwind"`.
- **Teardown never blocks.** It only signals cancel and callback release, and
  never joins a worker in `onCleared`, `deinit`, or on the main thread.

## Verification

Run the check that proves the claim you changed. A green Rust suite compiles
neither wrapper.

| Claim | Check |
| --- | --- |
| Pre-cancel, unknown-id no-op, bounded reservations, poison recovery | Rust unit tests on the registry, for example `cargo test -p <ffi-crate> registry`, including a poisoned lock. |
| Kind parity | A contract test: each `code()` has one boundary variant and one bucket. |
| Determinism | A golden test: identical output bytes with a no-op and a recording listener. |
| Cancel latency and cleanup | A stress-looped test that cancels mid-stage, expects `Cancelled` within the budget, and finds no partial output. |
| Kotlin bridge | A `kotlinx-coroutines-test` `runTest` that cancels the Flow and asserts one `cancelJob` call and no live worker, plus the drop-without-cancel case. |
| Swift bridge | A test that cancels the consuming `Task`, plus one that drops the stream, built in Swift 6 mode with the app target's default isolation. |

Run device or emulator lanes when the change touches threading or lifecycle
teardown; without a device, report that lane as not run, not as passed. Read
[`references/review-checklist.md`](references/review-checklist.md) when you
review a boundary change.

## 1. Error model

### Stable kinds

Internal `anyhow` chains, `thiserror` source chains, and backtraces stay inside
the crate. The FFI surface is a closed, versioned set of kinds: adding a kind is
a contract change, and removing or renaming one is breaking. Give every kind a
stable `code()` string, such as `invalid_request`, and mark the core kind enum
`#[non_exhaustive]`. **The kind identity is the cross-language contract, not the
message:** on the wire it is the boundary variant name, which becomes a Kotlin
exception subclass and a Swift enum case.

Read [`references/error-taxonomy.md`](references/error-taxonomy.md) when you
change a kind or wire a host log sink (allowlisted fields only, never a message).

### The boundary enum is flat

The boundary error is a separate type from the core kind: a **flat** UniFFI error,
which exposes only the variant names and sends the `Display` text as the single
field of each variant.

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

- One variant per core kind, kept in step by an exhaustive `match` in the same
  crate. A downstream crate cannot match a `#[non_exhaustive]` enum
  exhaustively: map the wildcard to `Unexpected` and add a contract test that
  compares the stable codes with the boundary variants.
- **No `diagnostic` field on the wire**, so no field can carry a trace to the UI.
- `Cancelled` is a first-class variant, the expected outcome of cooperative
  cancellation.
- Correlate a failure with its job through the `job_id` of the request, not
  through the error.

### The five native semantic buckets

Every kind lands in exactly one UX bucket on the native side.

| Bucket | Kinds | UX |
| --- | --- | --- |
| Recoverable user error | `InvalidRequest`, `OutOfMemoryRisk`, `ResourceLimitExceeded` | Inline validation, smaller workload, retry. |
| Recoverable file or data error | `InvalidData`, `NotFound`, `InvalidArchive`, `ArchiveAuthenticationFailed`, `IoFailed` | Re-pick the file, prompt for the passphrase. |
| Engine bug | `ProcessingFailed`, `OutputFailed`, `Unexpected`, a Rust panic, version skew | Generic "something went wrong" plus a log entry. Never blame the user. |
| Programmer error | A contract violation the wrapper detects, such as an event for another `job_id` | Assert in debug builds. |
| Cancellation | `Cancelled` | Silent, or a short "Cancelled". |

Assign a bucket to a new kind in the same change.

End every Kotlin wrapper `try` with a `catch (e: Exception)` that maps to the
engine-bug bucket; around a `suspend` call, rethrow `CancellationException`
first. Read the "Error translation" sections of
[`references/platform-bridges.md`](references/platform-bridges.md) when you
write a mapper.

## 2. Progress

### Rust side

Long-running engine methods take an `Arc<dyn ProgressListener>`, a foreign
trait with
`fn on_progress(&self, event: ProgressEvent) -> Result<(), ProgressCallbackError>`
(the `uniffi-boundary` skill holds the full declaration). On a listener failure,
convert `ProgressCallbackError` to `EngineError::Unexpected`, stop the job with
`?`, and let the worker remove its temporary output. Keep any existing final
output unchanged. This skill owns the event contract:

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

- **Three fields, no more:** no partial results, byte counts, or file names.
- **A closed stage enum with a terminal `Done`.** Stages name phases of work,
  not functions. Renaming a stage is a contract change.
- Clamp `fraction` to `0.0..=1.0`, monotonic within a stage, never `NaN`.
- Emit at stage transitions and bounded intervals, not per cheap item.
- **Keep the callback cheap and non-blocking.** It runs on the engine worker
  thread, and a blocking call there can deadlock against the host's locks.

### Platform bridges

Read [`references/platform-bridges.md`](references/platform-bridges.md) when you write or review the Kotlin or Swift wrapper. Kotlin uses
`callbackFlow` with `buffer(Channel.CONFLATED)` and ends with
`awaitClose { engine.cancelJob(jobId) }`; Swift passes
`bufferingPolicy: .bufferingNewest(1)` and runs the blocking engine call on a
dedicated `Thread`. Both reserve the job before the worker starts, and neither
runs an engine call on the main thread.

## 3. Cancellation

Cancellation is **cooperative**.

- One `AtomicBool` cancel flag per job lives behind the `job_id`. The engine
  checks it at every stage boundary and inside per-chunk loops, then returns
  `Cancelled` promptly. Store it with `Release` and load it with `Acquire`; use
  `Relaxed` only with a comment that the flag publishes no other data.
- `cancel_job(job_id)` is **idempotent and non-blocking**: it sets the flag and
  returns, never joins the worker. Cancelling an unknown or finished job is a
  no-op success.
- Support **pre-cancel** through a bounded reservation of the caller-supplied
  `job_id`, made before you expose cancellation or launch the worker. A cancel
  for an unreserved id adds no map entry. Reject empty, oversized, and duplicate
  ids, and reservations above the active-job limit. Reap a reservation that does
  not start within a short TTL; never expire a running job.
- **Latency budget.** Observe a cancel within one stage or a bounded number of
  iterations; write the budget down.
- **Clean up partial output on the `Cancelled` path:** write to a temporary path
  and rename on success, so the cancel path only deletes the temporary.
- Keep `cancel_job` for a UniFFI `async fn` export too: platform cancellation
  never reaches Rust as a cooperative cancel.

Read [`references/platform-bridges.md`](references/platform-bridges.md)
(section 1) when you implement the job registry, the checkpoint helper, or an
`async fn` export: it holds a runnable registry model.

## 4. Mobile lifecycle

A screen owner consumes process-scoped Rust work; it never owns a Rust thread or
runtime. Use no Rust runtime or one process-scoped runtime, deliver UI state on
`Dispatchers.Main` or `@MainActor`, make restart initialization idempotent, and
write a callback release-race policy. Read
[`references/mobile-lifecycle.md`](references/mobile-lifecycle.md) when a job or
callback follows an Android or iOS owner lifecycle.
