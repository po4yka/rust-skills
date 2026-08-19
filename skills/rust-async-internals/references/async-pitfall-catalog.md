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
- [tokio::time::timeout is cooperative](#tokiotimetimeout-is-cooperative--never-fires-on-non-yielding-futures)
- [JoinSet drop cannot abort spawn_blocking threads](#joinset-drop-cannot-abort-spawn_blocking-threads--silent-shutdown-hang)
- [spawn_blocking pool exhaustion from long-lived tasks](#spawn_blocking-pool-exhaustion-from-long-lived-tasks)
- [block_in_place panics on current_thread runtime](#block_in_place-panics-on-current_thread-runtime)
- [broadcast receiver silently drops messages on Lagged](#broadcast-receiver-silently-drops-messages-on-lagged)
- [std::sync::Mutex guard across .await deadlocks silently](#stdsyncmutex-guard-across-await-deadlocks-silently)
- [async fn in traits is not dyn compatible and has no Send bound](#async-fn-in-traits-is-not-dyn-compatible-and-has-no-send-bound)

## Blocking in async — common mistakes

**Severity: CRITICAL**

```rust
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
/// cancel-safe: only `.await`s on `read` and `mpsc::recv`, both individually cancel-safe.
async fn read_request(&mut self) -> Result<Request> { todo!() }

/// NOT cancel-safe: `db.insert().await` followed by `send_ack().await` —
/// cancellation between them leaves the DB written but the client unacked.
async fn process(&self, stream: TcpStream) -> Result<()> { todo!() }
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
| `tokio::sync::Mutex::lock` | Yes | Acquisition is the only state change; cancellation releases the wait. |
| `tokio::sync::oneshot::Receiver` | Yes | Single state transition. |
| `tokio::sync::mpsc::Receiver::recv` | Yes | Documented cancel-safe. |
| `tokio::sync::Notify::notified` | **Conditional** | Must be awaited via `Pin<&mut>` to be cancel-safe; a bare `.notified().await` re-arms on each call. |
| `tokio::time::sleep` | Yes | Cancellation just drops the timer. |
| `sqlx::Transaction::commit` | **No** | Drop on a partial commit triggers an implicit blocking rollback. |
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

### sqlx 0.7 transactions

```rust
let tx = conn.begin().await?;
// ... operations ...
tx.commit().await?;  // If THIS fails, tx is dropped with no rollback decision made.
```

`Transaction`'s `Drop` impl issues an implicit ROLLBACK through a **blocking
syscall** on the connection. Inside a tokio multi-thread runtime this surfaces
as a `WARN`-level "blocking call in async context" log from the runtime's
blocking detector. Inside a `current_thread` runtime, or under heavy load, it
blocks a worker thread until the rollback completes. The symptom is a random
latency spike.

Rule: never let a sqlx `Transaction` drop after a failed `commit().await`.
Convert to an explicit rollback:

```rust
match work(&mut tx).await {
    Ok(v) => match tx.commit().await {
        Ok(()) => Ok(v),
        Err(e) => {
            // commit failed; Drop would do a blocking rollback. Pre-empt it.
            let _ = tx.rollback().await;
            Err(e.into())
        }
    },
    Err(e) => {
        let _ = tx.rollback().await;
        Err(e)
    }
}
```

### deadpool connections

`Object<Manager>::drop` returns the connection to the pool. If the pool's
recycle hook performs an async health check, the recycle is enqueued on a
background task, which may not run if the runtime is shutting down. The
connection then leaks during shutdown.

Rule: call `Object::take()` + `Manager::recycle()` explicitly in shutdown
paths. Do not rely on `Drop`.

### tokio::fs::File

`Drop` closes the fd through a `spawn_blocking`, so the close syscall does not
run on a runtime thread. If the runtime shuts down with
`Runtime::shutdown_timeout(Duration::ZERO)`, the close may not run and the fd
leaks to the kernel until process exit.

Rule: in shutdown paths, `drop(file)` explicitly and then
`tokio::task::yield_now().await` before you return. Outside shutdown, use
`file.sync_all().await?` followed by an explicit drop.

### General audit

For every `Drop` on an async resource type:

1. Read the library source for `impl Drop`. Does it block, spawn, or no-op?
2. If it blocks: run cleanup through an explicit `.commit()` / `.rollback()` /
   `.close()` before the drop.
3. If it spawns: cleanup is fire-and-forget. Verify the behavior under runtime
   shutdown.
4. Document the choice in a comment on the variable binding, for example
   `// drop here: blocking rollback acceptable in error path`.

## Async closures and the `AsyncFn` family (stable since Rust 1.85)

**Severity: INFO — replaces several long-standing workarounds**

Rust 1.85 (February 2025, RFC 3668) stabilized `async ||` closures and the
`AsyncFn` / `AsyncFnMut` / `AsyncFnOnce` trait family. This resolves two
long-standing pain points listed under "HRTB pitfalls" below:

1. Higher-ranked async signatures `for<'a> Fn(&'a T) -> impl Future + 'a`
   could not be expressed without GATs. `AsyncFn` handles them natively.
2. Returning futures that borrow from captured state required
   `Box<dyn Future + '_>` workarounds. `async ||` infers the right bound.

```rust,ignore
// PREFERRED (1.85+):
fn register<F>(callback: F) where F: AsyncFn(&str) -> Result<u32> { ... }
let cb = async |s: &str| { do_work(s).await };
register(cb);

// LEGACY (still works, but verbose and less inferable):
fn register<F, Fut>(callback: F)
where F: Fn(&str) -> Fut, Fut: Future<Output = Result<u32>> { ... }
let cb = |s: &str| async move { do_work(s).await };
```

Rules, once the crate MSRV is at 1.85 or above:

1. For new higher-ranked async bounds, prefer `F: AsyncFn(Args) -> T` over
   `F: Fn(Args) -> impl Future`.
2. Callbacks captured into structs that span `tokio::spawn` still need
   `+ Send + 'static`. The `AsyncFn` family does NOT auto-add `Send`. Use
   `trait_variant::make` or write the bound explicitly:
   `F: AsyncFn(Args) -> T + Send + Sync + 'static`.
3. Do NOT mass-rewrite existing `|x| async move { ... }` into `async |x|` in
   unrelated diffs. Migrate site by site when you touch the callback site for
   another reason. Premature churn obscures `git blame`.
4. The legacy HRTB workarounds below (`force_hrtb`,
   `Box<dyn for<'a> Fn(&'a str) -> ...>`) stay documented for reference. Do not
   use them in new code.

Reference:
[RFC 3668](https://github.com/rust-lang/rfcs/blob/master/text/3668-async-closures.md),
Rust 1.85 release notes.

## HRTB pitfalls in `Fn` callbacks

**Severity: WARNING**

Higher-Ranked Trait Bounds (HRTBs) — `for<'a> FnMut(&'a T) -> K` — are the
correct shape for callbacks that take a reference and return something that
must not outlive the reference. Several sharp edges exist.

**Not expressible with a dependent output.** If `K` depends on `'a` (for
example `K = &'a str`), you cannot express it without GATs today:

```rust
// Does NOT compile: K cannot depend on 'a without GATs
fn register<F: for<'a> FnMut(&'a str) -> &'a str>(f: F) {}
```

Workaround: use `Box<dyn for<'a> Fn(&'a str) -> &'a str + 'static>`, or
restructure to pass owned values.

**Closure inference quirk.** Closures in stable Rust default to fixed-lifetime
inference, not HRTB inference. A closure `|s: &str| s` fails to implement
`for<'a> Fn(&'a str) -> &'a str` in some compiler versions. Workaround: name
the function explicitly, or force HRTB with a helper:

```rust
fn force_hrtb<F: for<'a> Fn(&'a str) -> &'a str>(f: F) -> F { f }
let cb = force_hrtb(|s| s);
```

**Async `Fn` with `+ Send + 'static`.** Before RPITIT (Rust 1.75), async
functions in traits cannot be expressed as `F: for<'a> AsyncFn(&'a T)`. The
canonical pre-1.75 workaround is
`F: Fn(&T) -> Pin<Box<dyn Future<Output = R> + Send + '_>>`. From 1.75 on,
prefer `trait MyTrait { async fn call(&self, t: &T) -> R; }`.

When callbacks cross a thread boundary into `tokio::spawn`, every captured
closure must be `'static + Send`. Do not capture `&T`. Convert to an owned
value or an `Arc<T>` before the spawn.

## Async + shared state in event loops

**Severity: WARNING**

A captured `&mut State` inside an async block lives for the whole lifetime of
the `Future`, from the first poll to completion. Two concurrent futures cannot
share `&mut State`:

```rust
// DOES NOT COMPILE: two mutable borrows of `state` active at once
let f1 = async { state.handle_event(ev1) };
let f2 = async { state.handle_event(ev2) };
tokio::join!(f1, f2); // error[E0499]
```

Correct approaches, in order of preference:

1. **Single-task ownership.** One task owns `State`. Every other task
   communicates with it through `mpsc` channels. No sharing is needed. Prefer
   this on any hot path.
2. **`Arc<Mutex<State>>`.** Correct, but it serializes access. Acceptable for
   low-contention configuration state. Unacceptable on a per-packet or
   per-frame path.
3. **`RefCell<State>` inside a `!Send` single-threaded runtime.** Valid only on
   a `current_thread` runtime.

Nightly or future options — document only, do not ship them today:

- `Context::ext` (unstable): pass state through the `Waker` context without
  `unsafe`.
- Generators with `resume(arg)`: coroutine-style state handoff. Available on
  stable through the `generator-light` crate.

## `Pin` necessity in FFI

**Severity: WARNING for self-referential or FFI types**

`Pin<&mut T>` guarantees that `T` will not move after it is pinned. You need
it for:

- Self-referential structs, where a field holds a pointer to another field of
  the same struct. This is the default use of `Pin` in async state machines.
- FFI types that must not move after construction, because C++ objects have
  non-trivial move constructors that Rust cannot call.

`cxx`-generated bindings expose C++ types as `Pin<&mut CppType>`. That is
correct: C++ may have a destructor that captures `this`, so the object address
must stay stable. The same logic applies to any FFI handle that C allocates and
returns by pointer. If the C API says "do not move this after init", wrap it in
`Pin<Box<T>>` on the Rust side.

Rules:

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

## `tokio::time::timeout` is cooperative — never fires on non-yielding futures

**Severity: CRITICAL**

`tokio::time::timeout` wraps a future and checks the deadline before each poll.
If the wrapped future never reaches an `.await` point — a tight CPU loop, a
blocking syscall, a heavy synchronous computation — the timeout never fires.
The future runs to completion regardless of the deadline.

```rust
// DANGEROUS: looks protected but is not
let result = tokio::time::timeout(
    Duration::from_secs(1),
    async {
        // No .await -- timeout will never fire
        expensive_cpu_computation()
    }
).await;
```

Fix: move any blocking or CPU-heavy work into `spawn_blocking` before you wrap
it with `timeout`:

```rust
let result = tokio::time::timeout(
    Duration::from_secs(1),
    tokio::task::spawn_blocking(|| expensive_cpu_computation())
).await;
```

Apply this to every CPU-heavy classification, parsing, compression,
fingerprinting, or crypto path.

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
