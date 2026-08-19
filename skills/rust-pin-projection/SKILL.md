---
name: rust-pin-projection
description: Use when you put Pin in a signature, write a self-referential struct, or project a pinned reference into a field. Covers the gate that Pin enforces nothing when the target is Unpin, why Unpin does not mean movable and a PhantomPinned value still moves in safe code, the choice between std::pin::pin!, Box::pin and Pin::new_unchecked and the stack escape that compiles with zero warnings and is undefined behaviour, why a hand-rolled shadowing pin macro is broken, the four structural pinning obligations with their diagnostics, Drop taking &mut self on a pinned value, repr(packed) as incompatible with pinning, and the Unpin rule the projection macros change under you. Triggers on "pin projection", "structural pinning", "pin-project", "pin-project-lite", "PhantomPinned", "Pin::new_unchecked", "self-referential struct", "Unpin", "Box::pin", "std::pin::pin!", "PinnedDrop", "address-sensitive", "E0596", or "cannot borrow data in dereference of".
license: BSD-3-Clause
---

# Rust pin projection

## Purpose

Decide whether `Pin` buys anything in your signature, then meet the obligations it creates.
This skill covers address-sensitive types, `Unpin`, `PhantomPinned`, the three ways to pin a
value, and pinning projection into a field, by hand and through the macro crates.

The sentence to not get wrong: `Pin<&mut T>` enforces nothing when `T: Unpin`, and `!Unpin` never
makes a type unmovable. The restriction starts at the pin, and only for a `!Unpin` type.

The skill stops at `Pin`. Polling and cancel safety belong to `rust-async-internals`. Miri
belongs to `rust-sanitizers-miri`. Every diagnostic and Miri transcript below comes from rustc
1.97.0, edition 2024, aarch64-apple-darwin, Miri on nightly, pin-project 1.1.13, and
pin-project-lite 0.2.17.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| You are about to write `self: Pin<&mut Self>` | [Pin enforces nothing for an Unpin target](#pin-enforces-nothing-for-an-unpin-target) |
| `PhantomPinned`, or a claim that a type "cannot move" | [Unpin does not mean movable](#unpin-does-not-mean-movable) |
| `error[E0277]: PhantomPinned cannot be unpinned` | [Get a value pinned](#get-a-value-pinned) |
| `error[E0515]: cannot return value referencing temporary value`, at a `pin!` | [Get a value pinned](#get-a-value-pinned) |
| `error[E0382]: use of moved value`, `does not implement the Copy trait` | [Get a value pinned](#get-a-value-pinned) |
| Miri: `allocN has been freed, so this pointer is dangling` | [Never pin a named stack binding](#never-pin-a-named-stack-binding) |
| `error[E0133]: call to unsafe function Pin::<Ptr>::new_unchecked is unsafe` | [Never hand-roll a stack pinning macro](#never-hand-roll-a-stack-pinning-macro) |
| You wrote `impl<T> Unpin for MyType<T> {}` | [Obligation 1](#obligation-1-structural-unpin) |
| You wrote `impl Drop`, or `#[repr(packed)]`, on a type with a pinned field | [Obligation 2](#obligation-2-pinned-destruction) |
| A pinned value sits in `ManuallyDrop`, or an `Option` is set to `None` | [Obligation 3](#obligation-3-notice-of-destruction) |
| `error[E0596]: cannot borrow data in dereference of Pin<&mut T> as mutable` | [Obligation 4](#obligation-4-no-move-out-operation) |
| You choose between `pin-project` and `pin-project-lite` | [The projection macros](#the-projection-macros) |
| You write a smart pointer that a caller may wrap in `Pin` | [Your own pinning pointer type](#your-own-pinning-pointer-type) |
| You must overwrite a pinned value, or write a `PinnedDrop` | `references/pin-projection-macros.md` |

## Pin enforces nothing for an Unpin target

Check this before you add `Pin` to any signature. `Pin::new` and `Pin::get_mut` are both safe
for an `Unpin` target, and `Pin<Ptr>` implements `DerefMut` for one. Every door that `Pin`
exists to close stands open, and safe code walks through it:

```rust
use std::mem;
use std::pin::Pin;

fn main() {
    let (mut a, mut b) = (String::from("a"), String::from("b"));
    // Both calls are safe, because String: Unpin.
    mem::swap(Pin::new(&mut a).get_mut(), Pin::new(&mut b).get_mut());
    assert_eq!((a.as_str(), b.as_str()), ("b", "a"));

    // `Pin<Ptr>` implements `DerefMut` for an `Unpin` target, so this is safe too.
    let mut c = 0u32;
    *Pin::new(&mut c) = 7;
    assert_eq!(c, 7);
}
```

`self: Pin<&mut Self>` on an `Unpin` type documents intent and enforces nothing. So:

- Write `Pin` in a signature only when the type is `!Unpin`, or when a trait such as `Future`
  forces the receiver. Otherwise take `&mut self` and delete the ceremony.
- Add a `PhantomPinned` field to the type whose address must stay stable. That one field
  removes the auto `Unpin` impl and turns the API from documentation into enforcement.

## Unpin does not mean movable

`Unpin` is not `Movable`, and `!Unpin` is not `Unmovable`. Many write-ups rename the trait this
way, and the rename produces wrong designs. Every Rust type moves, `!Unpin` included:

```rust
use std::marker::PhantomPinned;
use std::mem;

struct NotUnpin { x: u32, _p: PhantomPinned }

fn main() {
    let a = NotUnpin { x: 1, _p: PhantomPinned };
    let mut c = a;                                   // move by assignment
    let mut d = NotUnpin { x: 2, _p: PhantomPinned };
    mem::swap(&mut c, &mut d);                       // swap through &mut
    let boxed = Box::new(c);                         // move into the heap
    let v = vec![d];                                 // move into a Vec
    assert_eq!((boxed.x, v[0].x), (2, 1));
}
```

That program has no `unsafe`. It compiles with no error and no warning. `Unpin` is an auto trait
that only the bounds on `Pin`'s own API read. It takes part in no move check anywhere else in
the language. Read `T: Unpin` as "pinning `T` has no effect, and `&mut T` comes back out of
`Pin<&mut T>` for free". Read `T: !Unpin` as "once a value is pinned, safe code cannot reach
`&mut T` again". Before the pin, nothing is restricted.

## Get a value pinned

| Constructor | Result | Unsafe | Escapes the frame | Allocates |
| --- | --- | --- | --- | --- |
| `std::pin::pin!(value)` | `Pin<&mut T>` | no | no | no |
| `Box::pin(value)` | `Pin<Box<T>>` | no | yes | yes |
| `Pin::new(&mut value)` | `Pin<&mut T>` | no, needs `T: Unpin` | no | no |
| `unsafe { Pin::new_unchecked(&mut value) }` | `Pin<&mut T>` | yes | no | no |

`std::pin::pin!` is stable since 1.68. It needs no crate, no feature gate, and no `unsafe`.
Write-ups that call it unstable are out of date.

```rust
use std::marker::PhantomPinned;
use std::pin::{pin, Pin};

/// Address-sensitive: `ptr` points into `buf` in the same value.
struct SelfRef { buf: [u8; 4], ptr: *const u8, _p: PhantomPinned }

impl SelfRef {
    fn new(v: u8) -> Self { SelfRef { buf: [v; 4], ptr: std::ptr::null(), _p: PhantomPinned } }

    /// Write the self-pointer only after the value is pinned.
    fn init(self: Pin<&mut Self>) {
        // SAFETY: no field is moved out; only `ptr` is written.
        let this = unsafe { self.get_unchecked_mut() };
        this.ptr = this.buf.as_ptr();
    }

    /// # Safety
    /// Call only after `init`, and only while the value has not moved.
    unsafe fn read(&self) -> u8 { unsafe { *self.ptr } }
}

fn main() {
    let mut on_stack = pin!(SelfRef::new(0xAA));      // Pin<&mut SelfRef>, no allocation
    on_stack.as_mut().init();
    let mut on_heap = Box::pin(SelfRef::new(0xBB));   // Pin<Box<SelfRef>>, outlives the frame
    on_heap.as_mut().init();
    assert_eq!(unsafe { (on_stack.read(), on_heap.read()) }, (0xAA, 0xBB));
}
```

`Pin::new` on that type fails, and the note names the exact bound:

```text
error[E0277]: `PhantomPinned` cannot be unpinned
     |              -------- ^^^^^^ within `SelfRef`, the trait `Unpin` is not implemented for `PhantomPinned`
     = note: consider using the `pin!` macro
             consider using `Box::pin` if you need to access the pinned value outside of the current scope
note: required because it appears within the type `SelfRef`
note: required by a bound in `Pin::<Ptr>::new`
1159 | impl<Ptr: Deref<Target: Unpin>> Pin<Ptr> {
```

`pin!` anchors the value in a temporary of the **enclosing function frame**. Pass the `Pin<&mut T>`
down as an argument. Do not return it: `fn escape() -> Pin<&'static mut u32> { pin!(5u32) }` gives
`error[E0515]: cannot return value referencing temporary value`, with the note `returns a value
referencing data owned by the current function`. Use `Box::pin` to outlive the frame.

`Pin<&mut T>` is not `Copy`. The compiler reborrows `&mut T` implicitly. It does not reborrow a
`Pin<&mut T>`, which is an ordinary struct, so every call to a `self: Pin<&mut Self>` method
consumes the pin:

```text
error[E0382]: use of moved value: `p`
   |         ----- move occurs because `p` has type `Pin<&mut S>`, which does not implement the `Copy` trait
14 |     println!("{}", p.step());
   |                      ------ `p` moved due to this method call
help: consider reborrowing the `Pin` instead of moving it
14 |     println!("{}", p.as_mut().step());
```

Call `.as_mut()` before every such call except the last, and declare the binding `let mut p`.

## Never pin a named stack binding

`Pin::new_unchecked(&mut local)` commits the **value** for the rest of its life, not for the
lifetime of the `Pin`. The `Pin` is an ordinary value that holds an ordinary `&mut`. Its drop
releases the borrow, and the borrow checker then gives by-value access back to the local:

```rust,ignore
fn make() -> SelfRef {
    let mut s = SelfRef::new(0xAA);
    unsafe { Pin::new_unchecked(&mut s) }.init();   // establishes the self-pointer
    s     // moving it out compiles with zero warnings, and is undefined behaviour
}
```

`cargo build` reports no error and no warning on that function. Miri finds it. The allocation id
changes on every run; the shape does not:

```text
$ cargo +nightly miri run --bin stackescape
error: Undefined Behavior: memory access failed: alloc182 has been freed, so this pointer is dangling
  --> src/bin/stackescape.rs:12:44
12 |     unsafe fn read(&self) -> u8 { unsafe { *self.ptr } }
   |                                            ^^^^^^^^^ Undefined Behavior occurred here
help: alloc182 was allocated here:
16 |     let mut s = SelfRef::new(0xAA);
help: alloc182 was deallocated here:
19 | }
```

- Never call `Pin::new_unchecked` on a binding you can still name. Use `std::pin::pin!`, which
  puts the value in an unnameable temporary, or `Box::pin`, which owns it. `Drop::drop` is the
  one exception: there the value is never used again after the call.
- Reach for `Pin::new_unchecked` only on a pointer you own for the whole life of the value.
- Run the tests under Miri. `cargo build` and `cargo test` both accept this defect.

## Never hand-roll a stack pinning macro

Tutorials show a two-line `macro_rules! pin` that shadows the caller's binding. As they give it,
the macro does not compile at a safe call site:

```text
error[E0133]: call to unsafe function `Pin::<Ptr>::new_unchecked` is unsafe and requires unsafe block
 7 |         let mut $name = Pin::new_unchecked(&mut $name);
   |                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ call to unsafe function
13 |     pin_hand!(a);
   |     ------------ in this macro invocation
```

The reflex fix is worse than the defect, because it compiles. Wrapping the **invocation** in
`unsafe { ... }` scopes the shadowing `let` to that block. The shadow dies at the closing brace,
the original binding comes back, and the value moves out:

```rust
use std::pin::Pin;

struct S { n: u32 }

macro_rules! pin_hand {
    ($name:ident) => {
        let mut $name = Pin::new_unchecked(&mut $name);
    };
}

fn takes_by_value(s: S) -> u32 { s.n }

fn main() {
    let mut a = S { n: 1 };
    unsafe { pin_hand!(a); }        // the shadow dies at this brace
    let n = takes_by_value(a);      // `a` is still an `S`, and still movable
    assert_eq!(n, 1);
}
```

That program compiles with two `unused` warnings and runs. The pin guarantee is gone. Use
`std::pin::pin!`: it keeps the `unsafe` inside the macro body around the call only, and it binds
a temporary that no name reaches again.

## Structural pinning: the four obligations

A pinning projection is a method with the shape `Pin<&mut Self> -> Pin<&mut Field>`. It declares
the field **structurally pinned**: the field is pinned whenever the struct is. Write it with
`Pin::map_unchecked_mut`. A field that is not structurally pinned projects to a plain `&mut`
through `Pin::get_unchecked_mut`. Choose per field, and state the choice in the `SAFETY:`
comment:

```rust
use std::pin::Pin;

pub struct Pair<A, B> { first: A, second: B }

impl<A, B> Pair<A, B> {
    pub fn first(self: Pin<&mut Self>) -> Pin<&mut A> {
        // SAFETY: `first` is structurally pinned. This type has no manual `Drop`,
        // no manual `Unpin` impl, is not `#[repr(packed)]`, and no method of it
        // moves out of `first`.
        unsafe { self.map_unchecked_mut(|s| &mut s.first) }
    }

    pub fn second(self: Pin<&mut Self>) -> &mut B {
        // SAFETY: `second` is not structurally pinned, so `&mut` to it is free.
        // No projection of this type returns `Pin<&mut B>`.
        unsafe { &mut self.get_unchecked_mut().second }
    }
}

fn main() {
    let mut p = std::pin::pin!(Pair { first: 1u32, second: String::new() });
    p.as_mut().second().push('x');
    assert_eq!(*p.as_mut().first(), 1);
}
```

The choice creates four obligations. Break one, and safe callers get undefined behaviour.

### Obligation 1: structural Unpin

The struct may be `Unpin` only when every structurally pinned field is `Unpin`. The auto impl
already does that. The defect is a hand-written one:

```rust,ignore
impl<T> Wrapper<T> {
    fn inner(self: Pin<&mut Self>) -> Pin<&mut T> {
        unsafe { self.map_unchecked_mut(|w| &mut w.inner) }
    }
}
impl<T> Unpin for Wrapper<T> {}   // one safe line, and the program is unsound
```

`impl Unpin` needs no `unsafe`, so this line passes an `unsafe`-focused review. It makes
`Pin::get_mut` safe for `Wrapper<T>`, and safe callers then swap pinned data. The triggering
line holds no `unsafe`: `mem::swap(a.as_mut().get_mut(), b.as_mut().get_mut())`.

```text
$ cargo +nightly miri run --bin badunpin
error: Undefined Behavior: memory access failed: allocN has been freed, so this pointer is dangling
13 |     unsafe fn read(&self) -> u8 { unsafe { *self.ptr } }
```

Never write `impl Unpin` by hand on a type that has a pinning projection. Delete the impl, and
let the auto trait decide.

### Obligation 2: pinned destruction

`fn drop(&mut self)` receives `&mut self` even for a value that was pinned. It is as if the
compiler called `Pin::get_unchecked_mut` for you. A destructor can therefore move a structurally
pinned field out, in plain safe code:

```rust,ignore
impl Drop for Wrapper {
    fn drop(&mut self) {
        // safe code, and it moves a structurally pinned field out of pinned storage
        STOLEN.set(Some(mem::replace(&mut self.inner, SelfRef::new(0))));
    }
}
```

`cargo +nightly miri run --bin dropmove` then reports `error: Undefined Behavior: memory access
failed: allocN has been freed, so this pointer is dangling` at the next read of the self-pointer.

Write the destructor as if the receiver were `Pin<&mut Self>`. Both macros enforce that: a manual
`impl Drop` beside a projection macro gives `error[E0119]: conflicting implementations of trait
MustNotImplDrop for type S<_>` from `pin-project-lite`, and the same error on `SMustNotImplDrop`
from `pin-project`, which prefixes the struct name. Use `PinnedDrop`. For a hand-written type, put
the body in an inner function that takes the pin. `references/pin-projection-macros.md` has both.

The same obligation rules out `#[repr(packed)]`. Drop glue for a packed struct may copy a field
to an aligned scratch location before it drops it, which moves pinned data. rustc gives no
protection: `unsafe { Pin::new_unchecked(&mut packed) }` compiles with no diagnostic at all.
`pin-project` rejects it outright: `error: #[pin_project] attribute may not be used on
#[repr(packed)] types`. `pin-project-lite` has no packed check. Its helper only forbids an
unaligned reference, so `error[E0793]: reference to field of packed struct is unaligned` comes
only when a field needs alignment above 1. A packed struct of 1-byte fields projects in silence.

### Obligation 3: notice of destruction

`Pin` is not only "no `&mut T` in safe code". For a `!Unpin` target it also guarantees that the
storage is not deallocated, overwritten, or repurposed until the destructor of the value has run
or panicked. Intrusive designs, such as a waiter queue that links a future into a list by
address, depend on exactly this half. Three shapes break it, and none of them frees memory in an
obvious way:

- `Pin<Box<ManuallyDrop<T>>>` projected down to `Pin<&mut T>`. `ManuallyDrop` inhibits the
  destructor, so it never runs. `std` states that this can never be made sound.
- An `Option` that holds a pinned value and is then set to `None`.
- `Vec::set_len`, used to shrink a `Vec` that holds pinned values. The elements above the new
  length are never destructed, and their storage becomes reusable.

Unsafe code that manages its own storage must call `ptr::drop_in_place` before it frees or
reuses that storage. A destructor that can panic part way through, and so skip the remaining
destructors, must abort the process instead. See `rust-panic-safety`.

### Obligation 4: no move-out operation

If any operation you expose can move the field out of a pinned value, that field cannot be
structurally pinned. `Option::take`, `mem::replace`, and `mem::swap` are the three that catch
people. The type system does the work once the projection returns `Pin<&mut Option<F>>`, because
`Pin<Ptr>` implements `DerefMut` only for an `Unpin` target:

```rust,compile_fail
use pin_project_lite::pin_project;
use std::pin::Pin;

pin_project! { struct WithPin<F> { #[pin] fut: Option<F> } }

fn steal<F>(s: Pin<&mut WithPin<F>>) -> Option<F> {
    s.project().fut.take()      // E0596
}
```

```text
error[E0596]: cannot borrow data in dereference of `Pin<&mut Option<F>>` as mutable
   |     s.project().fut.take()
   |     ^^^^^^^^^^^^^^^ cannot borrow as mutable
   = help: trait `DerefMut` is required to modify through a dereference, but it is not
           implemented for `Pin<&mut Option<F>>`
```

Delete the `#[pin]` attribute, and the identical body compiles, because the projection then
hands out `&mut Option<F>`. One attribute is the whole difference between a compile error and a
silent move of pinned data. The same `E0596` guards `mem::swap` on two `Pin<&mut S>` values.

## The projection macros

Write the projection with a macro. A hand-written `map_unchecked_mut` is correct only while all
four obligations stay true, and nothing in the build checks that for you. Take
`pin-project-lite` in a library, in a workspace that watches build time, and on any embedded or
cross-compiled target: it is a `macro_rules!` crate with no dependencies. Take `pin-project`
when you need `#[pin_project(project_replace = Owned)]` or the `#[pin_project(!Unpin)]` marker.
`references/pin-projection-macros.md` has the full comparison.

```rust
use pin_project_lite::pin_project;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll, Waker};

pin_project! {
    /// Counts how many times the inner future is polled.
    pub struct Counted<F> {
        #[pin]
        inner: F,      // structurally pinned: `Future::poll` needs `Pin<&mut F>`
        polls: u32,    // not pinned: `&mut u32` is enough
    }
}

impl<F: Future> Future for Counted<F> {
    type Output = (F::Output, u32);
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();      // Pin<&mut F> for `inner`, &mut u32 for `polls`
        *this.polls += 1;
        match this.inner.poll(cx) {
            Poll::Ready(v) => Poll::Ready((v, *this.polls)),
            Poll::Pending => Poll::Pending,
        }
    }
}

fn main() {
    let mut fut = Box::pin(Counted { inner: std::future::ready(7u8), polls: 0 });
    let mut cx = Context::from_waker(Waker::noop());
    assert_eq!(fut.as_mut().poll(&mut cx), Poll::Ready((7, 1)));
}
```

Both macros replace the auto `Unpin` impl with one that reads the `#[pin]` fields alone. A
`PhantomPinned` field without `#[pin]` therefore leaves the struct `Unpin`, and safe callers get
`Pin::get_mut` back. This compiles:

```rust
use pin_project_lite::pin_project;
use std::marker::PhantomPinned;

pin_project! { struct Forgot { _p: PhantomPinned } }   // no #[pin]

fn assert_unpin<T: Unpin>() {}

fn main() {
    assert_unpin::<Forgot>();   // the struct is Unpin: the attribute was forgotten
}
```

The same struct without the macro is `!Unpin`. Add `#[pin]`, and the assertion fails with
`error[E0277]: PhantomPinned cannot be unpinned ... within __Origin<'_>`. Mark every
address-sensitive field with `#[pin]`, and hold the result with a compile-fail test.

## Your own pinning pointer type

`Pin<P>` pins `P::Target` only when `P` is a real indirection. A `struct Inline<T>(T)` whose
`Deref` returns `&self.0` keeps the target inline, so a move of the `Pin<P>` value moves the
"pinned" data with it. Miri reports a dangling read on a program whose only move is the
`Pin<Inline<T>>` leaving its builder. `references/pin-projection-macros.md` has the code. So,
for a pointer type that a caller may wrap in `Pin`:

- `Deref::Target` must live behind a real indirection, at an address that survives a move of the
  pointer.
- `Deref` and `DerefMut` must not move out of the pointee, and must not invalidate it.
- `Drop` must not move out of the pointee, and must run its destructor before it frees storage.

## Checklist

- Every `Pin` in a signature sits on a `!Unpin` type, or a trait forces it.
- Every address-sensitive type has a `PhantomPinned` field.
- No `Pin::new_unchecked` call outside `Drop::drop` takes `&mut` to a nameable binding. Stack
  pinning uses `std::pin::pin!`, and no hand-written pinning macro exists in the tree.
- A pinned value that must outlive the frame uses `Box::pin`.
- Repeated calls on a `Pin<&mut Self>` receiver use `.as_mut()`.
- No hand-written `impl Unpin` sits next to a pinning projection.
- No manual `impl Drop` sits on a type with a structurally pinned field. `PinnedDrop` does.
- No pinned type is `#[repr(packed)]`. `pin-project-lite` does not catch every packed case.
- No projection exposes `take`, `replace`, or `swap` on a structurally pinned field.
- Every `#[pin]` attribute is present. An `assert_unpin` test proves the result.
- Every `map_unchecked_mut` and `get_unchecked_mut` call carries a `SAFETY:` comment that names
  the field and the choice.
- The tests for this code run under Miri in CI.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-async-internals` | This skill covers `Pin` itself. `rust-async-internals` covers polling, `select!`, cancel safety, and the manual poll bridge that uses `Pin::new` on an `Unpin` stream |
| `rust-unsafe` | The `SAFETY:` comment discipline for `map_unchecked_mut` and `get_unchecked_mut`, and the `#[repr(packed)]` alignment rules behind E0793 |
| `rust-sanitizers-miri` | Running the Miri jobs that catch every defect on this page, and the flags they need |
| `rust-macros` | `macro_rules!` hygiene and scope, which is why a shadowing pin macro breaks |
| `rust-panic-safety` | A destructor that panics part way through, which is how obligation 3 fails |
