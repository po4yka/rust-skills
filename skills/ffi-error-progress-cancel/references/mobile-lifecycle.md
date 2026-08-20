# Mobile lifecycle contract

Use this reference when a UniFFI job or callback follows an Android or iOS UI
owner. Keep raw JNI rules in `rust-jni`. Keep a hand-written Swift C ABI in
`rust-swift-ffi`.

## Choose the execution model

Choose one model for the library and record it next to the platform wrapper.

| Model | Host responsibility | Rust responsibility |
| --- | --- | --- |
| No Rust runtime | Run synchronous UniFFI methods on a bounded platform worker scheduler. | Complete the call on the calling worker. Do not spawn hidden work. |
| Process-scoped runtime | Initialize one runtime or executor provider for the process. Create as many independent engine Objects as product state requires. | Share the bounded queue and worker set across engines. Keep them independent of screens and views. |

Prefer no Rust runtime when synchronous methods and the host scheduler are
enough. Add a Rust runtime only when Rust-owned timers, sockets, or task
coordination require it.

Never create a runtime or thread pool for each operation, `Activity`,
`ViewModel`, view controller, or Swift task. Do not rely on runtime shutdown for
correct output. Mobile platforms can terminate the process without it.

## Map owners to responsibilities

| Lifetime | Owns | Does not own |
| --- | --- | --- |
| Android application process | The optional shared runtime provider and long-lived engine wrappers | A screen collection job |
| Android `ViewModel` or lifecycle owner | The coroutine that collects the Flow and its registration | The Rust runtime or worker thread |
| iOS application container | The optional shared runtime provider and long-lived engine clients | A view task or stream iterator |
| Swift controller, model, or task | The consuming task and its registration | The Rust runtime or blocking shutdown |

When a UI owner ends, cancel its consumer and release its callback
registration. Do not destroy an engine that other owners share or the process
runtime provider because one screen goes away.

Use one owner for each consumer. Do not let both a view and a model call
`cancel_job` as independent policy owners. Multiple calls are safe because
cancel is idempotent, but duplicated ownership makes restart and error handling
ambiguous.

## Keep teardown non-blocking

Teardown can run on the main thread or in a destructor. It must finish without
waiting for Rust work.

- Android calls coroutine cancellation and the idempotent release method from
  `awaitClose`, `ViewModel.onCleared`, or the lifecycle collection scope.
- Swift cancels the consuming task and calls the idempotent release method from
  `onTermination` or explicit owner teardown.
- Rust sets a flag, closes registration, and returns. It does not join a thread,
  drain a queue, acquire a lock held by callback code, or wait for a job stage.
- A destructor can call the same release method as explicit teardown. The
  second call is a no-op.

Do not perform synchronous shutdown in `onCleared`, `deinit`, or an app
background callback. If a feature requires proof that work stopped, expose an
asynchronous completion signal and await it outside teardown.

## Deliver UI state on the platform UI executor

A Rust callback can arrive on any worker thread. It only converts and enqueues
an event.

- Kotlin keeps engine work upstream on `Dispatchers.Default` or
  `Dispatchers.IO`. Collect UI state in a main-dispatcher lifecycle scope, or
  use `withContext(Dispatchers.Main)` at the wrapper boundary.
- Swift keeps blocking engine work outside actor inheritance. Apply UI state in
  a `@MainActor` consumer or with `await MainActor.run`.
- Do not make the synchronous Rust callback wait for the UI executor. Yield to
  the Flow or stream and return.
- Do not assume `flowOn` moves the collector. It moves upstream work only.
- Do not assume an `actor` is the main actor. Use `@MainActor` when UI isolation
  is required.

Test the executor assertion at the UI delivery point. A test that only proves
that Rust called the listener does not prove correct UI isolation.

## Close the callback release race

Define release as a state transition, not as dropping the last foreign object
and hoping no worker still has it.

Give each registration a unique token and a monotonically increasing
generation. Guard admission and release with the same lock or state machine.
Admission validates the active token and generation and clones a strong
`Arc<Registration>` lease in one critical section. Release uses the same state,
marks the registration inactive, invalidates its generation, and removes the
registry's `Arc` before it returns. Do not split the state check from lease
acquisition. The admitted lease keeps the foreign callback alive until the call
returns.

The default non-blocking release guarantee is:

- no new callback is admitted after release returns;
- a callback admitted before release can finish because it owns a strong lease;
- queued platform delivery checks the generation again and drops stale work;
- the platform delivery closure holds a weak UI owner, so a destroyed owner is
  not retained and cannot receive state;
- release never waits for an in-flight callback.

If the product requires no callback invocation after release completion, drain
admitted callbacks asynchronously and complete release only after the drain.
Do not wait for that completion in UI teardown. If replacement only requires
ordering, drain asynchronously before publishing the replacement as ready.

Use a new generation when a screen restarts the same logical request. A late
event from the prior generation must not update the new screen. Keep the
`job_id` cancellation contract separate: `cancel_job` stops engine work;
registration release stops delivery to one consumer.

## Handle foreground and background transitions

Background execution is a best-effort time window. It is not a completion
guarantee.

- Cancel work that exists only for the visible UI.
- For work that must survive a screen, move ownership to an application-level
  service before the screen ends.
- For work that must survive process death, persist the input and a restart
  marker. Resume or restart it in a later process.
- Write output to a temporary path and rename it on success. A killed process
  must not leave a partial file that looks complete.
- Treat the platform deadline as a cancel request. Do not report success until
  Rust commits the final output.

Test the race between the background signal, `cancel_job`, the final progress
event, and output commit. Success produces a complete committed output.
Cancellation leaves no committed partial output.

## Survive process death and repeated initialization

Assume the process can stop without calling any shutdown API. Do not require a
Rust destructor, a callback release, or runtime drain for correctness.

Make process runtime or provider initialization idempotent:

- repeated initialization with the same configuration returns the same usable
  provider or an explicit already-initialized result;
- incompatible repeated configuration returns a typed error and does not
  replace live state;
- engine construction stays instance-scoped, so independent engine Objects can
  share the provider without sharing product state;
- startup removes or validates abandoned temporary output;
- persistent job input has an explicit schema version;
- no stale registration or in-memory job is assumed to exist after restart.

Do not persist callback tokens, pointers, or generated UniFFI handles. Rebuild
all process-local ownership after restart.

## Respond to low-memory signals

Expose one non-blocking memory-pressure entry point only when the library owns
meaningful caches.

- Clear bounded, recoverable caches such as decoded previews, indexes that can
  be rebuilt, or reusable scratch buffers.
- Keep active job ownership, cancellation flags, callback registrations,
  durable metadata, and committed output.
- Do not start I/O, compaction, or cache reconstruction from the signal.
- Keep the cache bounded even when no signal arrives. A low-memory callback is
  not a memory policy.

Skip this API when Rust owns no cache. An empty lifecycle hook is not useful.

## Required lifecycle tests

| Case | Action | Required result |
| --- | --- | --- |
| Owner drop | Destroy the Android or Swift owner while a job emits progress. | Consumer cancellation reaches `cancel_job`; registration releases; no new callback is admitted; teardown does not block. |
| Queued callback after release | Pause the UI executor, queue an event, release the registration, then resume delivery. | Generation check drops the event and the weak owner is not retained. |
| In-flight callback | Block a callback after admission, then release. | Release returns without waiting; the callback object stays alive through its strong lease; after the call returns, its context releases exactly once; no next callback begins. |
| Background and cancel race | Race the background deadline, cancel, final progress, and output commit. | Result is one terminal state; cancelled work leaves no committed partial output. |
| Process re-initialization | Initialize a provider and multiple engines, simulate process loss without shutdown, then initialize from persisted input again. | Provider initialization succeeds idempotently; independent engines can be recreated; no process-local handle is reused; abandoned temporary output is handled. |
| Low memory | Fill all caches, start a job, then send memory pressure. | Recoverable cache memory drops; active job and registration state remain valid. |
| UI executor | Deliver progress from a Rust worker. | Kotlin state changes on `Dispatchers.Main`; Swift UI state changes on `@MainActor`. |

Run the owner-drop and callback-release rows under a stress loop. Their value is
the race, not the happy path.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A closed screen updates or crashes | Callback admission races release, or queued delivery holds a strong UI owner | Linearize admission and release, keep an in-flight `Arc` lease, and capture the UI owner weakly |
| `onCleared` or `deinit` hangs | Teardown joins a worker or drains callbacks synchronously | Signal cancel and release, then return; observe completion asynchronously |
| Threads grow after navigation | A runtime or executor is created per screen or call | Move it to the process engine, or use the host worker scheduler |
| UI framework reports a thread violation | The callback mutates UI state on the Rust worker | Yield first, then apply state on `Dispatchers.Main` or `@MainActor` |
| Work is reported complete after a background deadline | Deadline handling reports intent instead of committed output | Cancel at the deadline and report success only after atomic output commit |
| Restart fails unless shutdown ran | Initialization depends on process-local cleanup | Make initialization idempotent and recover from persisted input and temporary output |
| Memory pressure cancels jobs | The pressure hook clears ownership state instead of caches | Restrict it to bounded, recoverable caches |
