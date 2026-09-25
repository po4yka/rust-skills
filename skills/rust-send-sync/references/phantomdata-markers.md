# `PhantomData` markers for `Send` and `Sync`

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
  `T`, which rejects caller substitutions that look safe. The `rust-variance` skill covers that
  side.
- `PhantomData<MutexGuard<'static, T>>` goes further than the other four markers. `MutexGuard<'a,
  T>` is declared `T: ?Sized + 'a`, so a naked `T` in this marker forces `T: 'static` on the
  struct, and rustc rejects the definition with `error[E0310]`. Write `MutexGuard<'static, ()>`
  for the auto trait effect, and name `T` in a second marker.
