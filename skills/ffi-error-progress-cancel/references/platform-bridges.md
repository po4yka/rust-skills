# Platform bridges: deep reference

Companion to `SKILL.md`. This file holds the parts of the Kotlin and Swift
bridges that do not fit in the main flow.

Contents:

1. Rust side: job registry (runnable model), checkpoint helper, partial output
   cleanup, panic and listener-failure policy, async exports
2. Kotlin bridge: the `callbackFlow` bridge, backpressure, error translation,
   threading
3. Swift bridge: full shape, the single cancel path, listener, error
   translation, actor isolation
4. Test matrix
5. Canonical sources

Terminology is the same as in `SKILL.md`:

- `CoreErrorKind`: the core crate's stable category enum.
- `EngineError`: the flat UniFFI boundary error.
- `ProgressListener` / `ProgressEvent` / `ProgressStage`: the progress foreign
  trait and its payload.
- `reserve_job(job_id)` and `cancel_job(job_id)`: the bounded reservation and
  the idempotent, non-blocking cancel entry point.

---

## 1. Rust side

### Job registry

Cancellation needs somewhere to put the flag before the worker starts. Reserve
the caller-supplied `job_id` synchronously before the host can cancel it. Bound
the reservation count so abandoned or hostile ids cannot grow the map without
limit.

The block is a runnable model. Its `main` proves pre-cancel, the unknown-id
no-op, duplicate rejection, launch-failure release, and poison recovery on the
non-throwing paths.

```rust,run
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

const MAX_ACTIVE_JOBS: usize = 64;
const MAX_JOB_ID_BYTES: usize = 128;
const RESERVATION_TTL: Duration = Duration::from_secs(30);

struct JobEntry {
    flag: Arc<AtomicBool>,
    reserved_at: Instant,
    running: bool,
}

#[derive(Default)]
pub struct JobRegistry {
    entries: Mutex<HashMap<String, JobEntry>>,
}

impl JobRegistry {
    /// Throwing path. Runs before the worker launches and before cancel is visible.
    pub fn reserve(&self, job_id: &str) -> Result<(), &'static str> {
        if job_id.is_empty() || job_id.len() > MAX_JOB_ID_BYTES {
            return Err("invalid job id size");
        }
        let mut entries = self.entries.lock().map_err(|_| "job registry poisoned")?;
        Self::reap_expired(&mut entries);
        if entries.contains_key(job_id) {
            return Err("duplicate job id");
        }
        if entries.len() >= MAX_ACTIVE_JOBS {
            return Err("too many active jobs");
        }
        entries.insert(job_id.to_owned(), JobEntry {
            flag: Arc::new(AtomicBool::new(false)),
            reserved_at: Instant::now(),
            running: false,
        });
        Ok(())
    }

    /// Throwing path. The worker calls it at start and picks up a pre-cancel.
    pub fn register(&self, job_id: &str) -> Result<Arc<AtomicBool>, &'static str> {
        let mut entries = self.entries.lock().map_err(|_| "job registry poisoned")?;
        Self::reap_expired(&mut entries);
        let entry = entries.get_mut(job_id).ok_or("job id not reserved")?;
        entry.running = true;
        Ok(Arc::clone(&entry.flag))
    }

    /// Non-throwing export. Idempotent, non-blocking, and panic-free.
    pub fn cancel(&self, job_id: &str) {
        let mut entries = self.lock_recovered();
        Self::reap_expired(&mut entries);
        if let Some(entry) = entries.get(job_id) {
            // Release pairs with the worker's Acquire load, so writes made
            // before cancel are visible once the worker sees the flag.
            entry.flag.store(true, Ordering::Release);
        }
    }

    /// Non-throwing. Runs on launch failure, on every worker exit, and in `Drop`.
    pub fn release(&self, job_id: &str) {
        self.lock_recovered().remove(job_id);
    }

    // Entries are independent and no critical section runs foreign code, so a
    // poisoned map is still consistent. A panic here is fatal in a
    // non-throwing Swift call, and a second panic inside `Drop` aborts.
    fn lock_recovered(&self) -> MutexGuard<'_, HashMap<String, JobEntry>> {
        self.entries.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn reap_expired(entries: &mut HashMap<String, JobEntry>) {
        entries.retain(|_, entry| entry.running || entry.reserved_at.elapsed() < RESERVATION_TTL);
    }
}

pub struct LaunchReservation<'a> {
    registry: &'a JobRegistry,
    job_id: String,
    committed: bool,
}

impl<'a> LaunchReservation<'a> {
    pub fn new(registry: &'a JobRegistry, job_id: &str) -> Result<Self, &'static str> {
        registry.reserve(job_id)?;
        Ok(Self { registry, job_id: job_id.to_owned(), committed: false })
    }

    /// Call only after the worker launch succeeds.
    pub fn commit(mut self) {
        self.committed = true;
    }
}

impl Drop for LaunchReservation<'_> {
    fn drop(&mut self) {
        if !self.committed {
            self.registry.release(&self.job_id);
        }
    }
}

fn main() {
    let registry = JobRegistry::default();

    // Pre-cancel: a cancel between reserve and register reaches the worker.
    registry.reserve("job-1").unwrap();
    registry.cancel("job-1");
    let flag = registry.register("job-1").unwrap();
    assert!(flag.load(Ordering::Acquire));

    // Unknown ids never allocate; duplicates and oversized ids are rejected.
    registry.cancel("never-reserved");
    assert_eq!(registry.lock_recovered().len(), 1);
    assert_eq!(registry.reserve("job-1"), Err("duplicate job id"));
    assert!(registry.reserve(&"x".repeat(MAX_JOB_ID_BYTES + 1)).is_err());

    // A failed launch drops the guard and releases the entry.
    drop(LaunchReservation::new(&registry, "job-2").unwrap());
    assert!(registry.register("job-2").is_err());
    LaunchReservation::new(&registry, "job-3").unwrap().commit();
    assert!(registry.register("job-3").is_ok());

    // Poison the lock. Non-throwing paths still work; throwing paths report it.
    let _ = std::thread::scope(|s| {
        s.spawn(|| {
            let _held = registry.entries.lock();
            panic!("simulated panic while the registry lock is held");
        })
        .join()
    });
    assert!(registry.entries.is_poisoned());
    registry.cancel("job-1");
    registry.release("job-1");
    assert_eq!(registry.reserve("job-4"), Err("job registry poisoned"));
}
```

Points that matter:

- `reserve` runs before the worker is launched. A later `cancel` sets the
  reserved flag, and `register` picks it up when the worker starts.
- `cancel` uses `get`, not `entry`. An unknown or finished id never allocates.
- Limit the encoded id size as well as the entry count. The two limits bound
  both key bytes and per-entry overhead.
- Use `LaunchReservation` when Rust launches the worker. A failed launch drops
  the guard and releases the entry. After a successful launch, call `commit`.
  The registry exports no release to the host. When the host launches the
  engine call and that call never starts, the TTL reaps the reservation.
- `release` runs on every worker exit path. Use a worker guard with `Drop` so a
  `?` early return cannot skip it.
- Reap reservations that never reach `register` after a short startup TTL.
  Reap on every registry operation so abandoned reservations cannot exhaust
  availability. Never expire a running job.
- Hold the mutex only for the map operation. Never hold it across engine work
  or a foreign callback.
- Poison policy: throwing paths map poison to a typed error; `cancel` and
  `release` recover the guard with `PoisonError::into_inner`. A
  `lock().expect(...)` in `cancel_job` is a fatal Swift error, not an exception.
  Poison is sticky: every later `reserve` and `register` fails until the process
  restarts. That is the intended fail-closed behavior.

### Checkpoint helper

Put the check in one place so every loop uses the same shape and the same error.

```rust
use std::sync::atomic::{AtomicBool, Ordering};

fn check_cancelled(flag: &AtomicBool) -> Result<(), CoreError> {
    if flag.load(Ordering::Acquire) {
        return Err(CoreError::cancelled());
    }
    Ok(())
}
```

Call it:

- once at every `ProgressStage` transition, before the stage does work;
- inside inner loops at a bounded interval (per chunk, per block, per batch),
  not per cheap item.

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

This makes the cancel path and the failure path identical, so you test one.
A crashed process leaves a `.part` file that is obviously incomplete, not a
truncated file that looks real.

### Panic policy at the boundary

UniFFI's generated scaffolding catches a panic in an exported function and
reports it as an internal error outside `EngineError`. Kotlin receives the
generated `InternalException` with the panic message as its text. Swift
receives a private error type in a throwing call, and a fatal error that it
cannot catch in a non-throwing call. So:

- Convert every expected failure into an `EngineError` variant before it
  leaves Rust. Treat the scaffolding guard as a last resort, not a channel.
- Keep the non-throwing `cancel_job` export and the registry `release` (it runs
  in `Drop`) panic-free.
- Never put secrets or user data in a panic message; the message reaches the
  host. The `rust-panic-safety` skill owns the catch shape and the
  `UnwindSafe` requirements.

The listener call is the highest-risk site, because the foreign implementation
runs host code on the engine worker thread. A host listener that throws must
not take the engine down and must not abort the job silently. The default
policy is in `SKILL.md`, section 2: the job ends with `Unexpected`. If you
choose another policy, for example "stop calling the listener and continue",
write it down and test it.

### Async exports do not cancel

Keep `cancel_job` when an operation is a UniFFI `async fn` export. UniFFI does
not forward platform cancellation to Rust as a cancel signal (UniFFI futures
guide, "Cancelling async code"). As of UniFFI 0.32:

- Kotlin throws the coroutine's own `CancellationException` at the call and
  frees the Rust future. The free drops the future at its current `.await`.
- Swift keeps awaiting until Rust returns. `Task` cancellation does not end the
  call.

A drop is not a cooperative cancel. It skips the `Cancelled` path and its
partial-output cleanup, and work that the future handed to another thread or
task keeps running. Neither platform maps a Rust `Cancelled` result to a
platform cancellation error, so map `EngineError::Cancelled` yourself.

---

## 2. Kotlin bridge

### Bridge

```kotlin
fun export(request: ExportRequest): Flow<ExportProgress> = callbackFlow {
    try {
        engine.reserveJob(request.jobId)             // bounded; before cancel is visible
    } catch (e: EngineException) {
        throw e.toDomain()                           // no generated type escapes
    } catch (e: Exception) {                         // InternalException or binding skew
        throw DomainError.EngineBug("internal")
    }
    val listener = object : ProgressListener {
        override fun onProgress(event: ProgressEvent) { trySend(event.toDomain()) }
    }
    launch(Dispatchers.Default) {                    // engine work off the main thread
        try {
            engine.export(request.toFfi(), listener)
            close()
        } catch (e: EngineException) {
            close(e.toDomain())
        } catch (e: Exception) {                     // panic or skew; never render its text
            close(DomainError.EngineBug("internal"))
        }
    }
    awaitClose { engine.cancelJob(request.jobId) }   // the only cancel path
}.buffer(Channel.CONFLATED)
```

Inside a client class, inject the engine and the dispatcher, launch the engine
call on that dispatcher, and append `.flowOn(dispatcher)` after
`.buffer(Channel.CONFLATED)`. Keep the `reserveJob` mapping and the final
`catch (e: Exception)`: they stop a generated type, a panic message, and a skew
error from leaving the wrapper.

If the collector cancels before the launched body runs, the body never starts
(`CoroutineStart.DEFAULT`). `awaitClose` still sets the reserved flag, and the
registry TTL reaps the reservation. Do not add a host-side release call.

### Backpressure

`SKILL.md` section 2 holds the `callbackFlow`, `awaitClose`, and conflation
rules. Treat a failed `trySend` as a closed-consumer signal, not as normal
overflow. Never block the engine worker to deliver a progress tick.

If you need every event delivered, the event carries data it should not. Move
that data out of the progress channel.

### Error translation

```kotlin
private fun EngineException.toDomain(): Throwable = when (this) {
    is EngineException.Cancelled -> CancellationException(message)
    is EngineException.InvalidRequest -> DomainError.RecoverableUser("invalid_request", message)
    is EngineException.NotFound -> DomainError.RecoverableData("not_found", message)
    // ... one arm per boundary variant; no `else`, so a new variant fails the build
}
```

- The `when` matches on the generated subtype. A flat error carries only its
  message, so there is no `code` field to read; the arm supplies the stable
  code string that matches the Rust `code()` value.
- `Cancelled` becomes `CancellationException`. Never wrap it in a domain error;
  a wrapped `CancellationException` stops propagating and the coroutine tree
  stays alive.
- An `else` arm is dead code. The generated reader throws
  `RuntimeException("invalid error enum value, something is very wrong!!")`
  for an unknown variant index before any `EngineException` exists.
- `InternalException` (a Rust panic, with the panic text as its message) and
  that `RuntimeException` are not `EngineException`s. The final
  `catch (e: Exception)` in the bridge sends both to the engine-bug bucket. It
  cannot swallow a coroutine cancellation, because the wrapped engine calls
  block and do not suspend.
- The mapper lives in the engine wrapper module. Nothing above it imports a
  generated type.

### Threading

Engine calls block. Run them on a dispatcher with threads to spare:
`Dispatchers.Default` for compute-bound engine work, `Dispatchers.IO` when the
job is dominated by file or network waiting. Never run them on
`Dispatchers.Main`.

`flowOn(dispatcher)` only affects the upstream part of the chain. The
collector's context does not change, which is correct: the UI collects on the
main dispatcher.

When Rust-owned worker threads call the listener often, attach each worker to
the JVM once, at thread start. Otherwise JNA attaches and detaches the native
thread on every callback (UniFFI Kotlin Gradle guide). With `jni` 0.22,
`JavaVM::attach_current_thread` requests a permanent attachment. It gets the VM
from `JavaVM::singleton()`, which returns `Error::UninitializedJavaVM` until
something seeds it. The generated bindings load the library with JNA
`Native.register`, a `dlopen` that does not run `JNI_OnLoad`. UniFFI does not
generate a `JNI_OnLoad`, so seed the singleton yourself:

1. Export a `JNI_OnLoad` that calls `JavaVM::from_raw` and returns
   `JNI_VERSION_1_6`. Take the template from the `rust-jni` skill. Remove its
   `RegisterNatives` part: a UniFFI crate has no native methods to register,
   and a lookup of a class that does not exist returns `JNI_ERR` and fails the
   load.
2. Call `System.loadLibrary("<cdylib_name>")` once before the first binding
   call.

---

## 3. Swift bridge

### Full shape

```swift
actor EngineClient {
    private let ffi: Engine                          // generated UniFFI object

    nonisolated func export(
        request: ExportRequest                       // must be Sendable
    ) -> AsyncThrowingStream<ExportProgress, Error> {
        let ffi = self.ffi                           // a Sendable local for the closures
        return AsyncThrowingStream(ExportProgress.self, bufferingPolicy: .bufferingNewest(1)) { continuation in
            do {
                try ffi.reserveJob(jobId: request.jobId)
            } catch {
                continuation.finish(throwing: EngineClient.map(error))
                return
            }
            continuation.onTermination = { _ in
                ffi.cancelJob(jobId: request.jobId)  // also runs after finish; idempotent
            }
            let listener = ProgressListenerImpl { event in
                continuation.yield(event.toDomain())
            }
            Task.detached {
                do {
                    _ = try ffi.export(request: request.toFfi(), listener: listener)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: EngineClient.map(error))
                }
            }
        }
    }
}

nonisolated final class ProgressListenerImpl: ProgressListener {
    private let onEvent: @Sendable (ProgressEvent) -> Void

    init(_ onEvent: @escaping @Sendable (ProgressEvent) -> Void) {
        self.onEvent = onEvent
    }

    func onProgress(event: ProgressEvent) throws {   // Rust calls this on its worker thread
        onEvent(event)
    }
}
```

### `onTermination` is the only cancel path

Putting `cancelJob` in `onTermination` means:

- there is exactly one cancel call site to review;
- a consumer that walks away from the stream still cancels the engine;
- `cancelJob` also runs on the completion path, which is harmless because it
  is idempotent and tolerates a finished id.

That last point is why the "unknown or finished id is a no-op success" rule in
`SKILL.md` is not optional: this bridge depends on it. `SKILL.md` section 2
holds the assignment-order and non-blocking rules for the handler.

The detached task is not cancelled from the handler. `Task.cancel()` does not
interrupt a synchronous FFI call; the Rust flag does.

### Listener

- The generated foreign-trait protocol inherits `Sendable` (UniFFI Swift
  overview). The implementation is a `final class` with only `let` properties of
  `Sendable` type, and its closure is `@Sendable`.
- In a module built with MainActor default isolation (SE-0466:
  `-default-isolation MainActor`, or SwiftPM `.defaultIsolation(MainActor.self)`),
  unannotated declarations are inferred `@MainActor`. A class that directly
  conforms to the `Sendable` listener protocol is exempt, but the conversion
  helpers it and the detached task call (`toDomain`, `toFfi`) are not. Swift
  6.4 then rejects the bridge with "call to main actor-isolated instance method
  'toDomain()' in a synchronous nonisolated context". Mark those helpers
  `nonisolated`, or keep the wrapper in a target that keeps the default
  `nonisolated` isolation. A free error `map` function is also inferred
  `@MainActor`; Swift 6.4 accepts the static `EngineClient.map` above. The
  explicit `nonisolated` on the listener (Swift 6.1+) states that it has no
  actor isolation.
- The listener must outlive the engine call. The detached task captures it,
  which is enough. Do not let the listener hold a strong reference back to the
  client: the callback runs on the engine worker thread, and a retain cycle
  there is invisible in the UI.

### Error translation

```swift
static func map(_ error: Error) -> Error {
    guard let engineError = error as? EngineError else {
        return DomainError.engineBug                 // Rust panic, unknown variant, UniFFI internal error
    }
    switch engineError {
    case .Cancelled: return CancellationError()
    case .InvalidRequest(let message): return DomainError.recoverableUser(message)
    // ... one case per boundary variant; no `default`, so a new case fails the build
    }
}
```

- The guard catches binding and library skew. The generated reader throws
  `UniffiInternalError.unexpectedEnumCase`, a `fileprivate` type, for an unknown
  variant index, so the `switch` never sees one.
- `Cancelled` becomes `CancellationError`, so a caller that writes
  `try Task.checkCancellation()` and a caller that consumes the stream see the
  same type on the cancel path.
- Never pass the generated error through, and never render its
  `localizedDescription` or `String(describing:)`: both are the debug form.
  UniFFI conforms the type to `LocalizedError` with `errorDescription` set to
  `String(reflecting: self)`, which names the module, the type, and the case.
- To remove that conformance, set `omit_localized_error_conformance = true` in
  the `[bindings.swift]` table of `uniffi.toml`. That does not make
  `localizedDescription` safe to show: the `NSError` bridge text still names the
  module and the type. Map the error either way.

### Actor isolation

The client is an `actor`, and the blocking engine call runs in `Task.detached`
so it inherits no actor. The stream factory is `nonisolated` because it only
builds the stream.

Do not move the blocking call into a `nonisolated async` helper. Under Swift 6.2
`NonisolatedNonsendingByDefault` (SE-0461, part of approachable concurrency),
such a helper runs on the caller's actor, which can be the main actor. If you
need a helper, mark it `@concurrent`.

---

## 4. Test matrix

Test the three protocols together. Each row is a real bug class that a
single-protocol test suite misses.

| Case | Setup | Expected |
| --- | --- | --- |
| Happy path | Run a job to completion with a recording listener. | Stages arrive in enum order, `fraction` never decreases within a stage, terminal event is `Done`, stream finishes without error. |
| No listener | Same job with a no-op listener. | Output bytes are identical to the happy path. This is the determinism guard. |
| Slow consumer | Consumer sleeps between events, on Kotlin and on Swift. | Job completes in the same wall time as the happy path within tolerance, and consumer-side memory stays flat. Dropped progress events are acceptable; a stalled engine is not. |
| Explicit cancel mid-job | Cancel during a long stage. | `Cancelled` within the stated latency budget; no partial output on disk; no error dialog path taken. |
| Pre-cancel | Reserve the id, then call `cancel_job` before the worker starts. | Job aborts at the first checkpoint and never does real work. |
| Cancel after completion | Cancel an id that already finished. | No-op success. Finished output still present and intact. |
| Double cancel | Cancel the same id twice. | Second call is a no-op success. |
| Unknown id cancel | Cancel many ids that were never reserved. | No-op success, no error, and no map growth. |
| Reservation limits | Reserve an oversized id and more than the active-job limit. | Both fail and total key bytes and entry count stay bounded. |
| Launch failure | Reserve an id, then fail before the worker starts. | Rust launch: the launch guard removes the entry immediately. Host launch that never starts: the entry is reaped after the TTL. |
| Abandoned reservation | Reserve without register or release, advance past the TTL, then reserve again. | The stale entry is reaped and capacity becomes available. |
| Poisoned registry | Call a test-only export, behind a `cfg` or a Cargo feature, that panics while it holds the registry lock. Then call `cancel_job` and `reserve_job` from the Kotlin and Swift smoke tests. | `cancel_job` returns normally, and `reserve_job` throws a typed error in the engine-bug bucket. No `InternalException`, no Swift fatal error. The Rust registry test covers `release` after poison. |
| Consumer drops the stream | Collector goes out of scope without cancelling. | `awaitClose` / `onTermination` fires, `cancel_job` is called, no worker thread survives. |
| Engine error mid-job | Force a recoverable failure. | Stream throws the mapped domain error; partial output removed; `job_id` in the log lines matches the request. |
| Engine panic | Call a test-only export, behind a `cfg` or a Cargo feature, that panics inside the export. | Engine-bug bucket; the panic text is not in the UI. |
| Newer library, older binding | Load a library whose `EngineError` has a variant that the binding does not know, and return that variant. | Engine-bug bucket, no crash, and no raw text in the UI. |
| Redaction | Trigger an error whose internal message contains a path and a source chain. | The boundary message and the log sink contain neither. |
| Listener throws | Host listener implementation raises. | The job ends with `Unexpected` (engine-bug bucket) or the documented alternative policy; partial output removed; nothing unwinds across the boundary. |
| Swift isolation | Compile the wrapper in Swift 6 language mode with the app target's default isolation, then deliver progress from a Rust worker. | It compiles, and progress reaches the consumer without an actor-isolation failure. |

Run the cancel rows under a stress loop as well. A cancel that races the stage
transition finds missing checkpoints.

For leak detection under these tests, see the `rust-sanitizers-miri` skill. For
the observability side of the `job_id` correlation, see the
`rust-observability` skill.

---

## 5. Canonical sources

- UniFFI `#[uniffi(flat_error)]` and the `Error` derive:
  https://mozilla.github.io/uniffi-rs/latest/proc_macro/errors.html
- UniFFI foreign traits:
  https://mozilla.github.io/uniffi-rs/latest/foreign_traits.html
- UniFFI async exports and "Cancelling async code":
  https://mozilla.github.io/uniffi-rs/latest/futures.html
- UniFFI Swift panics in non-throwing calls, and `Sendable` foreign traits:
  https://mozilla.github.io/uniffi-rs/latest/swift/overview.html
- UniFFI Swift `omit_localized_error_conformance`:
  https://mozilla.github.io/uniffi-rs/latest/swift/configuration.html
- Kotlin `callbackFlow`, `awaitClose`, and buffer fusion:
  https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/callback-flow.html
- Kotlin `CoroutineStart.DEFAULT` (a job cancelled before it starts never runs):
  https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/-coroutine-start/
- Swift `AsyncThrowingStream`, buffering policy, and `onTermination`:
  https://developer.apple.com/documentation/swift/asyncthrowingstream
- Swift SE-0466, default actor isolation:
  https://github.com/swiftlang/swift-evolution/blob/main/proposals/0466-control-default-actor-isolation.md
- Swift SE-0461, caller-isolated `nonisolated async` functions:
  https://github.com/swiftlang/swift-evolution/blob/main/proposals/0461-async-function-isolation.md
