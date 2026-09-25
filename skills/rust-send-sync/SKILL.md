---
name: rust-send-sync
description: Use when deciding whether a type is Send or Sync, or when rustc rejects a value at a thread or task boundary with "cannot be sent between threads safely", "cannot be shared between threads safely", or "future cannot be sent between threads safely". Also for auto trait rules of references and smart pointers (Arc vs Rc), Mutex vs RwLock payload bounds, why MutexGuard is not Send yet is Sync, PhantomData markers that remove Send or Sync, auto trait leakage from impl Trait and async fn, and E0321. Not for proving a manual unsafe impl Send or Sync; use `rust-unsafe`.
license: BSD-3-Clause
---

# Rust Send and Sync

Every error text below comes from rustc 1.98.1, edition 2024, on aarch64-apple-darwin. The
quotes are excerpts.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0277]: X cannot be sent between threads safely` with `help: the trait Sync is not implemented` | [The one rule](#the-one-rule-t-is-send-exactly-when-t-is-sync) |
| `error[E0277]: X cannot be shared between threads safely` | [The auto trait table](#the-auto-trait-table) |
| `error[E0321]: cross-crate traits with a default impl, like Send` | [E0321](#unsafe-impl-send-cannot-target-a-reference-e0321) |
| A `Mutex` was changed to an `RwLock` and the build broke | [Lock payload bounds](#lock-payload-bounds-mutex-and-rwlock-are-not-interchangeable) |
| `MutexGuard<'_, T> cannot be sent between threads safely` | [Guards](#guards-mutexguard-is-not-send-and-it-is-sync) |
| You want a type that moves between threads but is not shareable | [`PhantomData` surgery](#phantomdata-surgery) |
| An unrelated call site broke after you edited a function body | [Auto traits leak](#auto-traits-leak-out-of-impl-trait-and-async-fn) |
| `error: future cannot be sent between threads safely` | [Auto traits leak](#auto-traits-leak-out-of-impl-trait-and-async-fn) |
| ``warning: use of `async fn` in public traits is discouraged`` | the `rust-async-internals` skill, when it is installed |
| A public type must keep or lose `Send` or `Sync` on purpose | [Verify](#verify-the-auto-traits) |
| You are about to write `unsafe impl Send for MyType {}` | the `rust-unsafe` skill, when it is installed |

## The one rule: `&T` is `Send` exactly when `T` is `Sync`

`Sync` states that one fact at the type level. A `Send` error whose `help:` line names `Sync`
therefore does not ask for a `Send` impl. It reports a shared reference to a value that is not
shareable.

Both auto traits are derived field-wise. Fix a bound error in the fields, not with an impl. Two
helper functions turn any question into a compile error you can read:

```rust
fn assert_send<T: Send>() {}
fn assert_sync<T: Sync>() {}

fn main() {
    assert_send::<&i32>();                  // i32 is Sync, so &i32 is Send
    assert_sync::<&i32>();                  // &T is Sync exactly when T is Sync
    assert_send::<std::cell::Cell<i32>>();  // Cell is Send: a single owner moves it
}
```

`Cell<i32>` is `Send`. A shared reference to it is not:

```rust,compile_fail,E0277
use std::cell::Cell;
fn assert_send<T: Send>() {}
fn main() { assert_send::<&Cell<i32>>(); }
```

```text
error[E0277]: `&Cell<i32>` cannot be sent between threads safely
3 | fn main() { assert_send::<&Cell<i32>>(); }
  |                           ^^^^^^^^^^ `&Cell<i32>` cannot be sent between threads safely
  |
  = help: the trait `Sync` is not implemented for `Cell<i32>`
  = note: required for `&Cell<i32>` to implement `Send`
```

Read the two lines together. The head trait is `Send`, because that is the bound that failed. The
unmet obligation is `Sync`, on the pointee. The failing impl is `impl<T: Sync + ?Sized> Send for
&T`, and you cannot write a different one (see [E0321](#unsafe-impl-send-cannot-target-a-reference-e0321)).

Repair in this order. Delete the sharing and move the value instead of the reference. Or give the
pointee interior mutability that is `Sync`: an atomic, a `Mutex`, or an `RwLock`. Only then read
the `rust-unsafe` skill, and only for a type you own whose own invariant makes the impl sound.

Never add `unsafe impl Send` or `unsafe impl Sync` only to make an error in this skill go away,
including on a wrapper struct around an `Rc`, a `Cell`, or a guard. The compiler accepts the impl
whether or not it is sound. Fix the field, the lock, or the signature instead.

The two message texts are not interchangeable. `cannot be sent` is a failed `Send` bound;
`cannot be shared` is a failed `Sync` bound. The second appears under an `Arc`, because
`Arc<T>: Send` itself requires `T: Sync`.

## Verify the auto traits

The compiler proves only the auto traits it derives from fields. After a manual `unsafe impl`, it
no longer checks what a raw pointer field points to, so a green build proves nothing about that
impl.

| Claim | Check |
| --- | --- |
| A public type stays `Send` or `Sync` | A `const` assertion next to the type (below). A field edit then fails at the definition, not at a distant caller. Across releases, `cargo semver-checks` reports `auto_trait_impl_removed` |
| A public `-> impl Trait` return stays `Send` | Write `+ Send` (and `+ Sync` when callers share it) in the signature. The body then fails at the definition. See [Auto traits leak](#auto-traits-leak-out-of-impl-trait-and-async-fn) |
| A type is deliberately not `Send` | A `compile_fail` doctest that defines `assert_send` and calls `assert_send::<my_crate::Type>()`. A doctest is a separate crate, so `crate::Type` fails for the wrong reason. The doctest passes on any error, so keep only that call in it. Stable rustdoc does not check an error code after `compile_fail` |
| An `Arc` payload is shareable | `clippy::arc_with_non_send_sync`, warn by default |
| No `std::sync` guard lives across an `.await` | `clippy::await_holding_lock`, warn by default |
| Every `async fn` future is `Send` | `clippy::future_not_send` (nursery, allow by default). Enable it in a library whose futures cross `spawn`. It reports at the definition |

`cargo clippy --locked --all-targets -- -D warnings` runs both warn-by-default lints above (group
`suspicious`). Run it before a commit that touches a type or a future that crosses threads. To
enable `future_not_send`, set `future_not_send = "warn"` under `[lints.clippy]` in `Cargo.toml`.
The lint reports every future-returning function in the crate, private functions and trait-impl
`async fn` included. Put `#[expect(clippy::future_not_send, reason = "...")]` on each future that
is local by design. The lint ignores a future that is `Send` only for some type parameters, so it proves nothing about a
generic `async fn`.

```rust
pub struct Session { pub id: u32, pub buf: Vec<u8> }

const _: () = {
    const fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<Session>();
};
```

## The auto trait table

| Type | `Send` when | `Sync` when |
| --- | --- | --- |
| `T` (your struct) | every field is `Send` | every field is `Sync` |
| `&T` | `T: Sync` | `T: Sync` |
| `&mut T` | `T: Send` | `T: Sync` |
| `Box<T>` | `T: Send` | `T: Sync` |
| `Arc<T>` | `T: Send + Sync` | `T: Send + Sync` |
| `Rc<T>` | never | never |
| `*const T`, `*mut T` | never | never |
| `Cell<T>`, `RefCell<T>` | `T: Send` | never |
| `Mutex<T>`, `RwLock<T>` | `T: Send` | see [lock bounds](#lock-payload-bounds-mutex-and-rwlock-are-not-interchangeable) |
| `MutexGuard<'_, T>`, `RwLockReadGuard`, `RwLockWriteGuard` | never | `T: Sync` |

Two rows carry the surprise. **`Arc<T>` needs both traits on the payload, not only `Send`.** An
`Arc` clone hands a second owner shared access to one value, so the payload must be shareable as
well as movable:

```rust,compile_fail,E0277
use std::cell::Cell;
use std::sync::Arc;
fn assert_send<T: Send>() {}
fn main() {
    assert_send::<Cell<i32>>();        // ok on its own
    assert_send::<Arc<Cell<i32>>>();   // E0277: Arc<T>: Send needs T: Send + Sync
}
```

```text
error[E0277]: `Cell<i32>` cannot be shared between threads safely
  = help: the trait `Sync` is not implemented for `Cell<i32>`
  = note: if you want to do aliasing and mutation between multiple threads, use
          `std::sync::RwLock` or `std::sync::atomic::AtomicI32` instead
  = note: required for `Arc<Cell<i32>>` to implement `Send`
```

Put the lock inside the `Arc`. `Arc<Mutex<Cell<i32>>>` is
both `Send` and `Sync`, because `Mutex<T>: Sync` needs only `T: Send`. The `note:` means
"replace the `Cell`": `Arc<AtomicI32>` and `Arc<RwLock<i32>>` both work. Do not wrap the `Cell`
in the suggested `RwLock`: `RwLock<Cell<i32>>` fails again (see
[lock bounds](#lock-payload-bounds-mutex-and-rwlock-are-not-interchangeable)).

`clippy::arc_with_non_send_sync` (warn by default) reports `Arc::new` of a payload that is not
`Send + Sync` at the construction site, before any thread boundary. If that `Arc` never crosses a
thread, use `Rc`.

**`&mut T` is not the mirror of `&T`.** `&mut T: Send` requires `T: Send`, not `T: Sync`:

```rust,compile_fail,E0277
use std::cell::Cell;
use std::rc::Rc;
fn assert_send<T: Send>() {}
fn main() {
    assert_send::<&mut Cell<i32>>();  // ok: Cell<i32> is Send, although it is not Sync
    assert_send::<&mut Rc<i32>>();    // E0277: &mut T: Send needs T: Send
}
```

```text
error[E0277]: `Rc<i32>` cannot be sent between threads safely
  = help: within `&mut Rc<i32>`, the trait `Send` is not implemented for `Rc<i32>`
  = note: required because it appears within the type `&mut Rc<i32>`
```

A `&mut T` is a move channel, not a view. `std::mem::replace(x, T::default())` takes the value out
through the reference, so the receiving thread owns and drops it. That is the `Send` obligation.

## `unsafe impl Send` cannot target a reference (E0321)

You cannot decide per reference type whether it is `Send`. The impl does not exist to be written:

```rust,compile_fail,E0321
pub struct Handle(*mut u8);
unsafe impl Send for &Handle {}
unsafe impl Send for &mut Handle {}
```

```text
error[E0321]: cross-crate traits with a default impl, like `Send`, can only be implemented
              for a struct/enum type, not `&Handle`
2 | unsafe impl Send for &Handle {}
  | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ can't implement cross-crate trait with a default impl
  |                              for non-struct/enum type
```

`unsafe impl Send for Handle {}` compiles, because `Handle` is a struct in this crate. `Sync` is
the only lever that reaches `&Handle`: write `unsafe impl Sync for Handle {}`, and `&Handle`
becomes `Send` through the blanket impl. That is a stronger promise. The `rust-unsafe` skill holds
the audit it needs.

## Lock payload bounds: `Mutex` and `RwLock` are not interchangeable

- `Mutex<T>: Sync` requires only `T: Send`.
- `RwLock<T>: Sync` requires `T: Send + Sync`.

A `Mutex` hands out one `&mut T` at a time, so the payload never has to be shareable. An `RwLock`
hands out many concurrent `&T`, so the payload must be `Sync` on its own.

```rust
use std::cell::Cell;
use std::sync::Mutex;
fn assert_sync<T: Sync>() {}
fn main() { assert_sync::<Mutex<Cell<i32>>>(); }   // compiles
```

```rust,compile_fail,E0277
use std::cell::Cell;
use std::sync::RwLock;
fn assert_sync<T: Sync>() {}
fn main() { assert_sync::<RwLock<Cell<i32>>>(); }
```

```text
error[E0277]: `Cell<i32>` cannot be shared between threads safely
  = help: the trait `Sync` is not implemented for `Cell<i32>`
  = note: required for `std::sync::RwLock<Cell<i32>>` to implement `Sync`
```

Changing a read-heavy `Mutex<T>` to an `RwLock<T>` is therefore **not** a drop-in change. It stops
compiling as soon as the payload holds a `Cell` or a `RefCell`, and the error lands on the
`Arc<RwLock<...>>` at a call site far from the edit. Check the payload first. An `Rc` payload is
not a symptom of the swap. `Mutex<T>: Sync` also requires `T: Send`, so `Mutex<Rc<T>>` is neither
`Send` nor `Sync` before the edit. `Mutex<T>: Send` and `RwLock<T>: Send` both need only
`T: Send`, so the `Send` direction gives no warning.

## Guards: `MutexGuard` is not `Send`, and it is `Sync`

`std::sync::MutexGuard<'_, T>` is `!Send` for every `T`. POSIX requires the unlocking thread to be
the locking thread, so the guard's `Drop` must run where the guard was created.

```rust,compile_fail,E0277
use std::sync::MutexGuard;
fn assert_send<T: Send>() {}
fn main() { assert_send::<MutexGuard<'static, i32>>(); }
```

```text
error[E0277]: `std::sync::MutexGuard<'static, i32>` cannot be sent between threads safely
  = help: the trait `Send` is not implemented for `std::sync::MutexGuard<'static, i32>`
```

Do not read that as "nothing derived from the guard leaves the thread". The guard is `Sync`
whenever `T: Sync`, so `&MutexGuard<'_, T>` **is** `Send`. Reading through the guard is reading
`&T`, and that is safe to share. This runs and prints `total=6`:

```rust,run
use std::sync::Mutex;
use std::thread;

fn main() {
    let lock = Mutex::new(vec![1u32, 2, 3]);
    let guard = lock.lock().expect("lock poisoned");
    let total: u32 = thread::scope(|s| {
        // &MutexGuard is Send, because MutexGuard is Sync.
        s.spawn(|| guard.iter().sum::<u32>()).join().unwrap()
    });
    assert_eq!(total, 6);
    println!("total={total}");
    drop(guard);   // the unlock runs on the locking thread
}
```

Consequences to hold:

- Give a worker `&guard` only when the payload is `Sync`. `&MutexGuard<'_, T>` is `Send` exactly
  when `T: Sync`, so `&MutexGuard<'_, Cell<T>>` and `&MutexGuard<'_, RefCell<T>>` do not cross.
  Clone the value out of the guard instead. Never give a worker the guard itself.
- Pass `&guard` through `thread::scope`. `thread::spawn` requires `'static`, so it rejects the
  borrow with ``error[E0597]: `lock` does not live long enough``, plus `error[E0373]` when the
  closure borrows `guard` directly. Do not apply the E0373 `move` suggestion: it moves the guard
  itself, and that fails with E0277.
- Do not hold a `std::sync` guard across an `.await`. The task can resume on another thread, so
  the future stops being `Send`. `clippy::await_holding_lock` (warn by default) catches it. The
  `rust-async-internals` skill covers the async lock choice.

## `PhantomData` surgery

`PhantomData<X>` inherits the auto traits of `X`. Use `PhantomData<Cell<()>>` to remove only
`Sync`. Use a raw pointer marker such as `PhantomData<*mut ()>` only when you mean to remove both,
because it also blocks a move to a worker thread. Write `()` in the marker, not your own `T`: a
marker that names `T` also changes variance. Read
[references/phantomdata-markers.md](references/phantomdata-markers.md) when you design a marker:
it has the marker table with variance, and the marker that removes only `Send`.

## Auto traits leak out of `impl Trait` and `async fn`

A public `-> impl Trait` with no explicit `+ Send` publishes whatever auto traits the **body**
happens to have. Adding one `Rc` inside the function is then a breaking change, and the compiler
reports it at every distant call site, with a `note:` that points into your private body:

```text
error[E0277]: `Rc<Vec<u32>>` cannot be sent between threads safely
10 |     std::thread::spawn(move || { let _: Vec<u32> = it.collect(); });
   |                        ^^^^^^^ within this `{closure@...}`
note: required because it appears within the type `impl Iterator<Item = u32>`
```

Spell the bound in the signature. The guarantee is then frozen, and the body is the thing that
must comply:

```rust
pub fn ids() -> impl Iterator<Item = u32> + Send {
    (0..3).map(|i| i * 2)
}
fn main() { assert_eq!(ids().sum::<u32>(), 6); }
```

With `+ Send` written, the same offending body fails at the definition:

```rust,compile_fail,E0277
use std::rc::Rc;
pub fn ids() -> impl Iterator<Item = u32> + Send {
    let names: Rc<Vec<u32>> = Rc::new(vec![1, 2, 3]);
    (0..3).map(move |i| names[i])
}
```

```text
error[E0277]: `Rc<Vec<u32>>` cannot be sent between threads safely
3 | pub fn ids() -> impl Iterator<Item = u32> + Send {
  |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ `Rc<Vec<u32>>` cannot be sent ...
5 |     (0..3).map(move |i| names[i])
  |     ----------------------------- return type was inferred to be `Map<...>` here
```

Write `+ Send` only when you intend it, and add `+ Sync` when callers share the returned value. An
API that is single-threaded by design cannot carry the bound, because it then fails at the
definition. Record that decision in the doc comment.

This is not async-specific. `async fn f() -> T` desugars to `fn f() -> impl Future<Output = T>`.
It has the same leak. On stable Rust 1.98.1, no syntax puts a bound on an `async fn` return type.
Write the desugared form:

```rust
use std::future::Future;

pub fn load(id: u32) -> impl Future<Output = u32> + Send {
    async move { id + 1 }
}

fn main() { let _ = load(1); }
```

Do not silence the `async_fn_in_trait` warning when callers spawn the future. For `async fn`
in a trait that callers spawn, and for return type notation, use the `rust-async-internals`
skill, when it is installed.

The async diagnostic has **no error code**, so a search for E0277 finds nothing:

```text
error: future cannot be sent between threads safely
  |                         ^^^^ future created by async block is not `Send`
note: future is not `Send` as this value is used across an await
5 |         let names = Rc::new(vec![1u32, 2, 3]);
  |             ----- has type `Rc<Vec<u32>>` which is not `Send`
6 |         std::future::ready(()).await;
  |                                ^^^^^ await occurs here, with `names` maybe used later
```

Read the `note:`. It names the value and the exact `.await` that traps it. The
`rust-compiler-errors` skill covers the message shape; the fix here is the signature.

## Related skills

Use these skills by name when they are installed.

| Skill | Boundary |
| --- | --- |
| `rust-unsafe` | The proof obligation of a manual `unsafe impl Send` or `Sync`: the field audit, the compile-time field assertions, and the `SAFETY` comment |
| `rust-variance` | The other half of a `PhantomData` marker: which substitutions the marker still allows, and the invariance a `Cell` or `*mut` marker introduces |
| `rust-compiler-errors` | Reading E0277 in general, and the async block message that carries no error code |
| `rust-async-internals` | Holding a guard across an `.await`, the async lock choice, `Send` trait variants, and cancel safety |
| `memory-model` | Atomics, orderings, `loom`, and shared statics once the bounds are satisfied |
| `rust-crate-release` | Semver review of a public auto trait change |
