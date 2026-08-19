---
name: rust-send-sync
description: Use when you decide whether a type is Send, Sync, both, or neither, and when the compiler rejects a value at a thread boundary. Covers the one rule that generates the rest: &T is Send exactly when T is Sync. Covers the Send error whose help line names Sync, and the auto trait table for &T, &mut T, Box, Arc, Rc and raw pointers. Covers why Mutex<T> Sync needs only T Send while RwLock<T> Sync needs T Send + Sync, so the swap is not drop-in. Covers why MutexGuard is not Send but is Sync, so a scoped thread reads through a reference to the guard. Covers the four PhantomData markers and their variance side effect, auto trait leakage out of impl Trait and async fn, and E0321 on an unsafe impl for a reference type. Triggers on "Send", "Sync", "auto trait", "cannot be sent between threads safely", "cannot be shared between threads safely", "future cannot be sent between threads safely", "E0321", "PhantomData", "thread::scope", "Arc vs Rc", "MutexGuard is not Send", or "is not Send".
license: BSD-3-Clause
---

# Rust Send and Sync

## Purpose

Decide whether a type crosses a thread boundary, and read the diagnostic when it does not. One
sentence generates almost every rule below: **`&T` is `Send` exactly when `T` is `Sync`**. `Sync`
states that one fact at the type level. A `Send` error whose `help:` line names `Sync` therefore
does not ask for a `Send` impl. It reports a shared reference to a non-shareable value.

This skill is safe-code type reasoning. It stops where a manual `unsafe impl` starts: the proof
obligation, the field audit, and the `SAFETY` comment belong to `rust-unsafe`. Atomics belong to
`memory-model`. Cancel safety belongs to `rust-async-internals`.

Every error text below comes from rustc 1.97.0, edition 2024, on aarch64-apple-darwin.

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
| You are about to write `unsafe impl Send for MyType {}` | `rust-unsafe` |

## The one rule: `&T` is `Send` exactly when `T` is `Sync`

Both auto traits are derived field-wise. You never implement them; you arrange for them. Two
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

```rust,compile_fail
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
`rust-unsafe`, and only for a type you own.

The two message texts are not interchangeable. `cannot be sent` is a failed `Send` bound;
`cannot be shared` is a failed `Sync` bound. The second appears under an `Arc`, because
`Arc<T>: Send` itself requires `T: Sync`.

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

```rust,compile_fail
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

Put the lock inside the `Arc`, never an `unsafe impl` outside it. `Arc<Mutex<Cell<i32>>>` is
both `Send` and `Sync`, because `Mutex<T>: Sync` needs only `T: Send`.

**`&mut T` is not the mirror of `&T`.** `&mut T: Send` requires `T: Send`, not `T: Sync`:

```rust,compile_fail
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

```rust,compile_fail
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
becomes `Send` through the blanket impl. That is a stronger promise. `rust-unsafe` holds the audit
it needs.

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

```rust,compile_fail
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

```rust,compile_fail
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

```rust
use std::sync::Mutex;
use std::thread;

fn main() {
    let lock = Mutex::new(vec![1u32, 2, 3]);
    let guard = lock.lock().unwrap();
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
- Pass `&guard` through `thread::scope`. The reference borrows the guard, and `thread::spawn`
  requires `'static`, so it rejects the borrow with `error[E0597]`.
- Do not hold a `std::sync` guard across an `.await`. The task can resume on another thread, so
  the future stops being `Send`. `clippy::await_holding_lock` catches it; `rust-async-internals`
  covers the async lock choice.

## `PhantomData` surgery

`PhantomData<X>` inherits `X`'s auto traits exactly, so any std type with the wanted
implementation works as a marker. Pick the marker that removes only what you mean to remove:

| Marker field | `Send` | `Sync` | Variance in `T` if the marker names your own `T` |
| --- | --- | --- | --- |
| `PhantomData<fn() -> T>` | kept | kept | covariant |
| `PhantomData<Cell<T>>` | kept | removed | invariant |
| `PhantomData<MutexGuard<'static, T>>` | removed | kept | invariant, and it forces `T: 'static` |
| `PhantomData<*const T>` | removed | removed | covariant |
| `PhantomData<*mut T>` | removed | removed | invariant |

```rust
use std::cell::Cell;
use std::marker::PhantomData;
use std::sync::MutexGuard;

struct SendNotSync(PhantomData<Cell<()>>);                 // moves threads, does not share
struct SyncNotSend(PhantomData<MutexGuard<'static, ()>>);  // shares, stays on its thread
struct NeitherOne(PhantomData<*const ()>);                 // both removed
struct BothKept<T>(PhantomData<fn() -> T>);                // both kept for every T

fn assert_send<T: Send>() {}
fn assert_sync<T: Sync>() {}
fn main() {
    assert_send::<SendNotSync>();
    assert_sync::<SyncNotSend>();
    assert_send::<BothKept<std::rc::Rc<i32>>>();
    assert_sync::<BothKept<std::rc::Rc<i32>>>();
    let _ = NeitherOne(PhantomData);   // constructs, but neither Send nor Sync
}
```

Rules:

- Reach for `PhantomData<*mut ()>` only when you mean "neither". It is the default reflex and it
  is wrong when you only meant "not shareable": it also blocks moving the value to a worker
  thread, and the diagnostic then names `*mut ()`, a type the reader cannot find in the struct.
- Write `()` inside the marker when the marker only drops an auto trait. A marker that names your
  own parameter also constrains variance: `PhantomData<Cell<T>>` makes the struct invariant in
  `T`, which rejects caller substitutions that look safe. See
  [rust-variance](../rust-variance/SKILL.md).
- `PhantomData<MutexGuard<'static, T>>` goes further than the other four markers. `MutexGuard<'a,
  T>` is declared `T: ?Sized + 'a`, so a naked `T` in this marker forces `T: 'static` on the
  struct, and rustc rejects the definition with `error[E0310]`. Write `MutexGuard<'static, ()>`
  for the auto trait effect, and name `T` in a second marker.

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

```rust,compile_fail
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

Write `+ Send` only when you intend it. An API that is single-threaded by design cannot carry the
bound, because it then fails at the definition. Record that decision in the doc comment.

This is not async-specific. `async fn f() -> T` desugars to `fn f() -> impl Future<Output = T>`.
It has the same leak. No syntax puts a bound on an `async fn` return type. Write the desugared
form:

```rust
use std::future::Future;

pub fn load(id: u32) -> impl Future<Output = u32> + Send {
    async move { id + 1 }
}

pub trait Repo {
    fn get(&self, id: u32) -> impl Future<Output = u32> + Send;
}

fn main() { let _ = load(1); }
```

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

Read the `note:`. It names the value and the exact `.await` that traps it. `rust-compiler-errors`
covers the message shape; the fix here is the signature.

## Checklist

- [ ] The `Send` error's `help:` line names `Sync`? Fix the pointee, not the outer type.
- [ ] Every `Arc<T>` payload is `Send + Sync`, not only `Send`.
- [ ] No `Mutex` became an `RwLock` without a payload check for `Cell` or `RefCell`.
- [ ] No `MutexGuard` is moved into a thread, a task, or a `'static` closure. `&guard` is fine only
      when the payload is `Sync`, and only inside `thread::scope`.
- [ ] Each `PhantomData` marker removes exactly the auto traits the design intends, and its
      variance effect was checked.
- [ ] Every public `-> impl Trait` and every public `-> impl Future` states the auto traits it
      intends: `+ Send` when callers cross a thread boundary, `+ Sync` when callers share the
      value. A single-threaded API says so in its doc comment, so the absent bound is a decision.
- [ ] No `unsafe impl Send` or `unsafe impl Sync` was added to silence any item above.

## Related skills

| Skill | Boundary |
| --- | --- |
| [rust-unsafe](../rust-unsafe/SKILL.md) | This skill arranges the auto traits in safe code. `rust-unsafe` owns the proof obligation of a manual `unsafe impl Send` or `Sync`: the field audit, the compile-time field assertions, and the `SAFETY` comment |
| [rust-variance](../rust-variance/SKILL.md) | The other half of a `PhantomData` marker: which substitutions the marker still allows, and the invariance a `Cell` or `*mut` marker introduces |
| [rust-compiler-errors](../rust-compiler-errors/SKILL.md) | Reading E0277 in general, and the async block message that carries no error code |
| [rust-async-internals](../rust-async-internals/SKILL.md) | Holding a guard across an `.await`, the async lock choice, and cancel safety |
| [memory-model](../memory-model/SKILL.md) | Atomics, orderings, `loom`, and shared statics once the bounds are satisfied |
