# Variance tables, probe files, and the unsound contravariant channel

Deep material for `rust-variance`. Every result below comes from rustc 1.97.0, edition 2024,
aarch64-apple-darwin, and Miri 0.1.0 on the matching nightly.

## The probe files

Compile with a real output path. `rustc -o /dev/null` fails with a temp-directory error even
when the code is correct:

```bash
rustc --edition 2024 --crate-type lib --emit=metadata probe.rs -o probe.rmeta
```

### Covariance: every one of these compiles

```rust
use std::collections::HashMap;
use std::fmt::Debug;
use std::marker::PhantomData;
use std::rc::Rc;
use std::sync::Arc;

struct Own<T>(PhantomData<T>);

fn p01<'a, 'b: 'a>(x: &'b u8) -> &'a u8 { x }
fn p02<'a, 'b: 'a>(x: Box<&'b u8>) -> Box<&'a u8> { x }
fn p03<'a, 'b: 'a>(x: Vec<&'b u8>) -> Vec<&'a u8> { x }
fn p04<'a, 'b: 'a>(x: *const &'b u8) -> *const &'a u8 { x }
fn p05<'a, 'b: 'a>(x: fn() -> &'b u8) -> fn() -> &'a u8 { x }
fn p06<'a, 'b: 'a>(x: PhantomData<&'b u8>) -> PhantomData<&'a u8> { x }
fn p07<'a, 'b: 'a>(x: PhantomData<fn() -> &'b u8>) -> PhantomData<fn() -> &'a u8> { x }
fn p08<'a, 'b: 'a>(x: PhantomData<*const &'b u8>) -> PhantomData<*const &'a u8> { x }
fn p09<'a, 'b: 'a>(x: PhantomData<&'b mut u8>) -> PhantomData<&'a mut u8> { x }
fn p10<'a, 'b: 'a>(x: Box<dyn Debug + 'b>) -> Box<dyn Debug + 'a> { x }
fn p11<'a, 'b: 'a>(x: &'b mut u8) -> &'a mut u8 { x }
fn p12<'a, 'b: 'a>(x: Own<&'b u8>) -> Own<&'a u8> { x }
fn p13<'a, 'b: 'a>(x: Rc<&'b u8>) -> Rc<&'a u8> { x }
fn p14<'a, 'b: 'a>(x: Arc<&'b u8>) -> Arc<&'a u8> { x }
fn p15<'a, 'b: 'a>(x: Option<&'b u8>) -> Option<&'a u8> { x }
fn p16<'a, 'b: 'a>(x: Result<&'b u8, &'b str>) -> Result<&'a u8, &'a str> { x }
fn p17<'a, 'b: 'a>(x: (&'b u8, u32)) -> (&'a u8, u32) { x }
fn p18<'a, 'b: 'a>(x: [&'b u8; 3]) -> [&'a u8; 3] { x }
fn p19<'a, 'b: 'a>(x: HashMap<u32, &'b u8>) -> HashMap<u32, &'a u8> { x }
fn p20<'x, 'a, 'b: 'a>(x: &'x [&'b u8]) -> &'x [&'a u8] where 'b: 'x { x }
```

Note `p11`: `&'a mut T` is covariant in `'a`, the lifetime of the borrow itself. It is invariant
in `T`. The two facts sit in one type and are easy to confuse.

### Contravariance: only these two compile

```rust
use std::marker::PhantomData;

fn c1<'a, 'b: 'a>(x: fn(&'a u8)) -> fn(&'b u8) { x }
fn c2<'a, 'b: 'a>(x: PhantomData<fn(&'a u8)>) -> PhantomData<fn(&'b u8)> { x }
```

`&'a u8`, `fn() -> &'a u8`, and `Box<dyn Fn(&'a u8)>` are all rejected in the contravariant
direction with `error: lifetime may not live long enough`.

### Invariance: the exact note for each row

Each line below is one probe of the shape `fn p<'a, 'b: 'a>(x: C<&'b u8>) -> C<&'a u8> { x }`,
followed by the note rustc prints. All of them fail.

| Probe type | rustc note |
| --- | --- |
| `Cell<&'b u8>` | the struct `Cell<T>` is invariant over the parameter `T` |
| `UnsafeCell<&'b u8>` | the struct `UnsafeCell<T>` is invariant over the parameter `T` |
| `RefCell<&'b u8>` | the struct `RefCell<T>` is invariant over the parameter `T` |
| `Mutex<&'b u8>` | the struct `std::sync::Mutex<T>` is invariant over the parameter `T` |
| `RwLock<&'b u8>` | the struct `std::sync::RwLock<T>` is invariant over the parameter `T` |
| `mpsc::Sender<&'b u8>` | the struct `std::sync::mpsc::Sender<T>` is invariant over the parameter `T` |
| `*mut &'b u8` | mutable pointers are invariant over their type parameter |
| `&'x mut &'b u8` | mutable references are invariant over their type parameter |
| `PhantomData<Cell<&'b u8>>` | the struct `Cell<T>` is invariant over the parameter `T` |
| `PhantomData<*mut &'b u8>` | mutable pointers are invariant over their type parameter |
| `fn(&'b u8) -> &'b u8` | no variance note |
| `Box<dyn Fn(&'b u8)>` | no variance note |
| `Box<dyn Fn() -> &'b u8>` | no variance note |

Every row, the three `fn` and `dyn` rows included, prints
`help: consider adding the following bound: 'a: 'b` under the error. Only a row that prints a
variance note also prints
`help: see <https://doc.rust-lang.org/nomicon/subtyping.html> for more information about variance`.
The three `fn` and `dyn` rows print no variance note, so grep for the error text alone when you
script this.

## Probe traps

**Never put `'static` in the outer position.** This compiles and proves nothing. The outer
`&'static mut` forces `&'b u8: 'static`, which collapses `'a` and `'b` to the same lifetime:

```rust
fn degenerate<'a, 'b: 'a>(x: &'static mut &'b u8) -> &'static mut &'a u8 { x }
```

The correct form uses a fresh outer lifetime and explicit outlives bounds. It is rejected, which
is the true answer:

```rust,compile_fail
fn honest<'x, 'a: 'x, 'b: 'a>(x: &'x mut &'b u8) -> &'x mut &'a u8 { x }
```

**A probe on a type parameter needs a lifetime inside it.** `C<u8>` cannot show variance,
because `u8` has no subtypes. Always probe with `&'b u8`.

## What each `PhantomData` form declares

| Form | Variance in `T` | `Send` / `Sync` | Use it for |
| --- | --- | --- | --- |
| `PhantomData<T>` | covariant | both follow `T` | the struct owns a `T` it does not store |
| `PhantomData<&'a T>` | covariant | both need `T: Sync` | the struct borrows a `T` for `'a` |
| `PhantomData<&'a mut T>` | invariant in `T`, covariant in `'a` | `Send` needs `T: Send`, `Sync` needs `T: Sync` | an exclusive borrow |
| `PhantomData<fn() -> T>` | covariant | always both, whatever `T` is | a type-state tag that is never built |
| `PhantomData<fn(T)>` | contravariant | always both, whatever `T` is | a consumer that never stores a `T` |
| `PhantomData<*mut T>` | invariant | neither, whatever `T` is | a raw handle that must stay on one thread |
| `PhantomData<Cell<T>>` | invariant | `Send` needs `T: Send`, never `Sync` | interior mutability held behind a pointer |

The drop-check role of `PhantomData<T>` is real but is not observable on stable. With a plain
`impl Drop`, every lifetime parameter must strictly outlive the value whether the marker is there
or not. The difference appears only under `#![feature(dropck_eyepatch)]` with
`unsafe impl<#[may_dangle] T> Drop`. Do not look for a stable reproduction.

`rust-unsafe` covers the same markers from the FFI side, and `rust-discipline` covers
`PhantomData<fn() -> S>` on type-state APIs.

## The unsound contravariant channel

A handle whose only mention of `T` is `PhantomData<fn(T)>` is contravariant in `T`. That lets
`Sender<Message<'short>>` be used as `Sender<Message<'static>>`, so the handle escapes into a
`'static` context while the shared buffer still holds `Message<'short>` values. When the last
handle drops, the buffer runs their destructors, after the borrowed data is gone.

```rust
// UB: the queue drops `Message<'short>` values after `message` is freed.
use std::cell::RefCell;
use std::marker::PhantomData;
use std::rc::Rc;

struct Slot { data: *mut u8, drop_fn: unsafe fn(*mut u8) }

unsafe fn drop_as<T>(p: *mut u8) { drop(unsafe { Box::from_raw(p as *mut T) }) }

struct Queue { slots: RefCell<Vec<Slot>> }

impl Drop for Queue {
    fn drop(&mut self) {
        for s in self.slots.borrow_mut().drain(..) { unsafe { (s.drop_fn)(s.data) } }
    }
}

// The only mention of T is `fn(T)`, so Sender<T> is contravariant in T.
struct Sender<T> { q: Rc<Queue>, _m: PhantomData<fn(T)> }

impl<T> Clone for Sender<T> {
    fn clone(&self) -> Self { Sender { q: self.q.clone(), _m: PhantomData } }
}

impl<T> Sender<T> {
    fn send(&self, v: T) {
        let data = Box::into_raw(Box::new(v)) as *mut u8;
        self.q.slots.borrow_mut().push(Slot { data, drop_fn: drop_as::<T> });
    }
}

struct Message<'a>(&'a str);

impl Drop for Message<'_> {
    fn drop(&mut self) { println!("dropping message: {}", self.0); }
}

fn stash(s: Sender<Message<'static>>) -> Box<dyn FnOnce()> {
    Box::new(move || { let _keep = s; })
}

fn main() {
    let escaped;
    {
        let message = String::from("world");
        let q = Rc::new(Queue { slots: RefCell::new(Vec::new()) });
        let tx: Sender<Message<'_>> = Sender { q, _m: PhantomData };
        escaped = stash(tx.clone());          // contravariance widens 'short to 'static
        tx.send(Message(&message));
    }
    println!("block over");
    drop(escaped);
}
```

The program compiles with no warning and no `unsafe` at the call sites that matter:

```text
$ cargo run
block over
dropping message:
$ cargo +nightly miri run
error: Undefined Behavior: constructing invalid value of type &str: encountered a dangling reference (use-after-free)
    --> library/core/src/fmt/mod.rs:2872:71
     = note: stack backtrace:
             <Message<'_> as std::ops::Drop>::drop
             drop_as::<Message<'_>>
             <Queue as std::ops::Drop>::drop
```

Replace `Queue::drop` with a version that leaks the slots instead of calling `drop_fn`, and Miri
reports a leak and no undefined behavior. That isolates the destructor as the whole cause.

Rules that follow:

- Contravariance is sound for a handle that consumes a `T` inside the call and never stores or
  drops one. A queue stores and drops, so its handle must stay invariant.
- `std::sync::mpsc::Sender<T>` is invariant for this reason, not by oversight.
- A `PhantomData<fn(T)>` on a type that owns a `T` is a soundness bug, not a style choice.
  Use `PhantomData<T>`.

## The invariant `Sender`, rejected and repaired

`std::sync::mpsc::Sender<T>` is invariant in `T`, so one call site that demands `'static` pins the
whole channel. This pair is rejected:

```rust,compile_fail
use std::sync::mpsc::{channel, Sender};

struct Message<'a> { description: &'a str }

fn short_lived<'a>(_storage: &'a String, _s: Sender<Message<'a>>) {}
fn long_lived(_s: Sender<Message<'static>>) {}

fn main() {
    let storage = "descr".to_string();
    let (tx, _rx) = channel();
    short_lived(&storage, tx.clone());
    long_lived(tx.clone());
}
```

```text
error[E0597]: `storage` does not live long enough
11 |     short_lived(&storage, tx.clone());
   |                 ^^^^^^^^ borrowed value does not live long enough
12 |     long_lived(tx.clone());
   |     ---------------------- argument requires that `storage` is borrowed for `'static`
```

The message is covariant even though the handle is not. Write consumers generic over the
lifetime, and coerce at the send site:

```rust
use std::sync::mpsc::{channel, Sender};

struct Message<'a> { description: &'a str }

fn any_lifetime(_s: Sender<Message<'_>>) {}                     // not Message<'static>
fn send_static<'a>(s: &Sender<Message<'a>>, m: Message<'static>) { let _ = s.send(m); }

fn main() {
    let storage = "descr".to_string();
    let (tx, _rx) = channel();
    any_lifetime(tx.clone());
    send_static(&tx, Message { description: "literal" });
    let _ = tx.send(Message { description: &storage });
}
```
