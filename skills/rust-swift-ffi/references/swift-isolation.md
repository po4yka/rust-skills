# Swift isolation at a Rust boundary

Detail for the `Sendable`, `nonisolated`, `@concurrent`, and autorelease rules
in `SKILL.md`. The results were measured with Swift 6.4.

## Mutable state in a context box

Keep mutable state in a `let` `Mutex` from `Synchronization` (iOS 18+) or an
`OSAllocatedUnfairLock` (iOS 16+), so the compiler checks the `Sendable`
conformance. Use `@unchecked Sendable` only below those deployment floors or
for a wrapper whose safety comes from Rust, and write the invariant next to
the conformance.

## Where default MainActor isolation comes from

A module with default MainActor isolation infers `@MainActor` for every
unannotated declaration (Swift 6.2+, SE-0466). The mode comes from one of
these settings:

- The `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` build setting. The Xcode 27
  app template sets it.
- The compiler flag `-default-isolation MainActor`.
- The SwiftPM setting `.defaultIsolation(MainActor.self)`.

A SwiftPM target without that setting defaults to `nonisolated`.
`nonisolated` on a type needs Swift 6.1 (SE-0449). An extension of a
`nonisolated` class does not inherit `nonisolated`.

## What the compiler reports

Measured under MainActor default isolation:

- A box and trampolines that are all inferred `@MainActor` compile without a
  diagnostic in Swift 6 and Swift 5 mode. Rust then runs the "main-actor"
  code on its worker thread, and no runtime check fires.
- A mix fails in Swift 6 mode with one of the isolation errors in the Triage
  table below. Swift 5 mode reports some of them as warnings and
  misses others, for example a `nonisolated` trampoline that calls a method on
  an unannotated struct.
- `MainActor.assumeIsolated` inside the callback traps in
  `dispatch_assert_queue` on the first Rust-thread call.
- A handle class without `nonisolated` fails at its `deinit` with
  `cannot access property 'raw' with a non-Sendable type 'OpaquePointer' from
  nonisolated deinit`.

## Async wrappers over blocking exports

With `SWIFT_APPROACHABLE_CONCURRENCY = YES`, which the Xcode 27 project
template sets, a plain `nonisolated` async method runs on the caller's actor
(SE-0461). That can be the main actor, so a blocking Rust call hangs the UI.

Choose the thread by the length of the call:

- **Short call** (it returns without waiting on I/O, a lock, or a long
  computation): mark the method `@concurrent` (Swift 6.2+), or make the call in
  `Task.detached`. Swift 6 mode lets a main-actor caller use a `@concurrent`
  method only on a `Sendable` wrapper. Otherwise it reports `sending
  'self.engine' risks causing data races`.
- **Long call** (it blocks for seconds, waits on I/O, or runs a job with
  progress): run it on a dedicated `Thread` or on a `DispatchQueue` that the
  wrapper owns, and bridge the result with `withCheckedThrowingContinuation` or
  with the `AsyncThrowingStream` continuation. `@concurrent` and
  `Task.detached` both run on the cooperative pool. That pool is limited to
  about the CPU core count and does not grow when a thread blocks, so a few long
  calls stall every `await` in the process.

Bound the dedicated threads: cap the number of concurrent long jobs in Rust or
in the wrapper, and do not start one thread per call without that cap.

```swift
nonisolated func render(_ input: RenderInput) async throws -> RenderOutput {
    let engine = self.engine                     // a Sendable local
    return try await withCheckedThrowingContinuation { continuation in
        Thread {
            continuation.resume(with: Result { try engine.render(input) })
        }.start()
    }
}
```

## Autorelease pools on Rust threads

When a callback on a Rust-created thread constructs Foundation or
Objective-C temporary objects, wrap the synchronous callback body in
`autoreleasepool { ... }`. Copy all values that must outlive
the pool. A task scheduled onto an Apple executor uses that executor's pool
and usually does not need a second one.

## Triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `main actor-isolated ... can not be referenced from a nonisolated context`, `main actor-isolated default value in a nonisolated context`, `call to main actor-isolated ... in a synchronous nonisolated context`, or a `deinit` Sendable error | The module uses default MainActor isolation | Mark `nonisolated` every declaration that Rust reaches (see above) |
| UI hangs while an async wrapper waits on Rust | A `nonisolated` async method runs on the main actor under `nonisolated(nonsending)` | Mark a short call `@concurrent`; run a long one on a dedicated `Thread` |
| Thread Sanitizer reports a race in a context box that compiles clean in Swift 6 | `Unmanaged` hides a non-`Sendable` box | Make the box a `final class` marked `Sendable`, with `let` properties and a `let` lock |
| Trap in `dispatch_assert_queue` on the first callback | `MainActor.assumeIsolated` ran on a Rust thread | Make the box `nonisolated` and hop with `Task { @MainActor in ... }` |
| UI isolation warning or crash | Rust called a main-actor value directly | Copy the event and hop with `Task { @MainActor in ... }` |
