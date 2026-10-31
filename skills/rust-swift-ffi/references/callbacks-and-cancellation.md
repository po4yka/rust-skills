# Callbacks and cancellation

Detail for the callback, threading, and cancellation rules in `SKILL.md`.

Contents:

- Give every callback one retained context
- Treat callbacks as concurrent and non-main-thread calls
- Make cancellation and release separate operations

## Give every callback one retained context

Represent a callback registration as three C values:

```c
typedef void (*rs_progress_fn)(void * _Nonnull context,
                               uint64_t completed,
                               uint64_t total);
typedef void (*rs_context_release_fn)(void * _Nonnull context);

rs_job_t * _Nullable rs_engine_start(
    rs_engine_t * _Nonnull engine,
    void * _Nonnull context,
    rs_progress_fn _Nonnull progress,
    rs_context_release_fn _Nonnull release_context,
    rs_error_t * _Nonnull error_out);
```

Swift passes one retained callback box as the context,
`Unmanaged.passRetained(box).toOpaque()`, and two `nonisolated` trampolines
reach it:

```swift
nonisolated final class CallbackBox: Sendable {
    let deliver: @Sendable (JobProgress) -> Void
    init(deliver: @escaping @Sendable (JobProgress) -> Void) { self.deliver = deliver }
}

nonisolated let progressTrampoline: rs_progress_fn = { context, completed, total in
    let box = Unmanaged<CallbackBox>.fromOpaque(context).takeUnretainedValue()
    box.deliver(JobProgress(completed: completed, total: total))
}

nonisolated let releaseTrampoline: rs_context_release_fn = { context in
    Unmanaged<CallbackBox>.fromOpaque(context).release()
}
```

The progress callback uses `takeUnretainedValue()`. A `takeRetainedValue()`
there consumes the reference on the first event and leaves later events with a
dangling pointer. The release callback releases exactly once. It can run on a
Rust worker, so keep `CallbackBox.deinit` thread-independent, and schedule UI
or main-actor cleanup before the terminal callback.

Rust owns the retained context after `rs_engine_start` succeeds. Rust calls
`release_context` exactly once after all of these facts are true:

- The job completed or observed cancellation.
- No callback is running.
- No future callback can start.
- Rust removed the registration from every queue.

If start fails, Swift still owns the context and must release it. State this
transfer point next to the function declaration.

Break the owner, job, and callback cycle. The box holds the Swift owner
weakly, and Rust holds the box only until the terminal state.

## Treat callbacks as concurrent and non-main-thread calls

Assume Rust invokes every callback from an arbitrary worker thread. Never
touch UIKit, AppKit, SwiftUI state, or a main-actor object directly in the C
callback. Never let an Objective-C exception escape into Rust: a foreign
unwind into an `extern "C"` Rust frame is undefined behavior, and Swift cannot
catch an `NSException`. Call an Objective-C API that can raise through an
`@try`/`@catch` shim, or keep it out of the C callback.

Swift concurrency checking stops at the C boundary. `Unmanaged` hides the box
type, so a non-`Sendable` box with a `var` compiles in Swift 6 mode and races
at run time. Make every type that Rust holds through a context pointer a
`final class` marked `Sendable`, with only `let` properties and mutable state
behind a `let` lock. Never add `@unchecked Sendable` only to silence a
diagnostic.

Mark `nonisolated` every type, extension, function, and global that a
trampoline or release callback reaches: the handle wrappers, the callback
box, value types such as `JobProgress`, and error-mapping helpers. Default
MainActor isolation (Swift 6.2+, SE-0466) makes every unannotated declaration
`@MainActor`, and an extension of a `nonisolated` class does not inherit
`nonisolated`. Do not rely on diagnostics to find a missed annotation. A box
and trampolines that are all inferred `@MainActor` compile with no diagnostic
in Swift 6 and Swift 5 mode, and Rust then runs the "main-actor" code on its
worker thread with no runtime check. Read
[swift-isolation.md](swift-isolation.md) when you choose
the lock for a context box, set or check the isolation build settings,
interpret an isolation diagnostic, write an async wrapper, or make Foundation
objects in a callback.

Mark an `async` wrapper method that calls a blocking Rust export `@concurrent`
(Swift 6.2+), or make the call in `Task.detached`. Under approachable
concurrency, a plain `nonisolated` async method runs on the caller's actor,
which can be the main actor.

The C trampoline must copy scalar values and borrowed bytes before it returns.
Then it schedules the copied event on the main actor:

```swift
let deliver: @Sendable (JobProgress) -> Void = { [weak owner] progress in
    Task { @MainActor in
        owner?.receive(progress)
    }
}
```

Keep callback work bounded. Copy the event, schedule delivery, and return. Do
not wait synchronously for `MainActor.run`. A Rust worker can hold a lock that
the UI call needs and deadlock the process. Wrap a synchronous callback body
that makes Foundation or Objective-C temporary objects in
`autoreleasepool { ... }`.

## Make cancellation and release separate operations

Expose cancel as idempotent and non-blocking. It only marks the job cancelled
and wakes its worker. It does not join the worker and does not release callback
state.

The terminal path has one order:

1. Stop producing callback events.
2. Wait for any in-flight callback to return.
3. Mark the job terminal.
4. Call `release_context` once, with no Rust lock held.
5. Release the worker's job reference.

Swift cancels when its `Task` or stream terminates. The wrapper can release its
job handle immediately if Rust workers hold their own reference. The callback
context stays valid until Rust calls the release function.

Swift can drop its last job or engine reference inside `release_context`, so
`rs_job_release` can run on the Rust worker thread. Make every release export
safe on that path: no join and no lock that the worker holds. A release that
joins its own worker panics with the `os error 11` message in the triage table
(Rust 1.98.1, macOS). The process then aborts, or a panic guard logs the panic
and leaks the worker.

Do not use a Swift Boolean alone to prevent callbacks after owner destruction.
It cannot protect a context pointer from a concurrent Rust call. Enforce the
no-callback-after-release rule in Rust, and use the weak Swift owner only to
drop already-scheduled UI delivery.
