# Review checklist

Companion to `SKILL.md`. Use it when you review a change to the error model, the
progress stream, the cancel path, or the mobile lifecycle wrapper. Close every
item that the change touches.

## Error model

- [ ] The boundary error enum is flat, closed, and versioned. No `anyhow` chain,
      backtrace, or verbatim path crosses the boundary.
- [ ] Every core kind maps to one boundary variant: an exhaustive match in the
      defining crate, or a wildcard to `Unexpected` plus a stable-code contract
      test across crates. Every kind has one of the five buckets.
- [ ] Mappers key off the generated variant or `code()`, never the message, and
      have no `else` or `default` arm. A Rust panic and every error that is not
      a generated boundary error, binding skew included, go to the engine-bug
      bucket.
- [ ] A host log sink admits only allowlisted fields (enum cases, counts,
      booleans). No message, path, or source chain reaches it.
- [ ] The UI renders only the mapped app error, never a generated error's
      `localizedDescription` or a panic message.
- [ ] No generated FFI type escapes the single platform wrapper layer.

## Progress

- [ ] Kotlin conflates with `buffer(Channel.CONFLATED)`; Swift uses
      `.bufferingNewest(1)`. Listener callbacks are cheap and non-blocking.
- [ ] The progress event carries only `job_id`, `stage`, and `fraction`, and the
      closed stage enum ends in `Done`. Golden output is byte-identical with and
      without a listener.

## Cancellation

- [ ] `reserve_job` bounds id bytes and entry count and rejects duplicates.
      A failed Rust launch releases the reservation, and a TTL reaps abandoned
      ones.
      `cancel_job` never inserts unknown ids and supports pre-cancel.
- [ ] `cancel_job` and the registry `release` cannot panic, including after lock
      poison.
- [ ] `awaitClose` and `onTermination` are the only cancel paths, and
      `onTermination` is set before the task starts. `Cancelled` maps to
      `CancellationException` and `CancellationError`.
- [ ] Cancellation is observed within a written-down stage or iteration budget.

## Mobile lifecycle

- [ ] Mobile teardown only signals cancel and callback release. It never blocks
      `onCleared`, `deinit`, or the main thread.
- [ ] UI delivery hops through `Dispatchers.Main` or `@MainActor`, and released
      registrations reject queued callbacks through a written race policy.
- [ ] Initialization survives process restart without a prior shutdown, and a
      low-memory signal clears only bounded, recoverable caches.
