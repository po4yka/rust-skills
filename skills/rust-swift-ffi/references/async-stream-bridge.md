# AsyncStream over a C callback

This bridge turns the `rs_engine_start` progress callback from `SKILL.md` into
an `AsyncStream`. It assumes the `Engine` class, a `nonisolated` `Sendable`
`JobProgress` struct, and the `EngineError(taking:)` initializer that the
`SKILL.md` snippets use. It also assumes two exports that `SKILL.md` does not
declare: `void rs_job_cancel(rs_job_t * _Nonnull job)`, which is idempotent and
thread-safe, and `void rs_job_release(rs_job_t * _Nullable job)`, which never
blocks. Put the extension in the file that declares `Engine`, so that it can
read `private let raw`. With Swift 6.4, the snippet compiles and runs against a
C stub under Thread Sanitizer with no report, in three configurations: Swift 6
mode with `nonisolated` default isolation, Swift 6 mode with `MainActor`
default isolation, and the Xcode 27 app template settings (Swift 5 mode,
`MainActor` default isolation, approachable concurrency).

Hold the continuation in the retained context box.
`AsyncStream.Continuation` is `Sendable`, so the trampoline yields directly
from the Rust thread. Finish the stream in the release callback, because Rust
calls it once after the last event. Cancel from `onTermination`. It fires when
the consumer stops or its task is cancelled, and also after `finish()`, so
cancel must be idempotent.

```swift
nonisolated final class Job: @unchecked Sendable {
    // Invariant: rs_job_cancel is thread-safe and idempotent, and
    // rs_job_release never blocks, on any thread.
    private let raw: OpaquePointer
    init(_ raw: OpaquePointer) { self.raw = raw }
    func cancel() { rs_job_cancel(raw) }
    deinit { rs_job_release(raw) }
}

nonisolated final class StreamBox: Sendable {
    let continuation: AsyncStream<JobProgress>.Continuation
    init(_ continuation: AsyncStream<JobProgress>.Continuation) { self.continuation = continuation }
}

nonisolated let yieldProgress: rs_progress_fn = { context, completed, total in
    let box = Unmanaged<StreamBox>.fromOpaque(context).takeUnretainedValue()
    box.continuation.yield(JobProgress(completed: completed, total: total))
}

nonisolated let finishStream: rs_context_release_fn = { context in
    Unmanaged<StreamBox>.fromOpaque(context).takeRetainedValue().continuation.finish()
}

// An extension does not inherit `nonisolated` from the class.
nonisolated extension Engine {
    func progressStream() throws -> AsyncStream<JobProgress> {
        let (stream, continuation) = AsyncStream.makeStream(
            of: JobProgress.self, bufferingPolicy: .bufferingNewest(1))
        let context = Unmanaged.passRetained(StreamBox(continuation)).toOpaque()
        var error = rs_error_t()
        guard let rawJob = rs_engine_start(raw, context, yieldProgress, finishStream, &error) else {
            Unmanaged<StreamBox>.fromOpaque(context).release()
            throw EngineError(taking: &error)
        }
        let job = Job(rawJob)
        continuation.onTermination = { _ in job.cancel() }
        return stream
    }
}
```

`onTermination` is assigned after start because it needs the job handle. If
Rust finishes first, the handler does not run at `finish()`. It runs with
`.cancelled` when the stream is deallocated, and it cancels a terminal job,
which is harmless because `rs_job_cancel` is idempotent. The `Job` releases
with the handler.

Use `AsyncThrowingStream` and `finish(throwing:)` when the terminal event
carries an error.

In this shape the last `Job` reference often dies inside `finishStream`, on
the Rust worker. `rs_job_release` then runs on that worker, so it must not
join the worker or take a lock that the worker holds (see the cancellation
section of `SKILL.md`).
