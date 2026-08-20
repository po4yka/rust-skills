# Async Pitfall Catalog

Long-form sections that support `SKILL.md`. Each section keeps a severity
rating. Read the section that matches the code you author or review.

## Table of contents

- [Blocking in async — common mistakes](#blocking-in-async--common-mistakes)
- [select! and join! pitfalls](#select-and-join-pitfalls)
- [CancellationToken: child tokens, DropGuard, run_until_cancelled](#cancellationtoken-child-tokens-dropguard-run_until_cancelled)
- [Structured concurrency status](#structured-concurrency-status)
- [Cancel-safety is an untyped invariant — annotate explicitly](#cancel-safety-is-an-untyped-invariant--annotate-explicitly)
- [Async-Drop contracts of pooled resource libraries](#async-drop-contracts-of-pooled-resource-libraries)
- [Async closures and the AsyncFn family (stable since Rust 1.85)](#async-closures-and-the-asyncfn-family-stable-since-rust-185)
- [HRTB pitfalls in Fn callbacks](#hrtb-pitfalls-in-fn-callbacks)
- [Async + shared state in event loops](#async--shared-state-in-event-loops)
- [Pin necessity in FFI](#pin-necessity-in-ffi)
- [impl Trait (RPIT) overcaptures lifetimes in edition 2024](#impl-trait-rpit-overcaptures-lifetimes-in-edition-2024)
- [tokio::time::timeout is cooperative](#tokiotimetimeout-is-cooperative--one-poll-can-exceed-the-deadline)
- [JoinSet drop cannot abort spawn_blocking threads](#joinset-drop-cannot-abort-spawn_blocking-threads--silent-shutdown-hang)
- [spawn_blocking pool exhaustion from long-lived tasks](#spawn_blocking-pool-exhaustion-from-long-lived-tasks)
- [block_in_place panics on current_thread runtime](#block_in_place-panics-on-current_thread-runtime)
- [broadcast receiver silently drops messages on Lagged](#broadcast-receiver-silently-drops-messages-on-lagged)
- [std::sync::Mutex guard across .await deadlocks silently](#stdsyncmutex-guard-across-await-deadlocks-silently)
- [async fn in traits is not dyn compatible and has no Send bound](#async-fn-in-traits-is-not-dyn-compatible-and-has-no-send-bound)

## Blocking in async — common mistakes

**Severity: CRITICAL**

```rust
use std::time::Duration;

fn heavy_cpu_work() {}

// WRONG: blocks a runtime thread, starves other tasks
async fn bad() {
    std::thread::sleep(Duration::from_secs(1));
    std::fs::read_to_string("file.txt").unwrap();
}

// CORRECT: async equivalents
async fn good() {
    tokio::time::sleep(Duration::from_secs(1)).await;
    tokio::fs::read_to_string("file.txt").await.unwrap();
}

// CORRECT: offload unavoidable blocking work
async fn with_blocking() {
    tokio::task::spawn_blocking(|| heavy_cpu_work()).await.unwrap();
}
```

A synchronous client that runs on a dedicated `std::thread`, outside the tokio
runtime, is a valid design and not a bug. Write a comment at the thread spawn
site that states the intent. Otherwise a later reader "fixes" it into async and
moves the blocking work onto a runtime worker thread.

## select! and join! pitfalls

**Severity: CRITICAL**

```rust
// select! completes when the FIRST branch finishes; LOSING branches are DROPPED.
// Their futures are cancelled -- any in-progress work is lost.
tokio::select! {
    result = fetch_a() => { /* fetch_b() dropped */ }
    result = fetch_b() => { /* fetch_a() dropped */ }
}

// Biased select: always checks branches in order. Use for priority shutdown.
loop {
    tokio::select! {
        biased;
        _ = cancel.cancelled() => break,  // always checked first
        msg = rx.recv() => process(msg),
    }
}

// join! waits for ALL to complete -- no cancellation surprise.
let (a, b) = tokio::join!(fetch_a(), fetch_b());
```

Without `biased`, `select!` polls the arms in a random order. A saturated data
arm can starve the shutdown arm.

Tokio evaluates every branch precondition first. It then evaluates every async expression,
including expressions for disabled branches. A disabled future is not polled. This distinction
matters when future construction has synchronous work:

```rust
let branch = false;
tokio::select! {
    _ = async {
        // Put side effects here. This body runs only when the future is polled.
        prepare_then_wait().await;
    }, if branch => {}
    _ = ready() => {}
}
```

Do not write `make_future_with_side_effect()` as the disabled branch expression. Its call runs
before Tokio decides which futures to poll.

Dropping a `tokio::task::JoinHandle` detaches the task. The task continues and its result or
panic can be lost. A task owner must keep the handle, request cooperative cancellation, and
await the handle. Use `abort()` only when abrupt cancellation is valid, then await the handle so
shutdown observes the task exit.

## CancellationToken: child tokens, DropGuard, run_until_cancelled

**Severity: WARNING**

`tokio_util::sync::CancellationToken` exposes three idioms beyond
`.cancelled().await`. Use them for structured concurrency.

**Child tokens — a parent cancels its children, but a child does not cancel
its parent.**

```rust
// Parent owns the master token. Each spawned unit of work holds a child token.
let master = CancellationToken::new();
for job_id in jobs {
    let child = master.child_token();
    tokio::spawn(async move {
        run_job(job_id, child).await
    });
}
// Later: master.cancel() — propagates to every child.
// A single child can fail without taking down its siblings:
//   child.cancel() inside one task affects only that task.
```

Use for: per-unit lifetimes inside a long-lived runtime. The parent token
cancels every unit on shutdown. One unit's failure does not cancel siblings.

**DropGuard — cancellation on an RAII boundary.**

```rust
use tokio_util::sync::CancellationToken;

let token = CancellationToken::new();
let _guard = token.clone().drop_guard();
// ... do work, possibly with early returns / ? ...
// When _guard drops (early return, panic, end of scope), the token is
// cancelled automatically. Spawned tasks that hold `token.clone()` observe it.
```

Use for: bounded async operations where cancellation must fire on any early
exit. It replaces hand-written `defer!`-style cleanup at each `?`.

**`run_until_cancelled` — race a future against cancellation and keep the
future's value.**

```rust
use tokio_util::sync::CancellationToken;

let token = parent.child_token();
match token.run_until_cancelled(do_work()).await {
    Some(value) => process(value),           // do_work completed
    None        => tracing::info!("cancelled"), // cancellation fired first
}
```

It is equivalent to
`tokio::select! { v = do_work() => Some(v), _ = token.cancelled() => None }`,
but it reads better. It does not remove the `select!` arm-cancellation footgun:
the losing branch is still dropped, so confirm that `do_work` is cancel-safe
before you use it.

## Structured concurrency status

**Severity: INFO**

Rust has no first-class structured concurrency. The community RFC
(tokio-rs/tokio#1879, tokio-uring#81) is open. Until it lands,
`CancellationToken` + `JoinSet` is the canonical pattern.

- **`JoinSet`** owns a set of spawned tasks. `join_next().await` returns the
  next completed result. `abort_all()` aborts all tasks. Dropping the `JoinSet`
  aborts all tasks and does NOT wait for them — see the
  `JoinSet drop cannot abort spawn_blocking` rule below.
- Pair `JoinSet` with a parent `CancellationToken` and one `child_token()` per
  task, so you have graceful cancellation in addition to abrupt abort.
- **`FuturesUnordered`** polls a set of futures in place, without spawning. It
  is a cancellation context like `select!`: a future removed from the set is
  dropped mid-flight, so every future you put in it must be cancel-safe.
- For task supervision (restart on failure), do not roll your own. Use a
  supervised pool crate (`tokio_graceful`, `async-stream` patterns) and
  document the policy.

Rule: any `for x in xs { tokio::spawn(work(x)); }` loop with N > 1 is a
refactor candidate. Use `JoinSet::spawn` + `join_next`, or
`futures::future::join_all` for a bounded small N, or
`futures::stream::iter(...).buffer_unordered(K)` for bounded concurrency over
a stream.

## Cancel-safety is an untyped invariant — annotate explicitly

**Severity: CRITICAL when used inside `select!` / `timeout` /
`FuturesUnordered`**

A future is **cancel-safe** if and only if dropping it between any two
`.await` points leaves observable state consistent. No signature expresses the
property. `async fn f(...)` looks identical whether `f` is safe to cancel
between its internal `.await`s or not. The borrow checker and clippy do not
help. The information lives in the caller context (whether the future ends up
in `tokio::select!`, `tokio::time::timeout`, or `FuturesUnordered`) plus
library documentation that you must read per method.

### Annotation discipline

Every `async fn` that may transitively be polled inside `select!` / `timeout` /
`FuturesUnordered` MUST carry a doc comment of this form:

```rust
use tokio::net::TcpStream;

struct Request;
struct Connection;

impl Connection {
    /// cancel-safe: only `.await`s on `read` and `mpsc::recv`, both individually cancel-safe.
    async fn read_request(&mut self) -> Result<Request> { todo!() }

    /// NOT cancel-safe: `db.insert().await` followed by `send_ack().await` —
    /// cancellation between them leaves the DB written but the client unacked.
    async fn process(&self, stream: TcpStream) -> Result<()> { todo!() }
}
```

Rule: prefix the comment with `cancel-safe:` or `NOT cancel-safe:` and give a
reason. "cancel-safe because idempotent" is not acceptable. Idempotence is a
property of the OPERATION; cancel-safety is a property of the SCHEDULING. Both
must hold independently.

### Library method cancel-safety table

Memorize this table. The documentation entries are easy to miss.

| Method | Cancel-safe? | Why |
|--------|--------------|-----|
| `AsyncReadExt::read` | Yes | Single syscall; on cancellation, no bytes consumed. |
| `AsyncReadExt::read_exact` | **No** | May consume some bytes before cancellation; the caller loses them. |
| `AsyncWriteExt::write` | Yes | Single syscall. |
| `AsyncWriteExt::write_all` | **No** | Same partial-write hazard. |
| `tokio::sync::Mutex::lock` | **No for queue position** | The mutex is fair. Cancellation removes the waiter, so retrying loses its FIFO place. No lock is leaked. |
| `tokio::sync::oneshot::Receiver` | Yes | Single state transition. |
| `tokio::sync::mpsc::Receiver::recv` | Yes | Documented cancel-safe. |
| `tokio::sync::Notify::notified` | **Conditional** | Must be awaited via `Pin<&mut>` to be cancel-safe; a bare `.notified().await` re-arms on each call. |
| `tokio::time::sleep` | Yes | Cancellation just drops the timer. |
| `sqlx::Transaction::commit` | **No** | Drop after a partial commit queues a silent rollback; nothing reports the failure. |
| `sqlx::QueryAs::fetch_one` | Conditional | Cancel-safe if the connection is dropped (released to the pool); not if it is reused. |
| `reqwest::RequestBuilder::send` | **No** | The body may be partially sent. |

### Spawn-and-join firewall for non-cancellable critical sections

When a sequence of `.await`s must complete atomically with respect to
cancellation, lift it into a spawned task and join the handle:

```rust
async fn process(stream: TcpStream, db: Arc<Db>) -> Result<()> {
    let data = read_message(&stream).await?;
    // From here on, cancellation of `process()` must NOT abort the work.
    let handle = tokio::spawn(async move {
        db.insert(&data).await?;
        send_ack(&stream).await?;
        Ok::<_, Error>(())
    });
    handle.await?  // outer cancellation cancels the join, not the spawned work.
}
```

This trades cooperative cancellation for atomicity. The spawned task runs to
completion even if the caller is dropped. Use it only when the alternative
(data loss or inconsistent state) is worse. Pair it with a
`tokio::time::timeout` inside the spawned task if unbounded run time is itself
a hazard.

## Async-Drop contracts of pooled resource libraries

**Severity: WARNING**

Async types whose `Drop` performs cleanup (transactions, connections, file
handles) have library-specific behavior that is NOT visible in their
signatures. Code that uses the API correctly can still miss the `Drop`
semantics. Read the `Drop` impl before you rely on it.

### sqlx transactions

Read against sqlx 0.7.4, 0.8.6 and 0.9.0. The `Drop` body is the same in all three.

```rust
let tx = conn.begin().await?;
// ... operations ...
tx.commit().await?;  // Consumes `tx`; an error can leave the durable outcome unknown.
```

`Transaction::drop` calls `TransactionManager::start_rollback`, a non-async
function that queues a ROLLBACK on the connection. Nothing blocks in `drop`.
The rollback runs on the next async use of that connection, which includes the
moment the pool recycles it. This cleans up a transaction that the driver still
considers open. It does not prove that a failed `commit` was absent from the
database. For example, the database can commit and the connection can fail
before the acknowledgement reaches the client.

`Transaction::commit(self)` consumes the transaction. After it returns `Err`,
there is no `tx` value on which to call `rollback`; an example that tries does
not compile. Roll back explicitly only while you still own the transaction,
such as after the work step fails:

```rust
let value = match work(&mut tx).await {
    Ok(value) => value,
    Err(e) => {
        let _ = tx.rollback().await;
        return Err(e);
    }
};

// `commit` consumes `tx`. Propagate failure; do not attempt a second rollback.
tx.commit().await?;
Ok(value)
```

A commit transport or protocol error can leave the database outcome unknown.
The queued rollback is local connection cleanup, not evidence that the commit
did not happen. Do not retry blindly. Make the operation idempotent or reconcile
its durable state with a new connection.

### deadpool connections

Read against deadpool 0.13.0. `Object::drop` pushes the connection back into
the pool slot list and adds a permit. It is fully synchronous and it runs no
health check. `Manager::recycle`, the `pre_recycle` hook and the `post_recycle`
hook all run inside the next `Pool::get().await`, not at drop time.

Consequence: a connection returned by `Drop` during shutdown keeps whatever
state the last query left on it. Nothing validates it, and if the process exits
before another `get()`, `recycle` never runs at all.

Rule: in shutdown paths take the object out of the pool with
`Object::take(obj)`, which detaches it, and close it yourself. Do not expect
`Drop` to run any hook.

### tokio::fs::File

Read against tokio 1.53.1. `File` has no `Drop` impl at all. It holds
`Arc<std::fs::File>`, so the fd closes when the last handle to that `Arc`
drops. A write started by `poll_write` runs on the blocking pool and holds a
clone until it ends, so the close waits for it. With no operation in flight the
close syscall runs inline, on the thread that drops the file.

The data is not lost, but the write error is. A failed background write lands
in `last_write_err`, and that field is read by the next `write`, `flush` or
`seek` call. A drop makes that call never happen.

Rule: `file.flush().await?` before you drop a file you wrote to. Add
`file.sync_all().await?` when the bytes must reach the disk.

### General audit

For every `Drop` on an async resource type:

1. Read the library source for `impl Drop`. Does it block, spawn, queue the
   work for a later call, or no-op? A missing `Drop` impl is also an answer.
2. If it blocks: run cleanup through an explicit `.commit()` / `.rollback()` /
   `.close()` before the drop.
3. If it spawns or queues: cleanup is fire-and-forget, and it reports no error.
   Verify the behavior under runtime shutdown.
4. Document the choice in a comment on the variable binding, for example
   `// drop here: deferred rollback acceptable in error path`.

## Async closures and the `AsyncFn` family (stable since Rust 1.85)

**Severity: INFO — replaces several long-standing workarounds**

Rust 1.85 (February 2025, RFC 3668) stabilized `async ||` closures and the
`AsyncFn` / `AsyncFnMut` / `AsyncFnOnce` trait family. `AsyncFn(&T)` replaces
the boxed higher-ranked shape. It uses no box and no allocation. `async ||`
infers the borrow of a captured value.

PREFERRED, Rust 1.85 and later: `F: AsyncFn(&str) -> R`, called with
`async |s: &str| do_work(s).await`.

LEGACY, any stable release:
`F: for<'a> Fn(&'a str) -> Pin<Box<dyn Future<Output = R> + 'a>>`, called with
`|s| Box::pin(do_work(s))`. One `Fut` type parameter cannot express the borrow,
so the future needs a box. The next subsection compiles both shapes and shows
the diagnostic that forces the choice.

Rules, once the crate MSRV is at 1.85 or above:

1. For new higher-ranked async bounds, prefer `F: AsyncFn(Args) -> T` over
   `F: Fn(Args) -> impl Future`, as long as the future stays on the caller's
   task. It does not survive a `tokio::spawn`; see the next two subsections.
2. Do NOT mass-rewrite existing `|x| async move { ... }` into `async |x|` in
   unrelated diffs. Migrate site by site when you touch the callback site for
   another reason. Premature churn obscures `git blame`.
3. The non-async half of the HRTB rules lives in `rust-callback-bounds`. Read
   it before you write any `for<'a>` bound on a plain `Fn` callback.

An async closure always captures its input arguments because the returned future can use them.
This differs from an ordinary closure that does not capture an unused input. An async closure is
also lending when the future borrows a capture or when a by-value capture is read without a
dereference. A lending async closure does not implement `Fn` or `FnMut`; it can implement only
`FnOnce`. Do not add clones until a type probe proves which call trait the exact closure needs.

### A single `Fut` parameter rejects every borrowing `async fn`

`fn f<Fut: Future>(cb: impl Fn(&T) -> Fut)` accepts no `async fn` that borrows
its argument. `async fn handle(r: &Request)` returns a different opaque type per
region, and a single `Fut` parameter is chosen once, outside the `for<'a>`
binder. Recognise the diagnostic:

```text
error[E0308]: mismatched types
  |
6 | fn main() { add_reactor(handle); }
  |             ^^^^^^^^^^^^^^^^^^^ one type is more general than the other
  |
  = note: expected opaque type `impl for<'a> Future<Output = ()>`
             found opaque type `impl Future<Output = ()>`
  = note: distinct uses of `impl Trait` result in different opaque types
```

Two bounds accept it. Pick by whether the future must cross a task boundary:

```rust
use std::future::Future;
use std::pin::Pin;

struct Request { body: String }
async fn handle(r: &Request) { let _ = &r.body; }

// FIX A, Rust 1.85 and later: the future stays local to the caller.
fn reactor_local(_f: impl AsyncFn(&Request)) {}

// FIX B, any stable release: an `Fn` bound that also carries `Send`.
fn reactor_spawnable(
    _f: impl for<'a> Fn(&'a Request) -> Pin<Box<dyn Future<Output = ()> + Send + 'a>>,
) {}

fn main() {
    reactor_local(handle);
    reactor_local(async |r: &Request| { let _ = &r.body; });
    reactor_spawnable(|r| Box::pin(handle(r)));
}
```

Write `Pin<Box<dyn Future<..> + 'a>>`, never a bare `Box<dyn Future<..> + 'a>`.
`Box<F>` implements `Future` only for `F: Unpin`, and `dyn Future` is not
`Unpin`, so the bare form type-checks and then fails at the `.await` with
``error[E0277]: `dyn Future<Output = ()>` cannot be unpinned``.

### `AsyncFn` carries no `Send` bound to the future

`F: AsyncFn(&T) + Send + Sync + 'static` does NOT make the future that `F`
returns `Send`. Those bounds constrain the callable, not its output. The
callback still fails to spawn. `tokio::spawn` prints an unnumbered error:

```text
error: future cannot be sent between threads safely
   |     tokio::spawn(async move { f(&req).await; });
   |     ^^^ future created by async block is not `Send`
   = help: within `{async block@src/main.rs:6:18: 6:28}`, the trait `Send` is
           not implemented for `<F as AsyncFnMut<(&Request,)>>::CallRefFuture<'_>`
note: required by a bound in `tokio::spawn`
```

A plain `T: Send` bound applied to the returned future prints the numbered form
of the same fact:

```text
error[E0277]: `<F as AsyncFnMut<(&Request,)>>::CallRefFuture<'_>` cannot be sent
              between threads safely
  = help: the trait `Send` is not implemented for
          `<F as AsyncFnMut<(&Request,)>>::CallRefFuture<'_>`
```

The returned future is `<F as AsyncFnMut<(&'a T,)>>::CallRefFuture<'a>`, an
associated type of the unstable `async_fn_traits`. You cannot name it on
stable, so you cannot write `for<'a> F::CallRefFuture<'a>: Send`. There is no
stable way to bound the future of an `AsyncFn`.

Rule: when the future must cross `tokio::spawn` and the callback must stay an
`Fn` bound, take FIX B above —
`F: for<'a> Fn(&'a T) -> Pin<Box<dyn Future<Output = R> + Send + 'a>>`. One
`Box::pin` per call is the price. Use `AsyncFn` everywhere else.

When you control the callee's shape, a trait method that returns
`impl Future<Output = R> + Send` (RPITIT, stable since 1.75) carries `Send` and
allocates nothing. It does not add `'static`. A future that borrows its argument
cannot be passed directly to `tokio::spawn`:

```rust
use std::future::Future;
use std::sync::Arc;

struct Request { body: String }

trait Handler: Send + Sync + 'static {
    fn call(&self, r: &Request) -> impl Future<Output = usize> + Send;
}

struct Len;
impl Handler for Len {
    async fn call(&self, r: &Request) -> usize { r.body.len() }
}

fn spawn_call(
    handler: Arc<impl Handler>,
    request: Request,
) -> tokio::task::JoinHandle<usize> {
    tokio::spawn(async move {
        // The outer task owns both values. Create the borrowed future here.
        handler.call(&request).await
    })
}
```

`tokio::spawn(handler.call(&request))` fails because both borrows are local and
the spawned future must be `'static`. Move owned values or `Arc` handles into an
outer `async move` block. Then create and await the borrowed RPITIT future
inside that block.

`#[trait_variant::make(TraitSend: Send)]` generates the same shape from an
`async fn` in a trait. Reach for FIX B only when the bound must accept an
arbitrary closure.

Reference:
[RFC 3668](https://github.com/rust-lang/rfcs/blob/master/text/3668-async-closures.md),
Rust 1.85 release notes.

## HRTB pitfalls in `Fn` callbacks

**Severity: WARNING**

Higher-Ranked Trait Bounds (HRTBs) — `for<'a> FnMut(&'a T) -> K` — are the
correct shape for callbacks that take a reference and return something that
must not outlive the reference.

**A dependent output is expressible. Do not box it.** An output type that names
the higher-ranked lifetime, such as `&'a K`, is legal in `Fn` sugar. Only a
*separate* generic parameter cannot depend on `'a`. Never reach for
`Box<dyn for<'a> Fn(&'a T) -> &'a K>`, a GAT, or a macro crate to work around
this shape.

`rust-callback-bounds` owns this rule. It holds the worked example, the
`K: ?Sized` bound that every `-> &'a K` row needs, the full decision table for
non-async callback bounds, and the cases where a closure does need an
annotation. Read it first. The rest of this section covers only the async part.

**Async `Fn` bounds.** Use `F: AsyncFn(&T) -> R` when the future stays on the
caller's task. Use `F: for<'a> Fn(&'a T) -> Pin<Box<dyn Future<Output = R> +
Send + 'a>>` when it crosses `tokio::spawn`. See "Async closures and the
`AsyncFn` family" above for the two diagnostics that tell the cases apart.

When callbacks cross a thread boundary into `tokio::spawn`, every captured
closure must be `'static + Send`. Do not capture `&T`. Convert to an owned
value or an `Arc<T>` before the spawn. `Send` on the closure does not reach the
future the closure returns.

## Async + shared state in event loops

**Severity: WARNING**

A captured `&mut State` inside an async block lives for the whole lifetime of
the `Future`, from the first poll to completion. Two concurrent futures
therefore cannot both hold `&mut State`:

```rust
// DOES NOT COMPILE: two mutable borrows of `state` active at once
let f1 = async { state.handle_event(ev1) };
let f2 = async { state.handle_event(ev2) };
tokio::join!(f1, f2); // error[E0499]
```

Correct approaches, in order of preference:

1. **Split the state by field at the call site.** Two concurrently polled
   futures CAN share one state struct. The borrow a future captures is the
   borrow made at the call site, and disjoint field borrows stay disjoint
   inside futures. Try this before any channel, lock, or `RefCell`.

   ```rust
   struct State { seen: u32, out: Vec<u32> }

   async fn bump(n: &mut u32) { *n += 1; }
   async fn record(v: &mut Vec<u32>) { v.push(1); }

   let mut state = State { seen: 0, out: Vec::new() };
   // Two disjoint field borrows, both futures polled concurrently.
   tokio::join!(bump(&mut state.seen), record(&mut state.out));
   assert_eq!(state.seen, 1);
   ```

   It fails only when both futures need the same field, or when either takes
   `&mut State` whole. `tokio::join!(f(&mut st), f(&mut st))` is E0499 whatever
   the fields are.
2. **Single-task ownership.** One task owns `State`. Every other task
   communicates with it through `mpsc` channels. No sharing is needed. Prefer
   this on any hot path.
3. **`Arc<Mutex<State>>`.** Correct, but it serializes access. Acceptable for
   low-contention configuration state. Unacceptable on a per-packet or
   per-frame path.
4. **`RefCell<State>` inside a `!Send` single-threaded runtime.** Valid only on
   a `current_thread` runtime.

Four routes look like they hand `&mut State` to a future. None of them works.
Do not plan a design around them. Two are runtime plumbing:

| Route | What actually happens |
|---|---|
| `Context::ext` (nightly, `feature(context_ext)`) | It carries a value only when the *executor* builds the `Context` with `ContextBuilder::ext()`. tokio uses `Context::from_waker`, which sets the slot to `&mut ()`. Inside a tokio task every `cx.ext().downcast_mut::<State>()` returns `None`, with no error and no warning. Usable only inside an executor you wrote yourself. |
| `Waker::data()` smuggling (stable) | `tokio::join!`, `select!` and `timeout` forward the task waker unchanged, so a round-trip through `cx.waker().data()` appears to work. `FuturesUnordered` — and `buffer_unordered` and `for_each_concurrent`, which are built on it — installs its own waker, so you read a pointer that belongs to the combinator. The cast compiles either way. |

The other two are language features. `#[coroutine]` closures with
`resume(&mut State)` and the stable generator crates cannot carry a
`&mut State` resume argument either. `rust-event-loop-state`, section "The
three escapes, and why none works", holds both diagnostics and the design
patterns that follow from this rule.

## `Pin` necessity in FFI

**Severity: WARNING for self-referential or FFI types**

`Pin<&mut T>` restricts `T` only when `T` is `!Unpin`. On an `Unpin` target
`Pin::new`, `Pin::get_mut` and `DerefMut` are all safe, so the pin enforces
nothing. `rust-pin-projection` owns `Pin`, `Unpin`, `PhantomPinned` and
structural projection into a field. This section covers only why an FFI or
self-referential type needs a pin at all. You need it for:

- Self-referential structs, where a field holds a pointer to another field of
  the same struct. This is the default use of `Pin` in async state machines.
- FFI types that must not move after construction, because C++ objects have
  non-trivial move constructors that Rust cannot call.

`cxx`-generated bindings expose C++ types as `Pin<&mut CppType>`. Use that
generated contract as documented by `cxx`. Do not generalize it to an opaque
pointer that a C library allocates. `Pin<Box<T>>` claims that Rust owns a `T`
allocation and must free it with the Rust allocator. That is false for a
C-owned allocation.

Store a C-owned handle as `NonNull<Opaque>`. Call the matching C destructor in
`Drop`. Moving the Rust wrapper does not move the C allocation:

```rust
use std::ptr::NonNull;

#[repr(C)]
pub struct OpaqueHandle {
    _private: [u8; 0],
}

unsafe extern "C" {
    fn handle_destroy(handle: *mut OpaqueHandle);
}

pub struct OwnedHandle {
    ptr: NonNull<OpaqueHandle>,
}

impl OwnedHandle {
    /// # Safety
    /// For a non-null `ptr`, the caller must transfer exclusive ownership of a
    /// live handle from the matching C constructor. No second owner or wrapper
    /// may exist. Foreign code must not destroy the handle or retain an access
    /// that can outlive this wrapper.
    pub unsafe fn from_raw(ptr: *mut OpaqueHandle) -> Option<Self> {
        NonNull::new(ptr).map(|ptr| Self { ptr })
    }
}

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        // SAFETY: `from_raw` transfers the only ownership claim to this value.
        // Drop runs once, after all mediated foreign accesses have ended.
        unsafe { handle_destroy(self.ptr.as_ptr()) };
    }
}
```

Expose foreign operations as methods that borrow `OwnedHandle`. Do not expose a
second owning constructor. If C retains the pointer after a method returns, add
an explicit unregister-and-join step before `Drop` can run.

Do not add `Send` or `Sync` unless the C API documents the same thread-safety
contract. Use `Pin` only for Rust-owned values whose address-stability contract
requires it, or when the generated binding API requires a pinned reference.

Rules:

- Every `async fn` and every `async {}` future is `!Unpin`, whatever the body
  holds. There is no per-body analysis: even `async fn trivial() -> u32 { 1 }`
  fails `assert_unpin` with ``error[E0277]: `{async fn body of trivial()}`
  cannot be unpinned``. A generic helper that polls a caller-supplied future
  must therefore take `Pin<&mut F>`. An `F: Unpin` bound forces every caller
  through `Box::pin` or `std::pin::pin!` instead.
- Never write a self-referential struct without `Pin` + `PhantomPinned`.
- Never store a raw pointer to a stack variable and then move the variable.
- `Box::pin(val)` is the easiest way to heap-pin a value.
- After pinning, use `Pin::get_unchecked_mut` only with a
  `// SAFETY: we never move T after this point` comment.

## `impl Trait` (RPIT) overcaptures lifetimes in edition 2024

**Severity: WARNING — edition migration hazard**

In Rust 2021 and earlier, return-position `impl Trait` (RPIT) did NOT
implicitly capture lifetime parameters unless you listed them. In Rust 2024,
all in-scope lifetimes are captured automatically. Consequence: a function that
was `'static`-compatible in edition 2021 may become non-`'static` after
migration, because the return type now captures a lifetime from an input
reference.

Concrete symptom: a function that returned `impl Future + 'static` and takes
`&self` now infers `impl Future + '_`. Every `tokio::spawn(obj.method())` call
site breaks.

Fix: use precise `use<..>` syntax (stabilized in Rust 1.82) to state exactly
which lifetimes and type parameters the opaque type captures.

`use<>` with an empty list captures nothing, so it only compiles when the body
genuinely holds no borrow. A future that keeps a reference must name the
lifetime, and it is then not `'static`:

```rust
// The future holds `data`, so it captures 'a. It cannot be spawned.
fn borrows<'a>(data: &'a str) -> impl Future<Output = usize> + use<'a> {
    async move { data.len() }
}
```

To get a `'static` future back, remove the borrow rather than the capture. Take
ownership, and `use<>` then holds:

```rust
// Captures nothing, so the future is 'static and `tokio::spawn` accepts it.
fn owns(data: String) -> impl Future<Output = usize> + use<> {
    async move { data.len() }
}
```

Writing `use<>` on the borrowing form does not make it `'static`; it fails with
`E0700: hidden type ... captures lifetime that does not appear in bounds`. The
lifetime is a property of what the body holds, and the capture list only
declares it.

The `impl_trait_overcaptures` lint (part of the `rust-2024-compatibility`
group) flags affected sites before migration. Run `cargo fix --edition` and
inspect every RPIT diff carefully.

Reference:
[Rust Blog: impl Trait capture rules](https://blog.rust-lang.org/2024/09/05/impl-trait-capture-rules/),
Edition Guide RPIT section.

## `tokio::time::timeout` is cooperative — one poll can exceed the deadline

**Severity: CRITICAL**

`tokio::time::timeout` polls the wrapped future before it reports the elapsed
deadline. It cannot preempt one call to `Future::poll`. A tight CPU loop,
blocking syscall, or heavy synchronous computation can run past the deadline.
If that poll then returns `Ready`, `timeout` returns `Ok`. If the poll never
returns, the timeout never fires.

```rust
use std::time::Duration;

fn expensive_cpu_computation() {}

// DANGEROUS: looks protected but is not
let result = tokio::time::timeout(
    Duration::from_secs(1),
    async {
        // One poll can exceed the deadline and still return Ok.
        expensive_cpu_computation()
    }
).await;
```

Move blocking or CPU-heavy work into `spawn_blocking` before you wrap it with
`timeout`. This makes the deadline observable, but it bounds only the caller's
wait. A blocking closure that has started continues after the timeout unless
the closure cooperates with cancellation:

```rust
use std::time::Duration;
use tokio_util::sync::CancellationToken;

fn expensive_cpu_computation(cancel: &CancellationToken) {
    while !cancel.is_cancelled() {
        if do_one_bounded_work_unit() {
            break;
        }
    }
}

fn do_one_bounded_work_unit() -> bool { todo!() }

let cancel = CancellationToken::new();
let worker_cancel = cancel.clone();
let result = tokio::time::timeout(
    Duration::from_secs(1),
    tokio::task::spawn_blocking(move || expensive_cpu_computation(&worker_cancel)),
).await;
if result.is_err() {
    cancel.cancel();
}
```

Apply this to every CPU-heavy classification, parsing, compression,
fingerprinting, or crypto path. Choose a work-unit size that meets the written
cancellation-latency budget. Do not describe the operation as time-bounded
unless the blocking function checks the token.

## `JoinSet` drop cannot abort `spawn_blocking` threads — silent shutdown hang

**Severity: WARNING**

When a `JoinSet` is dropped, it calls `.abort()` on every tracked future.
Tasks spawned through `spawn_blocking` run on OS threads, and tokio documents
that `abort` cannot cancel them. If a `JoinSet` holds handles to async tasks
that internally delegate to `spawn_blocking` — common in database pool workers,
file I/O wrappers, and heavy computation — then dropping the `JoinSet` during
shutdown does not stop the underlying threads.

In practice the process appears to shut down, because the async tasks receive
the abort, but OS threads keep running to completion. They can block process
exit or cause `Runtime::shutdown_timeout` to fire.

Fix: for tasks that use `spawn_blocking` internally, signal cancellation
explicitly. Pass a `CancellationToken` into the blocking closure and check it
between work units. Do not rely on `JoinSet` abort. Test shutdown under load,
not only on a happy-path sequential test.

## `spawn_blocking` pool exhaustion from long-lived tasks

**Severity: WARNING**

Tokio's blocking thread pool has a default cap of 512 threads. Each
`spawn_blocking` call occupies one thread until the closure completes.
Long-running or indefinitely polling tasks — file watchers, polling loops,
persistent connections — exhaust the pool. When the pool is saturated, new
`spawn_blocking` calls queue. The symptom is a latency spike that looks like an
async slowdown with no obvious cause.

Decision rule:

- **`spawn_blocking`**: bounded CPU work (target < 100 ms), occasional blocking
  syscalls, short file I/O.
- **`std::thread::spawn`**: indefinite blocking work, event loops, long-lived
  watchers.

Any new persistent blocking work MUST use a dedicated thread, not
`spawn_blocking`.

## `block_in_place` panics on `current_thread` runtime

**Severity: WARNING**

`tokio::task::block_in_place` migrates the current worker thread to the
blocking pool and redistributes other tasks to the remaining workers. Two
hazards exist.

1. **It panics on a `current_thread` runtime.** `#[tokio::test]` uses
   `current_thread` by default. A call to `block_in_place` inside such a test
   panics with "can call blocking only when running on the multi-thread
   runtime". Production code that uses `block_in_place` therefore produces
   confusing test failures.
2. **It starves `join!` branches.** Inside a `join!`, the other branches run on
   the same task. `block_in_place` suspends them for the duration of the
   blocking call, which causes unexpected sequencing: branch A completes, and
   branch B runs only afterwards.

Fix: use `spawn_blocking` instead of `block_in_place` in both cases. It is safe
on every runtime flavor and it does not affect co-located tasks.

## `broadcast` receiver silently drops messages on `Lagged`

**Severity: WARNING**

`tokio::sync::broadcast` channels have a fixed ring-buffer capacity. A slow
receiver that falls behind has its old messages overwritten. The next `recv()`
call returns `Err(RecvError::Lagged(n))`. Most code handles only the `Ok(msg)`
arm and treats `Lagged` as a transient error, so it silently drops `n` events.

```rust
// BUG: Lagged silently discarded
while let Ok(msg) = rx.recv().await {
    process(msg);
}

// CORRECT: handle Lagged explicitly
loop {
    match rx.recv().await {
        Ok(msg) => process(msg),
        Err(RecvError::Lagged(n)) => {
            tracing::warn!("broadcast: dropped {} messages", n);
            // decide: continue, alert, or reconnect
        }
        Err(RecvError::Closed) => break,
    }
}
```

For audit logs, metrics, or state-machine transition messages, a `Lagged` drop
is data loss. Use `mpsc` with explicit backpressure for lossless delivery.

## `std::sync::Mutex` guard across `.await` deadlocks silently

**Severity: CRITICAL**

`std::sync::Mutex` guards do not implement `Send`. The compiler rejects them in
`tokio::spawn` futures, which require `Send`. In a `current_thread` executor,
or inside a non-`Send` future, the compiler accepts a guard that crosses an
`.await` point. At runtime, if the executor schedules another task that
acquires the same lock, the program deadlocks: the async task is suspended
while it holds the lock, and the other task blocks on it.

This pattern works in development, under sequential load with a single task,
and deadlocks only under concurrent production load.

```rust
// DEADLOCK risk: guard lives across .await
let guard = mutex.lock().unwrap();
some_async_op().await;  // another task may try to lock here
drop(guard);

// CORRECT: drop before .await
let value = {
    let guard = mutex.lock().unwrap();
    guard.value.clone()
};
some_async_op().await;
```

Rule: if a `Mutex` guard must genuinely live across an `.await`, use
`tokio::sync::Mutex`. If it does not need to, drop the guard explicitly before
any `.await`.

## `async fn` in traits is not dyn compatible and has no `Send` bound

**Severity: WARNING**

`async fn` in traits was stabilized in Rust 1.75 (RPITIT). Three non-obvious
hazards appear when you replace `#[async_trait]`.

1. **Not dyn compatible.** A trait that contains `async fn` cannot be used as
   `dyn Trait`. Code that used `Box<dyn MyTrait>` — which worked under
   `#[async_trait]`, because that macro boxes the futures internally — breaks
   at compile time with `E0038`. Older releases called this check "object
   safety"; current rustc prints "is not dyn compatible", so a search for
   "object safe" in the build log finds nothing.
2. **No automatic `Send` bound.** A native `async fn` in a trait does not add
   `Send` to the returned future. `tokio::spawn(obj.method())` fails, because
   the future is not `Send`.
3. **Fix for both.** Use `#[trait_variant::make(MyTraitSend: Send)]` from the
   `trait-variant` crate to generate a `Send`-compatible trait variant:

```rust
#[trait_variant::make(MyTraitSend: Send)]
pub trait MyTrait {
    async fn process(&self, input: &str) -> Result<String>;
}
// Now use `MyTraitSend` for tokio::spawn contexts
```

Any trait with `async fn` methods used in `tokio::spawn` contexts MUST use
`trait_variant` or keep `#[async_trait]`. Do not mass-replace `#[async_trait]`
without an audit of every `Box<dyn>` and every `tokio::spawn` use site.
