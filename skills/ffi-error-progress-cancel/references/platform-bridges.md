# Platform bridges - deep reference

Companion to `SKILL.md`. This file holds the parts of the Kotlin and Swift
bridges that do not fit in the main flow: listener lifetime, buffering, multiple
consumers, error translation shape, and the test matrix that proves the three
protocols work together.

Terminology is the same as in `SKILL.md`:

- `CoreErrorKind` - the core crate's stable category enum.
- `EngineError` - the flat UniFFI boundary error.
- `ProgressListener` / `ProgressEvent` / `ProgressStage` - the progress
  callback interface and its payload.
- `cancel_job(job_id)` - the idempotent, non-blocking cancel entry point.

---

## 1. Rust side

### Job registry

Cancellation needs somewhere to put the flag before the worker starts. Reserve
the caller-supplied `job_id` synchronously before the host can cancel it. Bound
the reservation count so abandoned or hostile ids cannot grow the map without
limit.

```rust
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

#[derive(Default)]
pub struct JobRegistry {
    flags: Mutex<HashMap<String, Arc<AtomicBool>>>,
}

impl JobRegistry {
    /// Called before the worker is launched and before cancellation is visible.
    pub fn reserve(&self, job_id: &str) -> Result<(), &'static str> {
        let mut flags = self.flags.lock().expect("job registry poisoned");
        if flags.contains_key(job_id) {
            return Err("duplicate job id");
        }
        const MAX_ACTIVE_JOBS: usize = 64;
        if flags.len() >= MAX_ACTIVE_JOBS {
            return Err("too many active jobs");
        }
        flags.insert(job_id.to_owned(), Arc::new(AtomicBool::new(false)));
        Ok(())
    }

    /// Called by the worker when it starts. Picks up a cancel after reserve.
    pub fn register(&self, job_id: &str) -> Option<Arc<AtomicBool>> {
        let flags = self.flags.lock().expect("job registry poisoned");
        flags.get(job_id).cloned()
    }

    /// Idempotent, non-blocking. Unknown or finished id is a no-op success.
    pub fn cancel(&self, job_id: &str) {
        let flags = self.flags.lock().expect("job registry poisoned");
        // Release pairs with the Acquire load in the worker's poll, so every
        // write made before cancel is visible once the worker observes the flag.
        // See the memory-model skill.
        if let Some(flag) = flags.get(job_id) {
            flag.store(true, Ordering::Release);
        }
    }

    /// Called by the worker on every exit path, including the cancel path.
    pub fn finish(&self, job_id: &str) {
        let mut flags = self.flags.lock().expect("job registry poisoned");
        flags.remove(job_id);
    }
}
```

Points that matter:

- `reserve` runs before the worker is launched. A later `cancel` sets the
  reserved flag, and `register` picks it up when the worker starts.
- `cancel` uses `get`, not `entry`. An unknown or finished id never allocates.
- The active-job limit bounds reservations that never reach `finish`. Set the
  limit from the product's real concurrency budget.
- `finish` runs on every exit path. Without it the map grows for the process
  lifetime. Use a guard type with `Drop` so a `?` early return cannot skip it.
- Hold the mutex only for the map operation. Never hold it across engine work.
- The `Ordering` arguments are deliberately left to `memory-model`. Do not pick
  them by feel.

### Checkpoint helper

Put the check in one place so every loop uses the same shape and the same error.

```rust
fn check_cancelled(flag: &AtomicBool) -> Result<(), CoreError> {
    if flag.load(/* see memory-model */) {
        return Err(CoreError::cancelled());
    }
    Ok(())
}
```

Call it:

- once at every `ProgressStage` transition, before the stage does work;
- inside inner loops at a bounded interval - per chunk, per block, per batch -
  not per cheap item, because an atomic load in a hot inner loop is a real cost.

### Partial output cleanup

The worker owns cleanup. Write to a temporary path and rename on success.

```rust
let tmp = target.with_extension("part");
let result = render_into(&tmp, &flag, listener);
match result {
    Ok(()) => std::fs::rename(&tmp, &target).map_err(CoreError::io)?,
    Err(e) => {
        let _ = std::fs::remove_file(&tmp); // best effort; do not mask `e`
        return Err(e);
    }
}
```

This makes the cancel path and the failure path identical, so you only test one.
It also means a crashed process leaves a `.part` file that is obviously
incomplete rather than a truncated file that looks real.

### Panic policy at the boundary

A panic must not unwind across the FFI boundary. A panic that unwinds out of an
`extern "C"` function aborts the process. Every exported function catches at its
own edge and converts to `EngineError::Unexpected` with a generic message. See `rust-panic-safety` for the catch shape and the `UnwindSafe`
requirements, and `rust-debugging` for how the generated bindings surface a
panic that does escape.

The listener call is the highest-risk site, because the foreign implementation
runs user code on the engine worker thread. A host listener that throws must not
take the engine down and must not abort the job silently - decide the policy and
write it down.

---

## 2. Kotlin bridge

### Full shape

```kotlin
class EngineClient(
    private val engine: Engine,                      // generated UniFFI object
    private val dispatcher: CoroutineDispatcher = Dispatchers.Default,
) {
    fun export(request: ExportRequest): Flow<ExportProgress> = callbackFlow {
        engine.reserveJob(request.jobId)
        val listener = object : ProgressListener {
            override fun onProgress(event: ProgressEvent) {
                trySend(event.toDomain())            // never blocks the worker
            }
        }
        launch(dispatcher) {
            try {
                engine.export(request.toFfi(), listener)
                close()
            } catch (e: EngineException) {
                close(e.toDomain())
            }
        }
        awaitClose { engine.cancelJob(request.jobId) }
    }.flowOn(dispatcher)
}
```

### Why `callbackFlow` and not `flow {}`

`flow {}` needs a suspending producer you drive. The engine drives itself and
pushes events from a worker thread, so the producer is a callback. `callbackFlow`
is the builder that allows `send`/`trySend` from another thread and gives you
`awaitClose` as a teardown hook.

`awaitClose` is not optional. `callbackFlow` throws
`IllegalStateException` if the builder block completes without it, which is a
deliberate guard against exactly the leak this bridge would otherwise have.

### Backpressure

`trySend` does not suspend and does not block. If the buffer is full it drops
the event and returns a failed result. That is the right trade for progress:
the newest fraction matters, an old one does not, and blocking the engine
worker to deliver a progress tick is never correct.

If you need every event delivered, that is a sign the event carries data it
should not - move that data out of the progress channel.

### Error translation

```kotlin
private fun EngineException.toDomain(): Throwable = when (this) {
    is EngineException.Cancelled -> CancellationException(message)
    is EngineException.InvalidRequest -> DomainError.RecoverableUser("invalid_request", message)
    is EngineException.NotFound -> DomainError.RecoverableData("not_found", message)
    // ... one arm per boundary variant
    else -> DomainError.ProgrammerError(message)       // newer engine, older binding
}
```

- The `when` matches on the generated subtype. A flat error carries only its
  message across the boundary, so there is no `code` field to read; the arm
  supplies the stable code string that matches the Rust `code()` value.
- `Cancelled` becomes `CancellationException`. Never wrap it in a domain error;
  a wrapped `CancellationException` stops propagating and the coroutine tree
  stays alive.
- The `else` arm is what lets an older binding survive a newer engine. It maps to
  the programmer-error bucket, which the UI shows as a generic failure and the
  build asserts on in debug.
- The mapper lives in the engine wrapper module. Nothing above it imports a
  generated type.

### Threading

Engine calls block. Run them on a dispatcher with threads to spare -
`Dispatchers.Default` for compute-bound engine work, `Dispatchers.IO` when the
job is dominated by file or network waiting. Never on `Dispatchers.Main`.

`flowOn(dispatcher)` only affects the upstream part of the chain; the collector's
context is unchanged, which is what you want - the UI collects on the main
dispatcher.

---

## 3. Swift bridge

### Full shape

```swift
actor EngineClient {
    private let ffi: Engine                          // generated UniFFI object

    nonisolated func export(
        request: ExportRequest
    ) -> AsyncThrowingStream<ExportProgress, Error> {
        AsyncThrowingStream { continuation in
            do {
                try ffi.reserveJob(jobId: request.jobId)
            } catch {
                continuation.finish(throwing: EngineClient.map(error))
                return
            }
            let listener = ProgressListenerImpl { event in
                continuation.yield(event.toDomain())
            }
            let task = Task.detached { [ffi] in
                do {
                    _ = try ffi.export(request: request.toFfi(), listener: listener)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: EngineClient.map(error))
                }
            }
            continuation.onTermination = { _ in
                ffi.cancelJob(jobId: request.jobId)
                task.cancel()
            }
        }
    }
}
```

### `onTermination` is the only cancel path

It fires on all three endings: normal finish, `finish(throwing:)`, and the
consumer's `Task` being cancelled or the stream being deallocated. Putting
`cancelJob` there means:

- there is exactly one cancel call site to review;
- a consumer that just walks away from the stream still cancels the engine;
- `cancelJob` is called on the completion path too, which is harmless because it
  is idempotent and tolerates a finished id.

That last point is why the "unknown or finished id is a no-op success" rule in
`SKILL.md` is not optional - this bridge depends on it.

### Listener lifetime

The listener object must outlive the engine call. In the closure above the
`Task` captures it, which is enough. Do not store it in a local that the
enclosing scope drops before the detached task runs, and do not make the
listener hold a strong reference back to the client - the callback runs on the
engine worker thread and a retain cycle there is invisible in the UI.

### Error translation

```swift
static func map(_ error: Error) -> Error {
    guard let engineError = error as? EngineError else { return error }
    switch engineError {
    case .Cancelled: return CancellationError()
    case .InvalidRequest(let message): return DomainError.recoverableUser(message)
    // ... one case per boundary variant
    default: return DomainError.programmerError(String(describing: engineError))
    }
}
```

`Cancelled` becomes `CancellationError` so a caller writing
`try Task.checkCancellation()` and a caller consuming the stream see the same
type on the cancel path.

### Main-actor discipline

The client is an `actor`, and the blocking engine call runs in `Task.detached`
so it does not inherit an actor context. The stream factory is `nonisolated`
because it does no isolated work - it only builds the stream.

---

## 4. Test matrix

Test the three protocols together. Each row below is a real bug class that a
single-protocol test suite misses.

| Case | Setup | Expected |
| --- | --- | --- |
| Happy path | Run a job to completion with a recording listener. | Stages arrive in enum order, `fraction` never decreases within a stage, terminal event is `Done`, stream finishes without error. |
| No listener | Same job with a no-op listener. | Output bytes are identical to the happy path. This is the determinism guard. |
| Slow consumer | Consumer sleeps between events. | Job completes in the same wall time as the happy path within tolerance. Dropped progress events are acceptable; a stalled engine is not. |
| Explicit cancel mid-job | Cancel during a long stage. | `Cancelled` within the stated latency budget; no partial output on disk; no error dialog path taken. |
| Pre-cancel | Reserve the id, then call `cancel_job` before the worker starts. | Job aborts at the first checkpoint and never does real work. |
| Cancel after completion | Cancel an id that already finished. | No-op success. Finished output still present and intact. |
| Double cancel | Cancel the same id twice. | Second call is a no-op success. |
| Unknown id cancel | Cancel many ids that were never reserved. | No-op success, no error, and no map growth. |
| Reservation limit | Reserve more than the configured active-job limit. | The excess reservation fails and memory stays bounded. |
| Consumer drops the stream | Collector goes out of scope without cancelling. | `awaitClose` / `onTermination` fires, `cancel_job` is called, no worker thread survives. |
| Engine error mid-job | Force a recoverable failure. | Stream throws the mapped domain error; partial output removed; `job_id` in the log lines matches the request. |
| Unknown error code | Feed the mapper a code it does not know. | Programmer-error bucket, not a crash and not a raw string in the UI. |
| Redaction | Trigger an error whose internal message contains a path and a source chain. | The boundary message and the log sink contain neither. |
| Listener throws | Host listener implementation raises. | Documented policy holds - the engine does not abort silently and does not unwind across the boundary. |

Run the cancel rows under a stress loop as well. A cancel that races the stage
transition is the case that finds missing checkpoints.

For leak detection under these tests, see `rust-sanitizers-miri`. For the
observability side of the `job_id` correlation, see `rust-observability`.
