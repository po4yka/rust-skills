---
name: rust-async-internals
description: Use when you author or review async Rust that can be polled inside tokio::select!, tokio::time::timeout, JoinSet, or FuturesUnordered; when you bridge a foreign thread into a runtime with block_on; when you configure a tokio runtime for a constrained target; when you design CancellationToken parent/child shutdown trees; when you choose between spawn_blocking, block_in_place, and std::thread::spawn; when you poll a future by hand from a synchronous event loop; or when you audit for std::sync::Mutex-across-await deadlocks, broadcast Lagged data loss, !Send futures, and cancel-safety bugs. Triggers on "select", "disabled select branch", "JoinHandle", "async closure", "join", "spawn", "cancellation", "tokio runtime", "block_on", "async fn in traits", "task stall", "shutdown hang", or "async hang".
license: BSD-3-Clause
---

# Rust Async Internals

## When to use this skill

Use this skill when you do one of these things:

- You author or review an `async fn` that can be polled inside `tokio::select!`,
  `tokio::time::timeout`, `JoinSet`, or `FuturesUnordered`.
- You bridge a foreign thread (JNI, a C callback, a platform service thread)
  into a tokio runtime with `block_on`.
- You configure a runtime for a constrained target, or you decide between
  `current_thread` and `multi_thread`.
- You design shutdown with `CancellationToken`.
- You choose between `spawn_blocking`, `block_in_place`, and
  `std::thread::spawn`.
- You poll a future by hand from a synchronous loop.
- You diagnose a stall, a shutdown hang, a latency spike, or a silent message
  loss.

## Decision table

Read this table first. It answers most async design questions in one line.

| You must | Use | Do not use |
|---|---|---|
| Run N futures and keep only the first result | `tokio::select!` | `join!` |
| Run N futures to completion | `tokio::join!` or `try_join!` | `select!` |
| Own a dynamic set of spawned tasks | `JoinSet` | a bare `Vec<JoinHandle>` |
| Bound the concurrency of a work stream | `stream::iter(..).buffer_unordered(K)` | `spawn` in an unbounded loop |
| Shut down a task tree | `CancellationToken` + `child_token()` | `Notify` |
| Cancel on any early return or panic | `token.drop_guard()` | manual cleanup at each `?` |
| Race work against shutdown and keep the value | `token.run_until_cancelled(fut)` | a hand-written `select!` |
| Do bounded CPU work (target < 100 ms) | `spawn_blocking` | `block_in_place` |
| Run an indefinite blocking loop | `std::thread::spawn` | `spawn_blocking` |
| Hold a lock across `.await` | `tokio::sync::Mutex` | `std::sync::Mutex` |
| Deliver every message without loss | `mpsc` | `broadcast` |
| Bound how long a caller waits for CPU work | `timeout(d, spawn_blocking(..))` | `timeout(d, cpu_work())` |
| Keep a critical `.await` sequence atomic | `tokio::spawn` + join the handle | `select!` around it |

## Runtime configuration

### Build the runtime explicitly

```rust
tokio::runtime::Builder::new_multi_thread()
    .worker_threads(2)               // constrain for battery and CPU budget
    .thread_stack_size(1024 * 1024)  // 1 MiB; some platform defaults are too small
    .thread_name("app-tokio")
    .enable_all()
    .build()
```

Apply these rules:

- Set `worker_threads` explicitly on mobile and embedded targets. The default
  is one thread per core, which trades battery for throughput you do not need.
- Set `thread_stack_size` explicitly when the platform default stack is small.
  Deep async state machines overflow a small stack, and the crash looks like a
  random SIGSEGV, not a stack overflow.
- Name the threads. A named thread makes a stack dump readable.

### Share one runtime

Store the runtime in a `OnceCell<Arc<Runtime>>` and share it across units of
work. Do not build a runtime per session, per request, or per FFI call. Each
build creates a fresh thread pool.

### current_thread against multi_thread

| Flavor | Use it for | Constraint |
|---|---|---|
| `multi_thread` | production I/O concurrency | spawned futures must be `Send + 'static` |
| `current_thread` | tests, and synchronous wrapper APIs that call `block_on` | `block_in_place` panics on it |

`#[tokio::test]` uses `current_thread` by default. Production code that calls
`block_in_place` therefore panics under such a test. See the pitfall catalog.

### Tokio version floor

Do not downgrade tokio below these versions.

| Minimum | Fix | Why it matters |
|---|---|---|
| 1.42.1 | `broadcast::Sender::clone()` soundness bug (missing synchronization for `Send + !Sync` payloads); a `CancellationToken` race where a future that polled to `Ready` before the token fired was not cancelled | any abort path that relies on `CancellationToken` |
| 1.51.1 | file-descriptor leak when an `io_uring` `open` operation is cancelled before completion | any code that cancels in-flight FS or I/O work on teardown; below this version the leaked fds accumulate until process exit |

Check the resolved version with `cargo tree --locked -i tokio`. If it is below
the floor, promote it in the workspace `Cargo.toml` under
`[workspace.dependencies]`. Never downgrade a transitive dependency to work
around a breaking change. Open an upstream issue instead.

References: the tokio
[CHANGELOG](https://github.com/tokio-rs/tokio/blob/master/tokio/CHANGELOG.md),
[PR #7462](https://github.com/tokio-rs/tokio/pull/7462),
[PR #7983](https://github.com/tokio-rs/tokio/pull/7983).

## Drive async from a foreign thread

A foreign thread (a JNI call, a C callback, a platform service thread) cannot
`.await`. It must enter the runtime through `block_on`. Two shapes exist.

**Shape A — hand off to a worker thread.** The foreign call returns at once.
Use this when the work is long-running and the caller must not block.

```rust
let worker = std::thread::Builder::new()
    .name("app-worker".into())
    .spawn(move || {
        let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
            runtime.block_on(run_session(config, fd, cancel, stats))
        }));
        // Record Ok / Err / panic into shared state before the thread exits.
    });
// The foreign thread returns immediately.
// A later stop call cancels the work through the CancellationToken.
```

**Shape B — block the calling thread.** The foreign thread owns the work for
its whole lifetime. Use this only when the caller is a dedicated service
thread that has nothing else to do.

Apply these rules to both shapes:

1. Never call `block_on` for long-running work directly on a callback thread
   that the host expects to return promptly.
2. Wrap the `block_on` body in `catch_unwind`. A panic must never unwind
   across an FFI boundary. See `rust-panic-safety`.
3. Duplicate any file descriptor you receive (for example with
   `nix::unistd::dup`) before you pass it into async code. The host can revoke
   the original at any time. Close the duplicate on every error path, including
   a failed start.
4. Reset shared state with an RAII guard, not with cleanup code at each early
   return. A guard that flips the module back to `Idle` on drop keeps the state
   correct after a panic too.
5. Store the `CancellationToken` in the state-machine variants that own live
   work (for example `Starting` and `Running`), so stop and destroy paths can
   always reach it.

See `rust-jni` and `ffi-error-progress-cancel` for the boundary contract, and
`uniffi-boundary` when the boundary is generated.

## Cancellation

### select! drops the losing branches

`select!` completes when the first branch finishes. Every other branch future
is dropped at that instant. Work in progress inside a dropped branch is lost.

```rust
async fn fetch_a() -> u32 { todo!() }
async fn fetch_b() -> u32 { todo!() }

tokio::select! {
    result = fetch_a() => { /* fetch_b() is dropped mid-flight */ }
    result = fetch_b() => { /* fetch_a() is dropped mid-flight */ }
}
```

Therefore every future you put in a `select!` arm must be cancel-safe. Read
the cancel-safety rules and the library method table in
[references/async-pitfall-catalog.md](references/async-pitfall-catalog.md).

`join!` waits for all branches. It has no cancellation surprise.

A disabled branch still evaluates its async expression. Tokio does not poll the resulting
future, but synchronous setup in the expression can allocate, lock, mutate state, or panic.
Move side effects into the async body, or compute the branch only after its precondition.

### Put shutdown first with `biased`

```rust
loop {
    tokio::select! {
        biased;
        _ = cancel.cancelled() => break,  // always polled first
        msg = rx.recv() => process(msg),
    }
}
```

Without `biased`, `select!` polls arms in random order. A saturated data arm
can then starve the shutdown arm.

Rule: every long-lived `select!` loop must have a `cancel.cancelled()` arm. A
loop without one never terminates, and shutdown hangs.

### CancellationToken tree

Use `tokio_util::sync::CancellationToken` for structured shutdown, not
`tokio::sync::Notify`.

```rust
let master = CancellationToken::new();
for job in jobs {
    let child = master.child_token();
    tokio::spawn(async move { run_job(job, child).await });
}
// master.cancel() propagates to every child.
// child.cancel() affects only that child; siblings keep running.
```

Two more idioms are in the catalog: `drop_guard()` for cancel-on-early-exit,
and `run_until_cancelled(fut)` for "race against shutdown, keep the value".

## Concurrency composition

- `JoinSet` owns a set of spawned tasks. `join_next().await` yields the next
  completed result. `abort_all()` aborts every task. Dropping the `JoinSet`
  aborts the tasks but does not wait for them.
- `FuturesUnordered` polls a set of futures in place, without spawning. A
  future that you remove from the set is dropped, so the same cancel-safety
  rule as `select!` applies to every future you put in it.
- `stream::iter(items).buffer_unordered(K)` bounds concurrency to K.

Dropping a bare `JoinHandle` detaches its task. It does not cancel the task. Keep the handle,
signal cooperative cancellation, and await it. Use `abort()` only when abrupt cancellation is
part of the task contract, and still await the handle to observe completion.

Rule: any `for x in xs { tokio::spawn(work(x)); }` loop with N > 1 is a
refactor candidate. Replace it with `JoinSet::spawn` + `join_next`, with
`futures::future::join_all` for a small fixed N, or with `buffer_unordered(K)`
for a stream.

## Blocking work

| Work shape | Mechanism | Reason |
|---|---|---|
| Bounded CPU work, target < 100 ms | `spawn_blocking` | returns the pool thread quickly |
| Occasional blocking syscall, short file I/O | `spawn_blocking` | same |
| Indefinite blocking loop, watcher, persistent synchronous connection | `std::thread::spawn` | it would occupy a pool thread forever |
| Anything on a `current_thread` runtime | `spawn_blocking` | `block_in_place` panics there |

The blocking pool has a default cap of 512 threads. Long-lived
`spawn_blocking` tasks saturate it. The symptom is a latency spike with no
obvious cause, because new `spawn_blocking` calls queue behind the occupied
threads.

A synchronous protocol client that runs on its own `std::thread`, outside the
runtime, is a valid design and not a bug. Write a comment at the spawn site
that states the intent, so a later reader does not "fix" it into async.

## Send and !Send across .await

`tokio::spawn` requires `Send + 'static`. A value that lives across an
`.await` point becomes part of the future, so a `!Send` value makes the whole
future `!Send`.

- `std::sync::MutexGuard` is `!Send`. On a `multi_thread` runtime the compiler
  rejects it inside `tokio::spawn`. On a `current_thread` runtime, or inside a
  non-`Send` future, the compiler accepts it and the program deadlocks under
  concurrent load. Audit for this pattern first.
- `Rc`, `RefCell`, and raw pointers held across `.await` have the same effect.
- Fix by shortening the scope. Clone or copy what you need, drop the guard,
  then `.await`. Use `tokio::sync::Mutex` only when the lock must genuinely be
  held across the `.await`.
- Never capture `&T` into a spawned task. Convert to an owned value or an
  `Arc<T>` before the `spawn`.
- Native `async fn` in traits adds no `Send` bound to the returned future. A
  call on a concrete type still spawns, because the opaque type leaks its auto
  traits. A call through a generic `T: Trait` bound does not: it prints
  `error: future cannot be sent between threads safely`. Use
  `#[trait_variant::make(TraitSend: Send)]` or keep `#[async_trait]`.
- `F: AsyncFn(&T) + Send + Sync + 'static` bounds the callable, not the future
  it returns. It does not make the callback spawnable. No stable bound names
  that future. When the callback must stay an `Fn` bound, take
  `F: for<'a> Fn(&'a T) -> Pin<Box<dyn Future<Output = R> + Send + 'a>>`
  instead. When you control the callee, a trait method that returns
  `impl Future<Output = R> + Send` carries `Send` and allocates nothing. A
  future that borrows its argument is not `'static`; move the owned argument
  into an outer spawned task and create the borrowed future inside it. See the
  pitfall catalog.

## Timeouts

`tokio::time::timeout` polls the wrapped future before it reports the elapsed
deadline. It cannot preempt one call to `Future::poll`. If that poll runs past
the deadline and returns `Ready`, `timeout` returns `Ok`. If the poll never
returns, the timeout never fires.

```rust
use std::time::Duration;

fn expensive_cpu_computation() {}

// DANGEROUS: looks protected, is not
let r = tokio::time::timeout(Duration::from_secs(1), async {
    expensive_cpu_computation()   // no .await inside
}).await;

// This bounds the wait, but the blocking closure continues after timeout.
let r = tokio::time::timeout(
    Duration::from_secs(1),
    tokio::task::spawn_blocking(|| expensive_cpu_computation()),
).await;
```

Use `spawn_blocking` so the runtime can observe the deadline. This bounds only
how long the async caller waits. It does not stop a blocking closure that has
started. Pass a `CancellationToken` into CPU work and check it between bounded
work units when the operation itself must stop after the deadline. Cancel that
token when `timeout` returns `Elapsed`.

## Manual polling from a synchronous loop

Some designs pair a synchronous, step-driven engine (a userspace protocol
stack, a simulation tick loop, a hardware poll loop) with waker-driven tokio
tasks. The two schedulers do not share a waker. The bridge is a manual
`poll_read` / `poll_write` call with a no-op waker, made from the loop tick.

Three rules govern the bridge:

1. Never call a no-op-waker poll helper from inside an async task. Under a
   no-op waker, `Poll::Pending` means "no wake will ever arrive", so the task
   stalls permanently.
2. Never add an `async fn` wrapper around such a helper. It stalls for the
   same reason.
3. `AsyncRead::poll_read` returns `Poll<Result<()>>`. A ready success with no
   growth in `ReadBuf::filled()` is EOF; map it to `UnexpectedEof` only when the
   protocol requires more bytes. `AsyncWrite::poll_write` returns a byte count:
   treat `Ok(0)` as `WriteZero`; a closed peer can also return `BrokenPipe`.

Read [references/manual-poll-bridge.md](references/manual-poll-bridge.md) for
the `NoopWaker` implementation, the full invariants, and the io_uring
registered-buffer rules.

## Stall and hang triage

| Symptom | Likely cause | Check or fix |
|---|---|---|
| Every task is slow, one task looks stuck | a blocking call inside async context | grep for `std::thread::sleep`, `std::fs`, synchronous HTTP or DB calls; move to `spawn_blocking` or a dedicated thread |
| Shutdown never completes | a `select!` loop without a `cancelled()` arm | add `biased;` + `_ = cancel.cancelled() => break` |
| Async tasks abort, but the process will not exit | `JoinSet` drop cannot abort `spawn_blocking` threads | pass a `CancellationToken` into the blocking closure and check it |
| Latency spikes with no obvious cause | blocking pool saturated by long-lived tasks | move indefinite work to `std::thread::spawn` |
| A timeout is exceeded but returns `Ok`, or never returns | one poll of the wrapped future does not yield | wrap `spawn_blocking` inside the `timeout`; add cooperative cancellation if the work itself must stop |
| Panic: "can call blocking only when running on the multi-thread runtime" | `block_in_place` on a `current_thread` runtime | use `spawn_blocking` |
| Events are missing, no error is logged | `broadcast` `Lagged` handled as a generic `Err` | match `RecvError::Lagged(n)` explicitly, or switch to `mpsc` |
| Deadlock only under concurrent load | `std::sync::Mutex` guard held across `.await` | drop the guard before the `.await`, or use `tokio::sync::Mutex` |
| A stream stalls forever after one `Pending` | a no-op-waker poll helper was called from async code | move the call into the synchronous loop tick |
| Writes succeed, the peer sees nothing | the synchronous engine did not run a step after the write | check that the loop is not skipping ticks under load |
| io_uring operations hang after cancellation | an SQE was dropped without `IORING_OP_ASYNC_CANCEL` | submit the cancel in the drop path |
| File descriptors accumulate | a missing close on an error path, or tokio below 1.51.1 | audit `OwnedFd` cleanup on every early return; raise the tokio floor |

## Observability

`tokio-console` needs the `tokio_unstable` cfg flag and the
`console-subscriber` crate. Both add build complexity and runtime overhead,
and cross-compiled or constrained targets often cannot carry them. In that
case use `tracing` spans plus `RUST_LOG` filtering. Give every long-lived task
its own span, so a stalled task is visible in the log by name. See
`rust-observability`.

## Review checklist

Check each item before you approve async code.

- [ ] Every future in a `select!`, `timeout`, or `FuturesUnordered` arm is
      annotated `cancel-safe:` or `NOT cancel-safe:` with a reason.
- [ ] Every long-lived `select!` loop has a `cancelled()` arm, and uses
      `biased;` when shutdown must win.
- [ ] A disabled `select!` branch has no synchronous side effect in its async expression.
- [ ] Every spawned task has an owner that cancels or aborts and then joins it.
- [ ] No `std::sync::Mutex` guard lives across an `.await`.
- [ ] No blocking syscall or CPU-heavy loop runs on a runtime worker thread.
- [ ] `spawn_blocking` is used only for bounded work; indefinite work uses
      `std::thread::spawn`.
- [ ] Every `broadcast` receive loop handles `RecvError::Lagged`.
- [ ] Every `block_on` that crosses an FFI boundary is wrapped in
      `catch_unwind`.
- [ ] Every duplicated file descriptor is closed on every error path.
- [ ] `cargo tree --locked -i tokio` shows a version at or above the floor.
- [ ] No `for .. { tokio::spawn(..) }` loop without a `JoinSet` or a
      concurrency bound.
- [ ] No async wrapper exists around a no-op-waker poll helper.

## Pitfall catalog

Read [references/async-pitfall-catalog.md](references/async-pitfall-catalog.md)
when you author or review code touched by any of these:

- Blocking syscalls inside `async fn`
- `select!` / `join!` semantics and cancellation surprises
- Cancel-safety annotation discipline and the library method cancel-safety table
- The spawn-and-join firewall for non-cancellable critical sections
- `CancellationToken`: child tokens, `DropGuard`, `run_until_cancelled`
- Structured concurrency status
- Async-Drop contracts of pooled resource libraries (sqlx, deadpool, `tokio::fs::File`)
- Async closures and the `AsyncFn` family (Rust 1.85+)
- HRTB pitfalls in `Fn` callbacks
- Async plus shared `&mut State` in event loops
- `Pin` necessity in FFI types
- `impl Trait` (RPIT) lifetime overcapture in edition 2024
- `tokio::time::timeout` is cooperative
- `JoinSet` drop cannot abort `spawn_blocking` threads
- `spawn_blocking` pool exhaustion
- `block_in_place` panics on `current_thread`
- `broadcast` receiver drops messages on `Lagged`
- `std::sync::Mutex` guard across `.await`
- `async fn` in traits: not `dyn`-safe, no `Send` bound

## Related skills

- `rust-callback-bounds` — `for<'a>` bounds on non-async `Fn` callbacks. This
  skill covers only the async half.
- `rust-event-loop-state` — sharing `&mut State` across concurrently polled
  futures. This skill states the rule; that one holds the design patterns.
- `rust-pin-projection` — what `Pin` enforces, and what it does not. This skill
  covers polling and cancel safety; that one covers `Unpin`, `PhantomPinned`
  and structural projection.
- `rust-panic-safety` — `catch_unwind` at task and FFI boundaries.
- `rust-unsafe` — `SAFETY:` conventions for SQE construction and `Pin`.
- `rust-jni` and `ffi-error-progress-cancel` — the foreign-thread contract.
- `rust-debugging` — debugging async stack frames.
- `rust-performance` — flamegraphs with async frames.
- `memory-model` — memory ordering in async contexts.
- `rust-observability` — `tracing` spans and log filtering.
- `rust-test-tools` — testing shutdown and cancellation under load.
