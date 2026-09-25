---
name: rust-variance
description: Use when a lifetime coercion is refused ("is invariant over the parameter", "borrowed for 'static", "lifetime may not live long enough" on a return or argument), when deciding whether a type is covariant, contravariant, or invariant, or when adding a lifetime parameter, a PhantomData variance marker, or interior mutability to a public type. Also for subtyping questions such as a fn item that fails a trait bound (resize_with), dyn Fn lifetime parameters, and an unbounded lifetime from a raw pointer. Triggers on "variance", "phantomdata variance", "&mut is invariant", "sender is invariant".
license: BSD-3-Clause
---

# Rust variance

The question: does a value that holds `'b` fit where the compiler asks for `'a`, given
`'b: 'a`? The type constructor around the lifetime decides, not the lifetime. Variance belongs to
type constructors only: a trait bound matches by equality, so nothing coerces through it.

Every quoted diagnostic comes from rustc 1.98.1, edition 2024, aarch64-apple-darwin.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| You must know the variance of a type you own | [Settle it with a probe](#settle-it-with-a-probe) |
| `note: the struct X<T> is invariant over the parameter T` | [The variance table](#the-variance-table) |
| `note: mutable references are invariant over their type parameter` | [Settle it with a probe](#settle-it-with-a-probe) |
| An invariant type accepts a shorter lifetime through `dyn` or an array-to-slice change (a `&mut` unsize inside `Cell` needs 1.98; run `cargo +<msrv> check`) | [Settle it with a probe](#settle-it-with-a-probe) |
| A raw-pointer deref returns `&'a T` with no `'a` in the inputs | [Unbounded lifetimes](#unbounded-lifetimes-come-from-a-raw-pointer) |
| `note: raw pointer casts of trait objects cannot extend lifetimes` | [Unbounded lifetimes](#unbounded-lifetimes-come-from-a-raw-pointer) |
| A `Sender`, handle, or queue refuses to coerce | [Coerce the message, not the handle](#coerce-the-message-not-the-handle) |
| You add `Cell`, `RefCell`, or `Mutex` to a published struct (a breaking change; lock it with a `compile_fail` doctest and `cargo test --doc`) | [Variance is public API](#variance-is-public-api) |
| `note: requirement that the value outlives 'static introduced here`, pointing at a trait bound | [Traits match by equality](#traits-match-their-parameters-by-equality) |
| `error[E0597]` at `resize_with`, `map`, or any callback argument | [Traits match by equality](#traits-match-their-parameters-by-equality) |
| `error[E0106]: missing lifetime specifier` on `fn() -> &str` | [Three fixes](#three-fixes-for-a-producer-whose-output-lives-too-long) |
| `lifetime may not live long enough` on a `Box<dyn Fn(&'a T)>` field | [A free lifetime in `dyn Trait`](#a-free-lifetime-in-dyn-trait-makes-it-invariant) |
| `type annotation requires that ... is borrowed for 'static` at a `&mut` argument | [A `&mut` parameter](#a-mut-parameter-pins-the-callers-lifetime) |
| You script probes, or need every exact note, or the worked unsound channel | Read [references/variance-tables.md](references/variance-tables.md) |

## Settle it with a probe

Do not reason about variance. Compile these three one-line functions and read the result.

```rust,ignore
// probe.rs — replace `C` with the type under test, `S` with a type that has a lifetime.
fn cov<'a, 'b: 'a>(x: C<&'b u8>) -> C<&'a u8> { x }   // compiles => covariant in T
fn con<'a, 'b: 'a>(x: C<&'a u8>) -> C<&'b u8> { x }   // compiles => contravariant in T
fn cov_lt<'a, 'b: 'a>(x: S<'b>) -> S<'a> { x }        // compiles => covariant in 'a
```

Run one command. Pass a real output path; `-o /dev/null` fails for an unrelated reason:

```bash
rustc --edition 2024 --crate-type lib --emit=metadata probe.rs -o probe.rmeta
```

| `cov` | `con` | Verdict |
| --- | --- | --- |
| compiles | rejected | covariant in `T` |
| rejected | compiles | contravariant in `T` |
| rejected | rejected | invariant in `T` |

`Vec<T>` passes `cov`. `fn(T)` passes `con`, so a handler for a short-lived argument serves as a
handler for a long-lived one. `Cell<T>` fails both, and rustc names the rule in a note:

```rust,compile_fail
use std::cell::Cell;
fn cov<'a, 'b: 'a>(x: Cell<&'b u8>) -> Cell<&'a u8> { x }
```

```text
error: lifetime may not live long enough
2 | fn cov<'a, 'b: 'a>(x: Cell<&'b u8>) -> Cell<&'a u8> { x }
  = note: requirement occurs because of the type `Cell<&u8>`, which makes the generic argument `&u8` invariant
  = note: the struct `Cell<T>` is invariant over the parameter `T`
```

Two traps make a probe lie.

**A `'static` outer reference.** Never write one into a probe. This compiles, and it proves
nothing, because `&'static mut` forces `&'b u8: 'static` and collapses both lifetimes:

```rust
fn degenerate<'a, 'b: 'a>(x: &'static mut &'b u8) -> &'static mut &'a u8 { x }
```

Use a fresh outer lifetime instead: `fn p<'x, 'a: 'x, 'b: 'a>(x: &'x mut &'b u8) -> &'x mut &'a u8`.
That form is rejected with `note: mutable references are invariant over their type parameter`, which
is the true answer for `&mut T`.

**An unsizing step.** The `{ x }` return is a coercion site. The trap applies when the outermost
probe type is a std pointer or cell that implements `CoerceUnsized` (such as `&`, `&mut`,
`*const`, `*mut`, `NonNull`, `Box`, `Rc`, `Arc`, `Pin`, `Cell`, `RefCell`, `UnsafeCell`) and it
holds `dyn Trait + 'b`. An unsize coercion then shortens the lifetime even in an invariant
position, so `Cell<Box<dyn Debug + 'b>>` coerces to `Cell<Box<dyn Debug + 'a>>`. Rust 1.98 adds
an inner `&'b mut` to the coercions that do this. A compiles verdict then measures the
coercion, not the variance. Wrap such a probe type in `Vec<...>`, which forwards no coercion. A
rejected verdict needs no wrapper. A probe of a type you define needs none either, because a
type of your own cannot implement `CoerceUnsized` on stable. Never let the output differ from
the input in anything but the lifetime (array to slice, `T` to `dyn Trait`). Read
[references/variance-tables.md](references/variance-tables.md) for the per-version table when
code that passes through such a coercion compiles on one toolchain and fails on another.

## The variance table

| Constructor | Variance in `T` | Variance in `'a` |
| --- | --- | --- |
| `&'a T` | covariant | covariant |
| `&'a mut T` | **invariant** | covariant |
| `*const T` | covariant | — |
| `*mut T` | **invariant** | — |
| `Box<T>`, `Vec<T>`, `Rc<T>`, `Arc<T>`, `Option<T>`, `[T; N]`, `(T, U)` | covariant | — |
| `fn() -> T` | covariant | — |
| `fn(T)` | **contravariant** | — |
| `fn(T) -> T` | **invariant** | — |
| `Cell<T>`, `UnsafeCell<T>`, `RefCell<T>`, `Mutex<T>`, `RwLock<T>`, `mpsc::Sender<T>` | **invariant** | — |
| `dyn Trait + 'a` | — | covariant |
| `dyn Fn(&'a T)`, `dyn Fn() -> &'a T` with a free `'a` | — | **invariant** |
| `PhantomData<T>`, `PhantomData<&'a T>`, `PhantomData<fn() -> T>` | covariant | covariant |
| `PhantomData<fn(T)>` | **contravariant** | — |
| `PhantomData<*mut T>`, `PhantomData<Cell<T>>`, `PhantomData<&'a mut T>` | **invariant** | covariant |

Two rules generate the whole table:

- A struct or enum computes variance per parameter from its fields. Uses of one variance keep
  it. Uses of different variances make the parameter **invariant**. One `Cell<T>` field makes the
  whole type invariant in `T`, and so does a `fn() -> T` field next to a `fn(T)` field.
- Everything built on `UnsafeCell<T>` is invariant in `T`, because a shared reference to it
  permits a write. That is `Cell`, `RefCell`, `Mutex`, `RwLock`, `AtomicPtr`, and every channel
  handle in `std`.

A parameter that no field stores needs a `PhantomData` that states the intent:
`PhantomData<&'a T>` to borrow, `PhantomData<T>` to own, `PhantomData<fn(T)>` for
contravariance, `PhantomData<*mut T>` or `PhantomData<Cell<T>>` for invariance.
`PhantomData<fn(T)>` is sound only for a type that never stores or drops a `T`; see
[Coerce the message](#coerce-the-message-not-the-handle). `PhantomData<fn(T) -> T>` also gives
invariance and keeps `Send` and `Sync` for every `T`; `PhantomData<*mut T>` removes both. Read
the `PhantomData` table in [references/variance-tables.md](references/variance-tables.md) when
the auto traits matter.

## Unbounded lifetimes come from a raw pointer

An output lifetime that appears in no input is unbounded: every call site picks its own, and the
compiler agrees to anything. A raw-pointer deref is the usual source. This compiles, reads
freed memory at run time with an unpredictable result, and Miri (nightly 2026-05-15) reports
`constructing invalid value of type &std::string::String: encountered a dangling reference (use-after-free)`:

```rust
// UB: `'a` is tied to no input, so `escaped` outlives `owned`.
unsafe fn deref_unbounded<'a, T>(p: *const T) -> &'a T { unsafe { &*p } }

fn main() {
    let escaped: &String;
    {
        let owned = String::from("gone");
        escaped = unsafe { deref_unbounded(&owned as *const String) };
    }
    println!("{escaped}");
}
```

Borrowing the pointer variable is not enough. It proves that the pointer value is alive, not
that its pointee is alive. Tie the output to the actual owner, or return a guard that keeps the
allocation alive. An `unsafe` constructor must state and enforce the pointee-validity contract;
a borrow of `*const T` cannot replace it. Read
[references/variance-tables.md](references/variance-tables.md) when you need the exact-owner
accessor, which needs no dereference.

These std functions hand out an unbounded lifetime the same way: `<*const T>::as_ref`,
`<*mut T>::as_mut`, `NonNull::as_ref` and `as_mut`, `as_ref_unchecked` and `as_mut_unchecked`
(stable since 1.95), `slice::from_raw_parts`, and `CStr::from_ptr`. When no input carries the
lifetime, take `&self` on a wrapper that owns the pointer, or return a guard. The `rust-unsafe`
skill, when it is installed, owns the pointer-validity rules and the Miri workflow.

Since Rust 1.94 a raw-pointer cast cannot extend the lifetime bound of a trait object, and old
unsafe code that does fails with `note: raw pointer casts of trait objects cannot extend
lifetimes`. Keep `'a` in the stored type. The longer bound can make a method with a
`where Self: 'x` bound callable through a vtable that has no entry for it
(rust-lang/rust#141402). Use `transmute` only when no method of the trait has a lifetime bound on
`Self` and the owner outlives every use of the pointer, and state both facts in the `SAFETY`
comment. Read [references/variance-tables.md](references/variance-tables.md) when you need the
rejected cast and the exact `transmute` form.

## Coerce the message, not the handle

`std::sync::mpsc::Sender<T>` is invariant in `T`. Every clone is the same type, so the first call
site that demands `'static` pins the whole channel, and every borrowed source fails with
``error[E0597]: `storage` does not live long enough``.

The message stays covariant even though the handle does not. Write each consumer as
`Sender<Message<'_>>`, never `Sender<Message<'static>>`, and coerce at the send site. When a
consumer moves the sender into `thread::spawn`, every producer needs `Message<'static>`, and no
variance trick helps: make the element type own its data. Read
[references/variance-tables.md](references/variance-tables.md) when you need the rejected and
repaired pair.

Never repair this with a hand-rolled contravariant handle. A `Sender<T>` whose only mention of
`T` is `PhantomData<fn(T)>` compiles, coerces to `Sender<Message<'static>>`, escapes into a
`'static` context with short-lived values still queued, and drops them after the borrow ends.
Miri reports a use-after-free in the message destructor. The same reference holds the worked
code and the exact Miri output.

## Variance is public API

Wrapping a field in `Cell`, `RefCell`, `Mutex`, `RwLock`, or any `UnsafeCell` flips the struct
from covariant to invariant. Downstream code that shortened the lifetime stops compiling. Treat
it as a breaking change and record it in the breaking-change section of the changelog.
`ConfigV1<'a> { name: &'a str }` shortens from `'static` to `'a`. `ConfigV2<'a> { name:
Cell<&'a str> }` refuses the same coercion with ``note: the struct `ConfigV2<'a>` is invariant
over the parameter `'a` ``. Read [references/variance-tables.md](references/variance-tables.md)
when you need that pair as code.

Two more field changes break the same coercion. A `*mut T` field, or a `Box<dyn Fn(&'a T)>` field
in place of `fn(&'a T)`, makes the struct invariant over `'a`. A `&'a mut T` field is different: it
makes the struct invariant over `T`, and keeps it covariant over `'a`, so it breaks only a type
coercion.

Code that shortens a lifetime through a `&mut` unsize coercion inside `Cell`, `RefCell`, or
`UnsafeCell` needs `rust-version = "1.98"`. Run `cargo +<msrv> check` when the MSRV is lower.

Lock the variance of each public type with a lifetime parameter, so `cargo check` fails on the
field change before a downstream crate does. Keep the covariant probe in the crate as a private
function whose name starts with `_`, which keeps `dead_code` quiet:
`fn _config_is_covariant<'a, 'b: 'a>(c: ConfigV1<'b>) -> ConfigV1<'a> { c }`.

To lock intended invariance, put a `compile_fail` doctest on the type, in a library target, and
run `cargo test --doc`. A doctest compiles as a separate crate, so the type must be public and
the doctest must import it by its crate path. A `compile_fail` doctest passes on any compile
error, a wrong path included, so keep a compiling twin with the same import:

```rust
use std::cell::Cell;

/// ```
/// use my_crate::ConfigV2;
/// fn same<'a>(c: ConfigV2<'a>) -> ConfigV2<'a> { c }
/// ```
///
/// ```compile_fail
/// use my_crate::ConfigV2;
/// fn cov<'a, 'b: 'a>(c: ConfigV2<'b>) -> ConfigV2<'a> { c }
/// ```
pub struct ConfigV2<'a> { pub name: Cell<&'a str> }
```

## Traits match their parameters by equality

A trait bound is an equality constraint, not a subtyping constraint. `F: FnMut() -> &'a str` is
satisfied only by a callable whose `Output` **is** `&'a str`. `&'static str` is a subtype of
`&'a str`, and that fact is never consulted.

A named function has its own zero-sized item type, and the `Fn` impl on that type fixes
`Output = &'static str`. So this fails:

```rust,compile_fail
fn service_name() -> &'static str { "Service" }

fn main() {
    let service = "Service".to_string();
    let mut names: Vec<&str> = vec![&service];
    names.resize_with(10, service_name);
}
```

```text
error[E0597]: `service` does not live long enough
6 |     names.resize_with(10, service_name);
  |     ----------------------------------- argument requires that `service` is borrowed for `'static`
note: requirement that the value outlives `'static` introduced here
    --> .../library/alloc/src/vec/mod.rs
     |         F: FnMut() -> T,
```

Read the `note:`. It points at the bound that made the demand, not at the caller. The same shape
appears for any trait of your own, with the note on your own bound: `S: Sink<&'static u8>` is
not `S: Sink<&'a u8>`, and no variance rule bridges the two. Read
[references/variance-tables.md](references/variance-tables.md) when you need that shape as code.

## Three fixes for a producer whose output lives too long

All three compile against `let mut names: Vec<&str> = vec![&service];`. Prefer fix 1.

```rust
fn any_name<'a>() -> &'a str { "Service" }          // fix 1: unbounded output lifetime
fn static_name() -> &'static str { "Service" }

fn main() {
    let service = "Service".to_string();
    let mut names: Vec<&str> = vec![&service];
    names.resize_with(4, any_name);                 // fix 1
    names.resize_with(6, || static_name());         // fix 2: wrap at the call site
    let f: fn() -> &'static str = static_name;      // fix 3: coerce to a fn pointer
    names.resize_with(8, f);
    assert_eq!(names.len(), 8);
}
```

1. **Give the producer an unbounded output lifetime.** `fn any_name<'a>() -> &'a str` lets each
   call site pick its own `'a`. Use this whenever you own the producer. In safe code the compiler
   checks the body for every `'a`. The same signature over `unsafe` code is the hazard in
   [Unbounded lifetimes](#unbounded-lifetimes-come-from-a-raw-pointer).
2. **Wrap the call.** `|| static_name()` is a fresh closure, and inference gives its `Output` the
   short lifetime the bound asks for. Use this when the producer is in another crate.
3. **Coerce to a function pointer.** `fn` *pointers* are covariant in the return type, so
   `fn() -> &'static str` is a subtype of `fn() -> &'a str`, and the coercion runs at the argument
   site. The `fn` *item* type has no such freedom.

Fix 3 needs the lifetime written out, because `fn() -> &str` has no input lifetime for elision
to use. `let f: fn() -> &str = static_name;` gives `error[E0106]: missing lifetime specifier`,
with `^ expected named lifetime parameter` under the `&`.

## A free lifetime in `dyn Trait` makes it invariant

`dyn Trait + 'a` is covariant in the `'a` that bounds the object. A lifetime written **inside**
the trait's parameter list is a trait parameter instead, so it matches by equality, and the
object coerces in neither direction. A `fn(&Event<'a>)` field keeps a struct contravariant in
`'a`. A `Box<dyn Fn(&Event<'a>)>` field makes it invariant, both directions
fail with ``note: the struct `HooksBox<'a>` is invariant over the parameter `'a` ``, and the
change is invisible in review. Read [references/variance-tables.md](references/variance-tables.md)
when you need the two forms side by side.

The fix is to keep the object higher-ranked. Elision inside `dyn Fn(&Event)` produces
`for<'x>`, the struct loses its lifetime parameter, and the callback serves every caller:

```rust
pub struct Event<'a> { pub name: &'a str }
pub struct Hooks { pub on: Box<dyn for<'x> Fn(&Event<'x>)> }

fn main() {
    let h = Hooks { on: Box::new(|e| { let _ = e.name; }) };
    let name = String::from("tick");
    (h.on)(&Event { name: &name });
}
```

Rule: write a free lifetime into a trait object's parameters only when you intend invariance.

## A `&mut` parameter pins the caller's lifetime

`C` may be covariant and still be frozen by the `&mut` around it. With
`fn push_str_ref<'a>(v: &mut Vec<&'a str>, s: &'a str)`, a caller that declares
`let mut v: Vec<&'static str>` and pushes a borrowed `&s` gets
``error[E0597]: `s` does not live long enough``, and the label on the annotation reads
``type annotation requires that `s` is borrowed for `'static` ``. Two repairs:

- Drop the `'static` from the caller's annotation. `let mut v: Vec<&str>` lets `'a` shorten to
  the body, and the same call compiles.
- Take the container by value and give it back:
  `fn with_str_ref<'a>(mut v: Vec<&'a str>, s: &'a str) -> Vec<&'a str>`. The `&mut`
  disappears, so covariance applies and a `Vec<&'static str>` coerces at the call.

In a public API whose callers may hold a longer-lived container, prefer taking the container by
value, or an owned element type. Read
[references/variance-tables.md](references/variance-tables.md) when you need the full rejected
and repaired pair.

## Related skills

Hand off to these skills when they are installed.

| Skill | Boundary |
| --- | --- |
| `rust-unsafe` | Raw-pointer validity, `PhantomData` on FFI handles, the Miri workflow, and the proof for a manual `unsafe impl Send` or `Sync` |
| `rust-compiler-errors` | E0597, E0521, and E0106 beyond the variance shapes here, and dyn compatibility (E0038) |
| `rust-callback-bounds` | Choosing `Fn`, `FnMut`, `FnOnce`, or a `fn` pointer for a callback, once variance is settled |
| `rust-type-erasure` | `TypeId`-keyed stores, `dyn Any` downcasting and upcasting, and the `'static` bound of `Any` |
| `rust-send-sync` | The auto-trait half of the `PhantomData` table |
| `rust-discipline` | API review, including `PhantomData<fn() -> S>` on type-state tags and what counts as a breaking change |
| `memory-model` | `UnsafeCell` and the atomics whose invariance this skill only cites |
