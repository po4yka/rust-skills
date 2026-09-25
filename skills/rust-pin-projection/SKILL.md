---
name: rust-pin-projection
description: Use when adding Pin to a signature, writing a self-referential struct or other address-sensitive type, or projecting a pinned reference into a field (pin projection, structural pinning) by hand or with pin-project or pin-project-lite. Also for choosing between std::pin::pin!, Box::pin, and Pin::new_unchecked; PhantomPinned and Unpin semantics; PinnedDrop; and pin errors such as "PhantomPinned cannot be unpinned", E0596 "cannot borrow data in dereference of Pin", or an E0308 that names unreachable_pin_macro_type_constraint. Not for polling, wakers, or cancel safety; use rust-async-internals.
license: BSD-3-Clause
---

# Rust pin projection

`Pin<&mut T>` enforces nothing when `T: Unpin`, and `!Unpin` never makes a type unmovable. The
restriction starts at the pin, and it applies only to a `!Unpin` type.

The diagnostics below come from rustc 1.98.1, edition 2024, pin-project 1.1.13, and
pin-project-lite 0.2.17. The Miri output comes from nightly 2026-05-15 with the default Stacked
Borrows model.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| You are about to write `self: Pin<&mut Self>` | [Pin enforces nothing for an Unpin target](#pin-enforces-nothing-for-an-unpin-target) |
| `PhantomPinned`, or a claim that a type "cannot move" | [Unpin does not mean movable](#unpin-does-not-mean-movable) |
| `error[E0277]: PhantomPinned cannot be unpinned` | [Get a value pinned](#get-a-value-pinned) |
| `error[E0515]` or `error[E0716]` at a `pin!` | [How long a pin! value lives](#how-long-a-pin-value-lives) |
| `error[E0308]` that names `unreachable_pin_macro_type_constraint` | [pin! of a &mut reference](#pin-of-a-mut-reference) |
| `error[E0382]: use of moved value` on a `Pin<&mut T>` | [Reborrow before each call](#reborrow-before-each-call) |
| Miri: `allocN has been freed, so this pointer is dangling` | [Never pin a named stack binding](#never-pin-a-named-stack-binding) |
| Miri: `tag does not exist in the borrow stack`, invalidated by a `mem::swap` | [Obligation 1](#obligation-1-structural-unpin) |
| `error[E0133]` from a `macro_rules!` that calls `Pin::new_unchecked` | [Never hand-roll a stack pinning macro](#never-hand-roll-a-stack-pinning-macro) |
| You wrote `impl<T> Unpin for MyType<T> {}` | [Obligation 1](#obligation-1-structural-unpin) |
| You wrote `impl Drop`, or `#[repr(packed)]`, on a type with a pinned field | [Obligation 2](#obligation-2-pinned-destruction) |
| A pinned value sits in `ManuallyDrop`, or its storage is overwritten or freed before its destructor runs | [Obligation 3](#obligation-3-notice-of-destruction) |
| `error[E0596]: cannot borrow data in dereference of Pin<&mut T> as mutable` | [Obligation 4](#obligation-4-no-move-out-operation) |
| You choose between `pin-project` and `pin-project-lite` | [The projection macros](#the-projection-macros) |
| You write a smart pointer that a caller may wrap in `Pin` | [Your own pinning pointer type](#your-own-pinning-pointer-type) |
| You must overwrite a pinned value | Use `Pin::set`: it is safe and drops the old value in place. Read `references/pin-projection-macros.md` (section "Assign into a pinned value") for the example |
| You must prove a pinned type sound, or stay `!Unpin` | [Verify](#verify) |
| You review code that pins or projects | Read `references/pin-projection-macros.md` (section "Review checklist") |

## Verify

| Claim | Check | What a pass does not prove |
| --- | --- | --- |
| No pinned value moves, is overwritten, or loses its destructor | When a nightly toolchain with the `miri` component is installed, run `cargo +nightly miri test --locked` on the crate that holds `Pin::new_unchecked`, `map_unchecked_mut`, `get_unchecked_mut`, a manual `Unpin`, or a manual `Drop` on a pinned type. Run it before you merge a change to a type that pins or projects, and in CI for that crate. Without Miri, report the pinning code as not checked by Miri | Paths the tests do not run. A pinning defect stays silent until code uses a stored pointer to the pinned value, so a test must pin the value, store the pointer (a self-reference or an intrusive link), do the operation under test (move, swap, drop, overwrite), and then use the pointer |
| An address-sensitive type stays `!Unpin` | A `compile_fail` doctest, or a `trybuild` case, that calls `assert_unpin::<T>()`. Read `references/pin-projection-macros.md` (section "Prove the Unpin result with a test") when you write the test | A `compile_fail` doctest passes on any compile error, a typo included. `trybuild` compares the full error text |
| A type you promise is `Unpin` stays `Unpin` | A normal test that calls `assert_unpin::<T>()`, as in the same reference section | Anything about soundness |
| The code builds | `cargo build`, `cargo test`, `cargo clippy` | Pin soundness. All four Miri examples on this page and in the reference build with no warning |

A change that pins or projects is complete when the Miri row passes (or the report says that Miri
did not run), the `Unpin` tests hold, and every item of the review checklist in
`references/pin-projection-macros.md` holds. The `rust-sanitizers-miri` skill, when it is
installed, owns the Miri flags and the Stacked Borrows and Tree Borrows policy.

## Pin enforces nothing for an Unpin target

Check this before you add `Pin` to any signature. `Pin::new` and `Pin::get_mut` are both safe
for an `Unpin` target, and `Pin<Ptr>` implements `DerefMut` for one, so safe code moves the value
out through any of them.

- Write `Pin` in a signature only when the type is `!Unpin`, or when a trait such as `Future`
  forces the receiver. Otherwise take `&mut self`.
- Add a `PhantomPinned` field to the type whose address must stay stable. That one field
  removes the auto `Unpin` impl and turns the API from documentation into enforcement.

## Unpin does not mean movable

`Unpin` is not `Movable`, and `!Unpin` is not `Unmovable`. Every Rust type moves, `!Unpin`
included: assignment, `mem::swap` through `&mut`, `Box::new`, and `vec![..]` all move a
`PhantomPinned` type with no `unsafe` and no warning. No move check reads `Unpin`. Only trait
bounds read it: `Pin::new`, `Pin::get_mut`, `DerefMut for Pin<Ptr>`, and impls such as
`Future for &mut F`. Read `T: !Unpin` as "once a value is pinned, safe code cannot reach `&mut T`
again".
Read `references/pin-projection-macros.md` (section "Moves that Pin does not stop") when a design
depends on a type that "cannot move", or a review needs the moves shown.

## Get a value pinned

| Constructor | Result | Unsafe | Escapes the frame | Allocates |
| --- | --- | --- | --- | --- |
| `std::pin::pin!(value)` | `Pin<&mut T>` | no | no | no |
| `Box::pin(value)` | `Pin<Box<T>>` | no | yes | yes |
| `Pin::new(&mut value)` | `Pin<&mut T>` | no, needs `T: Unpin` | no | no |
| `unsafe { Pin::new_unchecked(&mut value) }` | `Pin<&mut T>` | yes | no | no |

`std::pin::pin!` is stable since 1.68. It needs no crate and no feature gate.

```rust,run
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

`Pin::new` on that type fails with ``error[E0277]: `PhantomPinned` cannot be unpinned`` and the
advice to use `pin!` or `Box::pin`. Take that advice. Do not reach for `Pin::new_unchecked`.

## Never pin a named stack binding

`Pin::new_unchecked(&mut local)` commits the **value** for the rest of its life, not for the
lifetime of the `Pin`. The `Pin` is an ordinary value that holds an ordinary `&mut`. Its drop
releases the borrow, and the borrow checker then gives by-value access back to the local:

```rust
use std::pin::Pin;

fn make() -> SelfRef {
    let mut s = SelfRef::new(0xAA);
    unsafe { Pin::new_unchecked(&mut s) }.init();   // establishes the self-pointer
    s     // moving it out compiles with zero warnings, and is undefined behaviour
}
```

`cargo build`, `cargo test`, and `cargo clippy -- -W clippy::pedantic` accept that function with no
diagnostic. Miri reports `allocN has been freed, so this pointer is dangling` at the read through
the self-pointer after the move. Read `references/pin-projection-macros.md` (section "A named
stack binding under Miri") when you must match the full Miri report.

- Never call `Pin::new_unchecked` on a binding you can still name, because safe code moves it
  after the `Pin` drops. Use `std::pin::pin!`, which puts the value in an unnameable temporary,
  or `Box::pin`, which owns it. `Drop::drop` is the one exception: there the value is never used
  again after the call.
- Call `Pin::new_unchecked` only on a pointer you own for the whole life of the value.

### Never hand-roll a stack pinning macro

A tutorial `macro_rules!` that shadows the caller's binding with
`let mut $name = Pin::new_unchecked(&mut $name);` fails with `E0133` at a safe call site. The
obvious fix, `unsafe { pin_hand!(a); }`, compiles and is worse: the shadow dies at the closing
brace, and the original binding moves out. Delete such a macro and use `std::pin::pin!`. Read
`references/pin-projection-macros.md` (section "A hand-rolled pinning macro") when you must
explain the failure in a review.

## Structural pinning: the four obligations

A pinning projection is a method with the shape `Pin<&mut Self> -> Pin<&mut Field>`. It declares
the field **structurally pinned**: the field is pinned whenever the struct is. Write it with
`Pin::map_unchecked_mut`. A field that is not structurally pinned projects to a plain `&mut`
through `Pin::get_unchecked_mut`. Choose per field, and state the choice in the `SAFETY:`
comment:

```rust,run
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

```rust
use std::pin::Pin;

struct Wrapper<T> { inner: T }

impl<T> Wrapper<T> {
    fn inner(self: Pin<&mut Self>) -> Pin<&mut T> {
        // SAFETY: claims `inner` is structurally pinned. The impl below breaks the claim.
        unsafe { self.map_unchecked_mut(|w| &mut w.inner) }
    }
}

impl<T> Unpin for Wrapper<T> {}   // one safe line, and the program is unsound
```

`impl Unpin` needs no `unsafe`, so this line passes an `unsafe`-focused review. It makes
`Pin::get_mut` safe for `Wrapper<T>`, and safe callers then swap pinned data with
`mem::swap(a.as_mut().get_mut(), b.as_mut().get_mut())`. Miri reports `allocN has been freed, so
this pointer is dangling` at the next read of the self-pointer after the swapped partner drops.
When the read comes directly after the swap, it reports `tag does not exist in the borrow stack
for this location` and names the `mem::swap` line as the write access that invalidated the tag.

Never write `impl Unpin` by hand on a type that has a pinning projection. Delete the impl, and
let the auto trait decide.

### Obligation 2: pinned destruction

`fn drop(&mut self)` receives `&mut self` even for a value that was pinned. A destructor can
therefore move a structurally pinned field out in plain safe code, for example with
`mem::replace`, and Miri reports a dangling self-pointer at the next read.

Write the destructor as if the receiver were `Pin<&mut Self>`. Both macros enforce that: a manual
`impl Drop` beside a projection macro gives `error[E0119]: conflicting implementations of trait`
on a generated `MustNotImplDrop` trait (`pin-project` prefixes the struct name). Use
`PinnedDrop`. For a hand-written type, put the body in an inner function that takes the pin. Read
`references/pin-projection-macros.md` (sections "A destructor that moves a pinned field" to
"Pinned destruction without a macro") when you write or review a destructor on a pinned type.

The same obligation rules out `#[repr(packed)]`: drop glue for a packed struct can move a field to
an aligned place before it drops it. rustc does not warn, and `pin-project-lite` rejects a packed
struct only when a field needs alignment above 1 (`E0793`). Reject packed layouts yourself. Read
`references/pin-projection-macros.md` (section "repr(packed): only one crate rejects it") when a
pinned type is packed.

### Obligation 3: notice of destruction

For a `!Unpin` target, `Pin` also guarantees that the storage is not deallocated, overwritten, or
repurposed until the destructor of the value has run or panicked. Intrusive designs, such as a
waiter queue that links futures by address, depend on this half. Three shapes break it, and none
frees memory in an obvious way:

- `Pin<Box<ManuallyDrop<T>>>` projected down to `Pin<&mut T>`. `ManuallyDrop` inhibits the
  destructor, so it never runs. `std` states that this can never be made sound.
- An `Option` that holds a pinned value and is overwritten with `None` without running the
  destructor of the value, for example through `ptr::write`. `Pin::set(None)` is sound: it
  drops the old value in place.
- `Vec::set_len`, used to shrink a `Vec` that holds pinned values. The elements above the new
  length are never destructed, and their storage becomes reusable.

Unsafe code that manages its own storage must call `ptr::drop_in_place` before it frees or
reuses that storage. A destructor that can panic part way through, and so skip the remaining
destructors, must abort the process instead. The `rust-panic-safety` skill, when it is
installed, covers that abort.

### Obligation 4: no move-out operation

If any operation you expose can move the field out of a pinned value, that field cannot be
structurally pinned: `Option::take`, `mem::replace`, and `mem::swap` are the usual ones. The type
system does the work once the projection returns `Pin<&mut Option<F>>`, because `Pin<Ptr>`
implements `DerefMut` only for an `Unpin` target:

```rust,compile_fail,E0596
use pin_project_lite::pin_project;
use std::pin::Pin;

pin_project! { struct WithPin<F> { #[pin] fut: Option<F> } }

fn steal<F>(s: Pin<&mut WithPin<F>>) -> Option<F> {
    s.project().fut.take()      // E0596
}
```

The help line says that `DerefMut` is required to modify through a dereference, but is not
implemented for `Pin<&mut Option<F>>`. Delete the `#[pin]` attribute, and the identical body
compiles, because the projection then hands out `&mut Option<F>`, and the move of pinned data is
silent. The same `E0596` guards `mem::swap` on two `Pin<&mut S>` values.

## The projection macros

Write the projection with a macro. A hand-written `map_unchecked_mut` is correct only while all
four obligations hold, and no build step checks that. Take `pin-project-lite` when the dependency
graph builds no proc-macro crate yet. Take `pin-project` for a tuple struct or tuple variant,
for `UnsafeUnpin`, or for its rejection of every `#[repr(packed)]` struct. Read
`references/pin-projection-macros.md` (section "Choose the crate") when you choose, and for a
complete `Future` that projects one pinned and one unpinned field.

Both macros replace the auto `Unpin` impl with one that reads the `#[pin]` fields alone. A
`PhantomPinned` field without `#[pin]` therefore leaves the struct `Unpin`, and safe callers get
`Pin::get_mut` back, with no diagnostic. The same struct without the macro is `!Unpin`. Add
`#[pin]` to the `PhantomPinned` field, or put `#[project(!Unpin)]` (`pin-project-lite`) or
`#[pin_project(!Unpin)]` (`pin-project`) on the type. Hold that result with a compile-fail test,
as [Verify](#verify) describes.

## Your own pinning pointer type

`Pin<P>` pins `P::Target` only when `P` is a real indirection: a `struct Inline<T>(T)` whose
`Deref` returns `&self.0` moves the "pinned" data with every move of the `Pin<P>`. Read
`references/pin-projection-macros.md` (section "A pinning pointer that pins nothing") when you
write a pointer type that a caller may wrap in `Pin`, for the three rules it must keep.

## Compile errors at a pin

### How long a pin! value lives

`pin!(v)` moves `v` into a temporary. As the `let` initializer, the temporary lives to the end of
the block. As a function argument or a method receiver, it dies at the end of the statement, with
`error[E0716]: temporary value dropped while borrowed` or `error[E0515]: cannot return value
referencing temporary value`. Bind first (`let mut p = pin!(v);`), then pass `p.as_mut()` down.
Use `Box::pin` when the pinned value must outlive the function. Read
`references/pin-projection-macros.md` (section "How long a pin! value lives") when the error names
a `pin!` nested in a tuple, a struct literal, `Some(..)`, or a match arm.

### pin! of a &mut reference

Since Rust 1.97, `pin!(r)` with `r: &mut T` always gives `Pin<&mut &mut T>`. Rustc 1.88 to 1.96
sometimes coerced it to `Pin<&mut T>` and so pinned a value that the caller could still move. A call
such as `takes(pin!(s))` with `s: &mut S` now fails with ``error[E0308]: expected `S`, found
`&mut S` ``, and the help line names `unreachable_pin_macro_type_constraint`.

- Do not fix it with `unsafe { Pin::new_unchecked(s) }`: the caller can still move `*s` after the
  call returns. Take `Pin<&mut S>` so that the owner pins the value, or use `Pin::new(s)` when the
  target is `Unpin`. When the function owns the value, pin the value: `takes(pin!(s))` with `s: S`.
- Never write `pin!(&mut s)`: rustc 1.88 to 1.96 accept it, and safe code then moves the local
  after the pin drops.

### Reborrow before each call

`Pin<&mut T>` is not `Copy`, and the compiler does not reborrow it implicitly, so every call to a
`self: Pin<&mut Self>` method consumes the pin. The second call fails with
``error[E0382]: use of moved value: `p` `` and the help ``consider reborrowing the `Pin` instead
of moving it``. Call `.as_mut()` before every such call except the last, and declare the binding
`let mut p`.

## Related skills

Use these skills, when they are installed:

| Skill | Boundary |
| --- | --- |
| `rust-async-internals` | Polling, `select!`, cancel safety, and the manual poll bridge that uses `Pin::new` on an `Unpin` stream |
| `rust-unsafe` | The general `SAFETY:` comment convention, and the `#[repr(packed)]` alignment rules behind E0793 |
| `rust-macros` | `macro_rules!` hygiene and scope, which is why a shadowing pin macro breaks |
