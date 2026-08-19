# Projection macros, pinned destructors, and pinning pointers

Deep material for `rust-pin-projection`. Read `SKILL.md` first: it holds the decision gate, the
three ways to pin a value, and the four structural pinning obligations.

Measured on rustc 1.97.0, edition 2024, aarch64-apple-darwin, with pin-project 1.1.13 and
pin-project-lite 0.2.17.

## Choose the crate

| | `pin-project` | `pin-project-lite` |
| --- | --- | --- |
| Kind | proc macro, `#[pin_project]` | `macro_rules!`, `pin_project! { ... }` |
| Dependency tree | `syn`, `quote`, `proc-macro2` | none |
| Compile cost | one proc-macro crate to build first | none |
| Structs | yes | yes |
| Enums | yes, with `#[pin_project(project = Name)]` | yes, with `#[project = Name]` |
| Pinned destructor | `#[pin_project(PinnedDrop)]` plus `#[pinned_drop]` | `impl PinnedDrop` inside the macro body |
| `#[repr(packed)]` | rejected outright, dedicated message | `E0793` only when a field needs alignment above 1 |
| Replace and take the old value | `#[pin_project(project_replace = Owned)]` | no |
| Explicit `!Unpin` marker | `#[pin_project(!Unpin)]` | add a `#[pin] PhantomPinned` field |
| Named projection type | `#[pin_project(project = Name)]` | `#[project = Name]` |

Take `pin-project-lite` by default. Take `pin-project` when you need `project_replace` or the
`!Unpin` marker. Both crates name the projection type on request, so that is not a reason to
pick one.

Both crates emit an `Unpin` impl conditioned on the `#[pin]` fields alone. That impl is more
permissive than the auto-derived one, which is the trap in `SKILL.md`.

## Prove the Unpin result with a test

A forgotten `#[pin]` attribute is silent. `fn assert_unpin<T: Unpin>() {}` states the result in
one line, and the direction of the test decides where it goes.

A type that you promise is `Unpin` takes a normal unit test:

```rust
use pin_project_lite::pin_project;

pin_project! { pub struct Buf { #[pin] inner: Vec<u8> } }

fn assert_unpin<T: Unpin>() {}

fn main() { assert_unpin::<Buf>(); }   // fails to compile if `inner` becomes !Unpin
```

A type that must stay `!Unpin` needs the opposite: the assertion has to fail. Put it in a
`compile_fail` doctest or a `trybuild` case, never in a normal test:

```rust,compile_fail
use pin_project_lite::pin_project;
use std::marker::PhantomPinned;

pin_project! { struct Marked { #[pin] _p: PhantomPinned } }

fn assert_unpin<T: Unpin>() {}

fn main() { assert_unpin::<Marked>(); }
```

The failure text names the generated origin type, which is how you tell a macro-derived `Unpin`
from the auto one:

```text
error[E0277]: `PhantomPinned` cannot be unpinned
  | fn main() { assert_unpin::<Marked>(); }
  |                            ^^^^^^ within `__Origin<'_>`, the trait `Unpin` is not implemented for `PhantomPinned`
  = note: consider using the `pin!` macro
          consider using `Box::pin` if you need to access the pinned value outside of the current scope
note: required because it appears within the type `__Origin<'_>`
note: required for `Marked` to implement `Unpin`
  = note: this error originates in the macro `$crate::__pin_project_make_unpin_impl`
```

## PinnedDrop with pin-project-lite

Put the impl inside the macro body. The receiver is `Pin<&mut Self>`, so no field can move out:

```rust
use pin_project_lite::pin_project;
use std::pin::Pin;

pin_project! {
    pub struct Conn<S> {
        #[pin]
        stream: S,
        id: u32,
    }
    impl<S> PinnedDrop for Conn<S> {
        fn drop(this: Pin<&mut Self>) {
            let this = this.project();
            println!("closing {}", this.id);
        }
    }
}

fn main() {
    drop(Box::pin(Conn { stream: (), id: 7 }));   // prints: closing 7
}
```

## PinnedDrop with pin-project

Pass `PinnedDrop` to the attribute, then write a separate `#[pinned_drop]` impl:

```rust,ignore
use pin_project::{pin_project, pinned_drop};
use std::pin::Pin;

#[pin_project(PinnedDrop)]
pub struct Conn<S> {
    #[pin]
    stream: S,
    id: u32,
}

#[pinned_drop]
impl<S> PinnedDrop for Conn<S> {
    fn drop(self: Pin<&mut Self>) {
        let this = self.project();
        println!("closing {}", this.id);
    }
}
```

A plain `impl Drop` beside either macro is a compile error. The message names a generated marker
trait, and the name differs per crate:

```text
$ cargo build --bin ppdrop            # pin-project
error[E0119]: conflicting implementations of trait `SMustNotImplDrop` for type `S<_>`

$ cargo build --bin plitedrop         # pin-project-lite
error[E0119]: conflicting implementations of trait `MustNotImplDrop` for type `S<_>`
```

## Pinned destruction without a macro

For a hand-written address-sensitive type, put the real destructor body in an inner function that
takes the pin. The signature then stops you from moving a field out:

```rust
use std::pin::Pin;

struct Conn { id: u32 }

impl Drop for Conn {
    fn drop(&mut self) {
        // SAFETY: the value is never used again after `drop` returns.
        inner_drop(unsafe { Pin::new_unchecked(self) });

        fn inner_drop(this: Pin<&mut Conn>) {
            // The real destructor body. It cannot move a field out.
            assert!(this.id > 0);
        }
    }
}

fn main() { drop(Conn { id: 1 }); }
```

## repr(packed): only one crate rejects it

`#[pin_project]` carries a dedicated check. It fires on every packed struct:

```text
error: #[pin_project] attribute may not be used on #[repr(packed)] types
4 | #[repr(packed)]
  |        ^^^^^^
```

`pin_project_lite::pin_project!` has no such check. It emits a
`#[forbid(unaligned_references, safe_packed_borrows)] fn __assert_not_repr_packed` helper that takes
a reference to every field. The lint fires only when a field needs alignment above 1:

```text
error[E0793]: reference to field of packed struct is unaligned
4 | / pin_project! {
5 | |     #[repr(packed)]
6 | |     struct S { #[pin] p: PhantomPinned, n: u64 }
7 | | }
  = note: this struct is 1-byte aligned, but the type of this field may require higher alignment
  = note: this error originates in the macro `$crate::__pin_project_struct_make_proj_method`
```

Change `n: u64` to `n: u8`, and every field is 1-byte aligned. The lint stays quiet, the struct
compiles, and `.project()` hands out `Pin<&mut PhantomPinned>` for the packed field. Do not treat
`pin-project-lite` as a guard against `#[repr(packed)]`. Reject packed layouts yourself.

Neither check reaches a hand-written projection. `unsafe { Pin::new_unchecked(&mut packed) }`
compiles with no diagnostic at all.

## Assign into a pinned value

`Pin::<Ptr>::set` needs only `Ptr: DerefMut`, with no `Unpin` bound. It is safe because it drops
the old value in place before it writes the new one, which keeps the drop guarantee:

```rust
use std::marker::PhantomPinned;
use std::pin::pin;

struct S { id: u32, _p: PhantomPinned }

impl Drop for S {
    fn drop(&mut self) { println!("drop {}", self.id); }
}

fn main() {
    let mut p = pin!(S { id: 1, _p: PhantomPinned });
    p.set(S { id: 2, _p: PhantomPinned });   // safe: drops the old S in place first
    assert_eq!(p.id, 2);
}
```

The program prints `drop 1`, then `drop 2`. Use `Pin::set` instead of
`unsafe { get_unchecked_mut() }` plus an assignment.

## A pinning pointer that pins nothing

`Pin<P>` promises a stable address for `P::Target`. The promise is empty when `P` stores the
target inline, because moving the `Pin<P>` value moves the target too:

```rust,ignore
struct Inline<T>(T);                        // not a pointer: T lives inline
impl<T> Deref for Inline<T> { type Target = T; fn deref(&self) -> &T { &self.0 } }
impl<T> DerefMut for Inline<T> { fn deref_mut(&mut self) -> &mut T { &mut self.0 } }

fn build() -> Pin<Inline<SelfRef>> {
    let mut p = unsafe { Pin::new_unchecked(Inline(SelfRef::new(0xAA))) };
    p.as_mut().init();
    p            // moves the "pinned" SelfRef, and that is undefined behaviour
}
```

```text
$ cargo +nightly miri run --bin derefinline
error: Undefined Behavior: memory access failed: allocN has been freed, so this pointer is dangling
  --> src/bin/derefinline.rs:13:44
13 |     unsafe fn read(&self) -> u8 { unsafe { *self.ptr } }
   |                                            ^^^^^^^^^ Undefined Behavior occurred here
help: allocN was deallocated here:
24 | }
```

The only move in that program is `p` leaving `build`. `Box<T>`, `Rc<T>`, and `Arc<T>` are sound
pinning pointers because the target lives in an allocation that a move of the pointer does not
touch.
