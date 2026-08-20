---
name: ffi-error-progress-cancel
description: Use when you design or review an FFI boundary for a long-running Rust operation that must report typed errors, stream progress, and cancel cooperatively - import, indexing, preview, render, export, or any job longer than one frame. Covers a closed versioned boundary error taxonomy, UniFFI flat error enums, mapping stable error codes to native UX buckets, redaction so no backtrace or filesystem path crosses the boundary, callback-interface progress listeners carrying job id plus stage and fraction, bridges to Kotlin Flow with callbackFlow and awaitClose and to Swift AsyncThrowingStream with onTermination, and wiring coroutine cancel and Task cancel down to an idempotent non-blocking cancel_job. Triggers on flat_error, callback interface, callbackFlow, awaitClose, trySend, AsyncThrowingStream, CancellationException, CancellationError, cancel_job, job_id, progress event, or "the UI must not show stack traces".
license: BSD-3-Clause
---

# FFI error, progress, and cancellation

## Purpose

Own the end-to-end contract that crosses the FFI boundary for every
long-running operation: a stable error taxonomy, a progress event stream, and
cooperative cancellation. These three concerns are one contract. If you design
them separately, you get an error enum that cannot express "the user pressed
Cancel", a progress stream that leaks a worker thread when the consumer goes
away, and a cancel call that blocks the UI thread.

This skill covers the boundary UX. Related skills cover the parts underneath:

- `uniffi-boundary` - binding generation mechanics and UDL/proc-macro shape.
- `memory-model` - the exact atomic `Ordering` for the cancel flag and the
  progress counter.
- `rust-panic-safety` and `rust-discipline` - panic policy at the boundary.
- `rust-debugging` - panic propagation through generated bindings.
- `rust-observability` - the `tracing` subscriber that receives redacted events.
- `rust-jni` - the same three protocols over a hand-written JNI boundary.

## When to use

- You design or review an FFI method that takes measurable time: archive
  import, index build, preview generation, large or vector export, batch export,
  asset import.
- You map a core error enum to the flat boundary enum, then on to Kotlin
  exceptions and Swift `Error`.
- You bridge a Rust progress callback into a Kotlin `Flow` or a Swift
  `AsyncThrowingStream`.
- You wire coroutine cancellation or `Task` cancellation down to a Rust job
  cancel.
- You decide what the UI shows against what the diagnostic log keeps.

## Pipeline

```text
core error crate   ──>  FFI crate (UniFFI)          ──>  Kotlin engine wrapper  ──> Flow
  CoreError               EngineError (flat_error)         (callbackFlow)
  CoreErrorKind           ProgressEvent / ProgressStage
                          ProgressListener (callback)  ──>  Swift engine client  ──> AsyncThrowingStream
                          Engine::cancel_job                (AsyncThrowingStream)
```

The core crate defines the kinds. The FFI crate translates them to the wire
enum, exposes the progress listener as a UniFFI callback interface, and hosts
`cancel_job(job_id)` on the engine object.

**Rule: exactly one layer touches generated types.** The platform engine
wrapper (one Kotlin module, one Swift package) is the only code allowed to see
UniFFI-generated types. Feature modules see idiomatic `Flow` / `AsyncSequence`
and platform-native error types. A generated exception that escapes into a
feature module is a review blocker - it makes the whole app depend on the
binding generator's naming.

---

## 1. Error model

### Expose stable categories, not internal errors

Internal `anyhow` chains, `thiserror` source chains, and backtraces stay inside
the crate. The FFI surface is closed and versioned. Adding a kind is a contract
change; removing or renaming one is a breaking change.

Give every kind a stable `code()` string - `invalid_request`, `not_found`,
`out_of_memory_risk`. **The kind identity is the cross-language contract, not
the message.** On the wire that identity is the boundary enum variant name,
which the binding generator turns into a Kotlin exception subclass and a Swift
enum case. The `code()` string is the same identity in text form: use it in
logs, in telemetry, and in any table that maps a kind to a UX bucket. Messages
are free to change per release and per locale; variant names and codes are
not.

Mark the core kind enum `#[non_exhaustive]` so downstream `match` arms keep a
wildcard and a new kind does not break every consumer crate at once.

```rust
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreErrorKind {
    // caller-controlled input
    InvalidRequest,
    InvalidData,
    NotFound,
    // resource policy
    OutOfMemoryRisk,
    ResourceLimitExceeded,
    IoFailed,
    // encrypted or signed container import
    InvalidArchive,
    ArchiveAuthenticationFailed,
    // engine-side failures
    ProcessingFailed,
    OutputFailed,
    // control flow
    Cancelled,
    // invariant violation and forward-compatible fallback
    Unexpected,
}

impl CoreErrorKind {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidRequest => "invalid_request",
            Self::InvalidData => "invalid_data",
            Self::NotFound => "not_found",
            Self::OutOfMemoryRisk => "out_of_memory_risk",
            Self::ResourceLimitExceeded => "resource_limit_exceeded",
            Self::IoFailed => "io_failed",
            Self::InvalidArchive => "invalid_archive",
            Self::ArchiveAuthenticationFailed => "archive_authentication_failed",
            Self::ProcessingFailed => "processing_failed",
            Self::OutputFailed => "output_failed",
            Self::Cancelled => "cancelled",
            Self::Unexpected => "unexpected",
        }
    }
}
```

Keep the set small enough to enumerate in a review, and split kinds only when a
platform must react differently. Useful splits, with the rule that decides each:

| Kind | Use it when |
| --- | --- |
| `InvalidRequest` | Caller-controlled operation parameters, identifiers, settings, paging, or lifecycle state are wrong. |
| `InvalidData` | Imported, captured, or persisted data is malformed or internally inconsistent. |
| `NotFound` | A named resource the caller asked for does not exist. |
| `OutOfMemoryRisk` | A memory policy or allocation guard refused the workload. Recoverable by shrinking it. |
| `ResourceLimitExceeded` | A non-memory work, count, depth, or time limit was hit. Recoverable by narrowing scope. |
| `InvalidArchive` | A container failed structural validation. |
| `ArchiveAuthenticationFailed` | A container failed authentication - wrong passphrase or bad tag. Keep it distinct from `InvalidArchive`; the UX is a passphrase prompt, not a re-pick. |
| `Unexpected` | Generated engine output violates an internal invariant. Also the forward-compatible catch-all for a kind a newer engine names but this binding version does not. |

### The boundary enum is flat

The boundary error is a separate type from the core kind. Make it a **flat**
UniFFI error: each variant carries a single user-safe `String`. Because the
enum is flat, UniFFI lowers the type's `Display` across the boundary instead of
marshalling structured fields.

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

Hard constraints on the wire type:

- One variant per core kind. Keep the two enums in step with an exhaustive
  `match` in the `From` conversion, so adding a kind fails the build until the
  boundary is updated.
- **No `diagnostic` field on the wire.** Do not put `Box<dyn Error>`,
  filesystem paths verbatim, or backtraces in the message. The message is the
  only string the UI is allowed to render, so treat it as user-visible text.
- `Cancelled` is a first-class variant, not a panic and not a generic failure.
  It is the success-path outcome of cooperative cancellation.
- `EngineError` carries only the message. Correlate a failure with its job
  through the `job_id` in the request record, not through the error.

### Diagnostics stay behind a redacting sink

Detailed diagnostics belong in engine logs. If the host installs a log sink
across the boundary (`init_engine_logging` style: the host passes a listener
that receives every `tracing` event), that sink is **not** a second channel for
reading the detail you just refused to send in the error.

Enforce it by construction:

- The error constructor emits the error's *kind* as a frozen enumeration case
  and nothing else. It does not emit the message or the source chain.
- A shared redacting visitor admits only declared field names carrying enum
  cases, counts, and booleans. Everything else - free-form strings, paths,
  source chains - is dropped before it reaches the boundary.
- A host-side subscriber inside the same process may render the full message.
  The FFI sink never sees it.

Review this as a whitelist, never a blacklist. A denylist of "sensitive" field
names fails the first time somebody adds a field.

### The five native semantic buckets

Every kind must land in exactly one UX bucket on the native side. This is the
contract that stops "show the raw error string" from becoming the default.

| Bucket | Kinds | UX |
| --- | --- | --- |
| Recoverable user error | `InvalidRequest`, `OutOfMemoryRisk`, `ResourceLimitExceeded` | Inline validation, reduce the workload, fix and retry. |
| Recoverable file or data error | `InvalidData`, `NotFound`, `InvalidArchive`, `ArchiveAuthenticationFailed`, `IoFailed` | Re-pick the file, prompt for the passphrase, re-import. Explain what to do. |
| Engine bug | `ProcessingFailed`, `OutputFailed`, `Unexpected` | Generic "something went wrong" plus a log entry. Never blame the user. |
| Programmer error | An unrecognized category code; contract violations caught at the boundary. | Must never ship. Assert in debug builds. |
| Cancellation | `Cancelled` | Silent, or a short "Cancelled". Never an error dialog. |

The bucket set is stable even when the kind set grows. A new kind must be
assigned a bucket in the same change that adds it.

### Kotlin mapping

UniFFI generates a sealed exception hierarchy - the `EngineError` enum becomes
`EngineException` in Kotlin. The wrapper translates it to the app's typed error
model, and never lets a generated exception escape to feature modules.

Map on the generated exception subtype with an exhaustive `when`, plus an
`else` branch that yields `PROGRAMMER_ERROR`. A flat error carries only its
message across the boundary, so the subtype is the only thing the mapper can
match on. The `else` branch is how an older binding survives a newer engine.

Map `Cancelled` to coroutine `CancellationException` so structured concurrency
treats it correctly. Do not swallow it as a normal failure and do not wrap it in
a domain error - a wrapped `CancellationException` breaks cancellation
propagation up the coroutine tree.

### Swift mapping

UniFFI generates a Swift `enum EngineError: Error`. An actor-isolated client
maps it to the app's public error type and keeps generated FFI types internal.

Map the `Cancelled` kind to Swift's `CancellationError` on the
`AsyncThrowingStream` path, so a caller's `try Task.checkCancellation()`
semantics line up with what the stream throws.

### Hard rule - UI against diagnostics

UI error messages must not expose internal stack traces. Diagnostic logs may
include detailed engine context. Enforce this by construction rather than by
review: the boundary type has no field that could carry a trace, so there is
nothing for the UI to render by accident.

---

## 2. Progress

### Rust side - a callback interface

Long-running engine methods take a listener. Declare it as a UniFFI **callback
interface** in the `Box<dyn ...>` form, which the host implements.

```rust
#[uniffi::export(callback_interface)]
pub trait ProgressListener: Send + Sync {
    fn on_progress(&self, event: ProgressEvent);
}

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

Design rules for the event:

- **Three fields, no more.** `job_id`, `stage`, `fraction`. A progress event is
  not a place to smuggle partial results, byte counts, or file names. Every
  field you add is a field somebody will render in the UI.
- **A closed stage enum with a terminal `Done`.** Stages name phases of work,
  not internal function names. Renaming a stage is a contract change.
- `fraction` is clamped to `0.0..=1.0` and is monotonic within a stage. Do not
  send `NaN`; a stage with unknown length reports `0.0` until it can do better.
- Emit at stage transitions and at bounded intervals inside long inner loops -
  per chunk, per block, per batch. Do not emit per item when items are cheap.
- **Keep the callback cheap and non-blocking.** The foreign callback runs on the
  engine worker thread. Heavy work there stalls the job, and a blocking call
  there can deadlock against the host's own locks.

### Determinism

Progress events are **observational**, not part of the deterministic output
contract. The number and the timing of events may vary across runs, machines,
and devices. The final result bytes must not.

- Never derive output from progress state.
- Never let a slow or absent progress consumer change what gets written.
- Golden-output tests run with a no-op listener and must produce identical
  bytes to a run with a real listener.

### Kotlin - `Flow` through `callbackFlow`

```kotlin
fun export(request: ExportRequest): Flow<ExportProgress> = callbackFlow {
    engine.reserveJob(request.jobId)                 // bounded; runs before cancellation is visible
    val listener = object : ProgressListener {
        override fun onProgress(event: ProgressEvent) { trySend(event.toDomain()) }
    }
    launch(Dispatchers.Default) {                    // engine work off the main thread
        try {
            engine.export(request.toFfi(), listener)
            close()
        } catch (e: EngineException) {
            close(e.toDomain())
        }
    }
    awaitClose { engine.cancelJob(request.jobId) }   // see section 3
}
```

Use `callbackFlow`, not `flow {}`: progress is push-based, so the producer is
not a suspending loop you control. `trySend` honors backpressure without
blocking the worker thread. `awaitClose` is the cancellation hook and is
mandatory - `callbackFlow` throws if the block returns without it.

### Swift - `AsyncThrowingStream`

```swift
func export(request: ExportRequest) -> AsyncThrowingStream<ExportProgress, Error> {
    AsyncThrowingStream { continuation in
        do {
            try ffi.reserveJob(jobId: request.jobId)
        } catch {
            continuation.finish(throwing: map(error))
            return
        }
        let listener = ProgressListenerImpl { continuation.yield($0.toDomain()) }
        let task = Task.detached {
            do {
                _ = try ffi.export(request: request.toFfi(), listener: listener)
                continuation.finish()
            } catch {
                continuation.finish(throwing: map(error))
            }
        }
        continuation.onTermination = { _ in
            ffi.cancelJob(jobId: request.jobId)
            task.cancel()
        }
    }
}
```

`onTermination` fires on normal finish and on consumer cancellation. It is the
single place that calls `cancelJob`, so there is exactly one cancel path to
test.

Deeper bridge material - buffering policy, multiple consumers, listener
lifetime, and the test matrix - is in
[`references/platform-bridges.md`](references/platform-bridges.md).

---

## 3. Cancellation

Cancellation is **cooperative**. Check it between expensive stages and inside
inner loops.

### Rust side

- A shared `AtomicBool` cancel flag per job lives behind the `job_id`. The
  engine checks it at every stage boundary and inside per-chunk loops, then
  returns the `Cancelled` error promptly. Store with `Release` and load with
  `Acquire`, or use `Relaxed` with a written rationale. See `memory-model` for
  the exact `Ordering` on that flag and on the progress counter. Do not
  re-derive it here.
- `cancel_job(job_id)` is **idempotent and non-blocking**. It sets the flag and
  returns. It does not join the worker and it does not wait for the job to
  notice. Cancelling an unknown or already-finished job is a no-op success, not
  an error.
- Support **pre-cancel** through an explicit bounded reservation. Reserve the
  caller-supplied `job_id` synchronously before you expose cancellation or
  launch the worker. A cancel between reservation and worker start sets that
  reserved flag. A cancel for an unreserved id stays a no-op and must not add a
  map entry. Reject empty or oversized ids, duplicate ids, and reservations
  above the active-job limit. Release the reservation if launch fails. Reap
  reservations that do not start within a short TTL; never expire running jobs.
- Never cancel by panicking and never by killing the thread. A panic that
  unwinds out of an `extern "C"` function aborts the process, and a killed
  thread leaks every lock it held. Catch the panic at the boundary and convert
  it; see `rust-panic-safety`.
- **Clean up partial output on the `Cancelled` path.** The worker deletes or
  discards the half-written file itself. Do not leave a truncated export on
  disk for the host to find. Write to a temporary path and rename on success, so
  the cancel path only has to delete the temporary.

### Kotlin

Coroutine cancellation must reach Rust. When the collecting coroutine is
cancelled, `awaitClose { engine.cancelJob(jobId) }` runs and sets the Rust flag.
Map the resulting Rust `Cancelled` to `CancellationException` so it propagates
cleanly instead of surfacing as a user-facing failure.

### Swift

`Task` cancellation must reach Rust. When the consuming `Task` is cancelled the
stream terminates and `continuation.onTermination` calls `cancelJob`. Keep the
client's FFI work off the main actor - an actor-isolated client with
`Task.detached` for the blocking engine call.

### Gotchas

- **The `job_id` is caller-supplied.** Every long-running request record carries
  a caller-chosen id, so the termination handler always has something to cancel
  even if the call has not returned a handle yet. Use a fresh id per invocation;
  a reused id makes a late cancel kill the next job.
- **Cancellation is not failure.** Do not log it at error level, do not show an
  error dialog, do not retry automatically, do not count it in a failure metric.
- **Latency budget.** A cancel must be observed within one stage or a bounded
  number of inner iterations. If one stage is long, add interior checkpoints.
  Write the budget down and test against it.
- **No leaked workers.** If the consumer drops the stream without an explicit
  cancel, the termination handler still fires `cancelJob`. Verify both the Flow
  path and the stream path in tests, including the drop-without-cancel case.
- **Cancel after completion.** A cancel that arrives after the job finished must
  not resurrect state or delete the finished output.

---

## Review checklist

- [ ] The boundary error enum is flat, closed, and versioned. No `anyhow`
      chain, backtrace, or verbatim path crosses the boundary.
- [ ] Every core kind maps to exactly one boundary variant, through an
      exhaustive `match` that fails the build when a kind is added.
- [ ] Every kind is assigned one of the five native buckets. `Unexpected` is the
      forward-compatible fallback and `Cancelled` is first class.
- [ ] Platform mappers key off the generated variant or the stable `code()`
      string, never the message, and have an `else` branch that yields a
      programmer-error bucket.
- [ ] The UI renders only the user-safe message. Detailed diagnostics stay in
      engine logs, behind a whitelist-based redacting visitor.
- [ ] No generated FFI type escapes the single platform wrapper layer.
- [ ] Progress is `callbackFlow` on Kotlin and `AsyncThrowingStream` on Swift.
      Listener callbacks are cheap and non-blocking.
- [ ] The progress event carries `job_id`, `stage`, and `fraction` and nothing
      else. The stage enum is closed and has a terminal `Done`.
- [ ] Progress is observational only. Golden output is byte-identical with and
      without a listener.
- [ ] `reserve_job` limits id bytes and entry count and rejects duplicate ids.
      Launch failure releases its reservation, and a TTL reaps abandoned
      reservations. `cancel_job` never inserts unknown ids and supports cancel
      after reservation but before worker start.
- [ ] Coroutine cancel and `Task` cancel both reach `cancel_job` through
      `awaitClose` and `onTermination`. `Cancelled` maps to
      `CancellationException` and `CancellationError`.
- [ ] Cancellation is observed within a written-down stage or iteration budget.

## Canonical sources

- UniFFI errors, flat against structured enums, `#[uniffi(flat_error)]`:
  https://mozilla.github.io/uniffi-rs/latest/types/errors.html
- UniFFI callback interfaces and foreign traits:
  https://mozilla.github.io/uniffi-rs/latest/types/callback_interfaces.html
- UniFFI async and futures, for the async export path and foreign executors:
  https://mozilla.github.io/uniffi-rs/next/futures.html
- Kotlin `Flow`, `callbackFlow`, `awaitClose`, structured cancellation:
  https://kotlinlang.org/docs/flow.html
- Swift `AsyncThrowingStream`, continuation and `onTermination`:
  https://developer.apple.com/documentation/swift/asyncthrowingstream
- Swift structured cancellation: `Task.isCancelled`, `checkCancellation()`,
  `withTaskCancellationHandler`.
