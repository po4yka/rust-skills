---
name: rust-variance
description: Use when a lifetime coercion is refused and you must decide whether a type constructor is covariant, contravariant, or invariant, or when you add a lifetime parameter to a public type. Covers the three one-line probes that settle any variance question in one rustc run, the variance of &T, &mut T, *const T, *mut T, Box, Vec, fn(T), fn() -> T, Cell, Mutex, dyn Trait and every PhantomData form, why traits match their parameters and associated types by equality so a fn item returning &'static str fails resize_with with E0597, the three fixes for a producer whose output lives too long, unbounded lifetimes from a raw-pointer deref, and why adding interior mutability to a published struct is a breaking change. Triggers on "variance", "covariant", "contravariant", "subtyping", "lifetime may not live long enough" on a coercion, "is invariant over the parameter", "borrowed for 'static", "resize_with", "unbounded lifetime", "phantomdata variance", "dyn fn lifetime", "&mut is invariant", or "sender is invariant".
license: BSD-3-Clause
---

# Rust variance

## Purpose

This skill answers one question: does a value that holds `'b` fit where the compiler asks for
`'a`, given `'b: 'a`. The answer comes from the type constructor around the lifetime, not from
the lifetime.

Do not get this sentence wrong: **variance belongs to type constructors only.** A trait matches
its parameters and its associated types by equality, so nothing coerces through a trait bound.
A named function *item* that returns `&'static str` therefore does not satisfy
`F: FnMut() -> &'a str`. Its `fn` pointer type does satisfy it, because the pointer type itself
subtypes. See fix 3 below.

Every diagnostic below is copied from rustc 1.97.0, edition 2024, aarch64-apple-darwin.

Raw-pointer soundness belongs to `rust-unsafe`. Reading E0597 and E0521 in general belongs to
`rust-compiler-errors`. This skill covers only the coercion decision.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| You must know the variance of a type you own | [Settle it with a probe](#settle-it-with-a-probe) |
| `note: the struct X<T> is invariant over the parameter T` | [The variance table](#the-variance-table) |
| `note: mutable references are invariant over their type parameter` | [Settle it with a probe](#settle-it-with-a-probe) |
| `note: requirement that the value outlives 'static introduced here`, pointing at a trait bound | [Traits match by equality](#traits-match-their-parameters-by-equality) |
| `error[E0597]` at `resize_with`, `map`, or any callback argument | [Traits match by equality](#traits-match-their-parameters-by-equality) |
| `error[E0106]: missing lifetime specifier` on `fn() -> &str` | [Three fixes](#three-fixes-for-a-producer-whose-output-lives-too-long) |
| `lifetime may not live long enough` on a `Box<dyn Fn(&'a T)>` field | [A free lifetime in `dyn Trait`](#a-free-lifetime-in-dyn-trait-makes-it-invariant) |
| A `Sender`, handle, or queue refuses to coerce | [Coerce the message, not the handle](#coerce-the-message-not-the-handle) |
| A raw-pointer deref returns `&'a T` with no `'a` in the inputs | [Unbounded lifetimes](#unbounded-lifetimes-come-from-a-raw-pointer) |
| You add `Cell`, `RefCell`, or `Mutex` to a published struct | [Variance is public API](#variance-is-public-api) |
| The full table, the traps, and the worked unsound channel | [references/variance-tables.md](references/variance-tables.md) |

## Settle it with a probe

Do not reason about variance. Compile these three one-line functions and read the result. This is
the most reusable item in this skill.

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

The covariant probe on `Vec<T>` compiles, so `Vec` accepts a longer-lived element:

```rust
fn cov<'a, 'b: 'a>(x: Vec<&'b u8>) -> Vec<&'a u8> { x }
```

The contravariant probe on `fn(T)` compiles, so a handler for a short-lived argument serves as
a handler for a long-lived one:

```rust
fn con<'a, 'b: 'a>(x: fn(&'a u8)) -> fn(&'b u8) { x }
```

Both probes fail on `Cell<T>`, and rustc names the rule in a note:

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

One trap. Never write a `'static` outer reference into a probe. This compiles, and it proves
nothing, because `&'static mut` forces `&'b u8: 'static` and collapses both lifetimes:

```rust
fn degenerate<'a, 'b: 'a>(x: &'static mut &'b u8) -> &'static mut &'a u8 { x }
```

Use a fresh outer lifetime instead: `fn p<'x, 'a: 'x, 'b: 'a>(x: &'x mut &'b u8) -> &'x mut &'a u8`.
That form is rejected with `note: mutable references are invariant over their type parameter`, which
is the true answer for `&mut T`.

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

- A struct or enum takes the **strictest** variance of its fields, computed per parameter. One
  `Cell<T>` field makes the whole type invariant in `T`.
- Everything built on `UnsafeCell<T>` is invariant in `T`, because a shared reference to it
  permits a write. That is `Cell`, `RefCell`, `Mutex`, `RwLock`, the atomics, and every channel
  handle in `std`.

`references/variance-tables.md` has the exact rustc note for each invariant row, and the probe
file that produced them.

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
    --> library/alloc/src/vec/mod.rs:3174:23
3174 |         F: FnMut() -> T,
```

Read the `note:`. It points at the bound that made the demand, not at the caller. The same shape
appears for any trait of your own, with the note on your own bound:

```rust,compile_fail
trait Sink<T> { fn put(&self, v: T); }

fn feed<'a, S: Sink<&'a u8>>(s: &S, v: &'a u8) { s.put(v) }

fn go<S: Sink<&'static u8>>(s: &S) {
    let local = 5u8;
    feed(s, &local);   // E0597: argument requires that `local` is borrowed for `'static`
}
```

`S: Sink<&'static u8>` is not `S: Sink<&'a u8>`. No variance rule bridges the two.

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
   call site pick its own `'a`. Use this whenever you own the producer. Note that an unbounded
   output lifetime is safe here only because the body returns a literal; see
   [Unbounded lifetimes](#unbounded-lifetimes-come-from-a-raw-pointer).
2. **Wrap the call.** `|| static_name()` is a fresh closure, and inference gives its `Output` the
   short lifetime the bound asks for. Use this when the producer is in another crate.
3. **Coerce to a function pointer.** `fn` *pointers* are covariant in the return type, so
   `fn() -> &'static str` is a subtype of `fn() -> &'a str`, and the coercion runs at the argument
   site. The `fn` *item* type has no such freedom.

Fix 3 needs the lifetime written out. The elision rules for `fn` items do not apply to a `fn`
pointer type, so `let f: fn() -> &str = static_name;` gives
`error[E0106]: missing lifetime specifier`, with `^ expected named lifetime parameter` under the
`&`.

## A free lifetime in `dyn Trait` makes it invariant

`dyn Trait + 'a` is covariant in the `'a` that bounds the object. A lifetime written **inside**
the trait's parameter list is a different thing: it is a trait parameter, so it matches by
equality, and the object coerces in neither direction.

A callback field as a function pointer is contravariant in the event lifetime:

```rust
pub struct Event<'a> { pub name: &'a str }
pub struct HooksPtr<'a> { pub on: fn(&Event<'a>) }

fn lengthen<'a>(h: HooksPtr<'a>) -> HooksPtr<'static> { h }   // compiles
```

Swap the field for a boxed closure over the same lifetime and the struct becomes invariant.
Both directions now fail, and the change is invisible in review:

```rust,compile_fail
pub struct Event<'a> { pub name: &'a str }
pub struct HooksBox<'a> { pub on: Box<dyn Fn(&Event<'a>)> }

fn lengthen<'a>(h: HooksBox<'a>) -> HooksBox<'static> { h }
```

```text
error: lifetime may not live long enough
4 | fn lengthen<'a>(h: HooksBox<'a>) -> HooksBox<'static> { h }
  |             -- lifetime `'a` defined here               ^ returning this value requires that `'a` must outlive `'static`
  = note: the struct `HooksBox<'a>` is invariant over the parameter `'a`
```

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

`C` may be covariant and still be frozen by the `&mut` around it. The caller's type annotation
then propagates into the argument:

```rust,compile_fail
fn push_str_ref<'a>(v: &mut Vec<&'a str>, s: &'a str) { v.push(s) }

fn main() {
    let mut v: Vec<&'static str> = vec!["a"];
    let s = String::from("b");
    push_str_ref(&mut v, &s);
}
```

```text
error[E0597]: `s` does not live long enough
4 |     let mut v: Vec<&'static str> = vec!["a"];
  |                ----------------- type annotation requires that `s` is borrowed for `'static`
6 |     push_str_ref(&mut v, &s);
  |                          ^^ borrowed value does not live long enough
```

Two repairs, both verified:

- Drop the `'static` from the caller's annotation. `let mut v: Vec<&str>` lets `'a` shorten to
  the body, and the same call compiles.
- Take the container by value and give it back. The `&mut` disappears, so covariance applies and
  a `Vec<&'static str>` coerces at the call:

```rust
fn with_str_ref<'a>(mut v: Vec<&'a str>, s: &'a str) -> Vec<&'a str> { v.push(s); v }

fn main() {
    let v: Vec<&'static str> = vec!["a"];
    let s = String::from("b");
    let v = with_str_ref(v, &s);
    assert_eq!(v.len(), 2);
}
```

Never take `&mut Container<&'a T>` in a public API when a caller may hold a longer-lived
container. Take it by value, or make the element type owned.

## Coerce the message, not the handle

`std::sync::mpsc::Sender<T>` is invariant in `T`. Every clone is the same type, so the first call
site that demands `'static` pins the whole channel. Every borrowed source then has to outlive
`'static`, and rustc reports ``error[E0597]: `storage` does not live long enough``.

The message stays covariant even though the handle does not. Write each consumer as
`Sender<Message<'_>>`, never `Sender<Message<'static>>`, and coerce at the send site. The rejected
pair and the repaired pair are in
[references/variance-tables.md](references/variance-tables.md).

What invariance costs the API: one lifetime serves the whole channel, so a consumer that moves
the sender into `thread::spawn` forces `Message<'static>` on every producer. No variance trick
reaches that case. Make the element type own its data.

Do not repair this by hand-rolling a contravariant handle. A `Sender<T>` whose only mention of
`T` is `PhantomData<fn(T)>` compiles, coerces to `Sender<Message<'static>>`, escapes into a
`'static` context with short-lived values still in the queue, and runs their destructors after
the borrow ends. Miri on that program reports `Undefined Behavior: constructing invalid value of
type &str: encountered a dangling reference (use-after-free)`. Contravariance is sound only for
a handle that consumes a `T` inside the call and never stores or drops one. The worked code is
in [references/variance-tables.md](references/variance-tables.md).

## Unbounded lifetimes come from a raw pointer

An output lifetime that appears in no input is unbounded: every call site picks its own, and the
compiler agrees to anything. A raw-pointer deref is the usual source. This compiles, prints
nothing useful, and Miri reports `constructing invalid value of type &std::string::String:
encountered a dangling reference (use-after-free)`:

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

Tie the output to an input. The borrow of the pointer variable carries the lifetime:

```rust
unsafe fn deref_tied<'a, T>(p: &'a *const T) -> &'a T { unsafe { &**p } }
```

The caller must change too. Store the pointer in a binding, then pass a borrow of that binding. A
borrow of the cast expression is a temporary, and rustc answers `error[E0716]: temporary value
dropped while borrowed`. This caller uses a binding, so the borrow checker sees the real lifetime:

```rust,compile_fail
unsafe fn deref_tied<'a, T>(p: &'a *const T) -> &'a T { unsafe { &**p } }

fn main() {
    let escaped: &String;
    {
        let owned = String::from("gone");
        let p = &owned as *const String;
        escaped = unsafe { deref_tied(&p) };
    }
    println!("{escaped}");
}
```

rustc now rejects the escape with ``error[E0597]: `p` does not live long enough``, and labels the
`println!` line `borrow later used here`.

`<*const T>::as_ref` and `NonNull::as_ref` both hand out an unbounded lifetime the same way. When
no input carries the lifetime, take `&self` on a wrapper that owns the pointer, or return a
guard. `rust-unsafe` owns the pointer-validity rules and the Miri workflow.

## Variance is public API

Wrapping a field in `Cell`, `RefCell`, `Mutex`, `RwLock`, or any `UnsafeCell` flips the struct
from covariant to invariant. Downstream code that shortened the lifetime stops compiling. Treat
it as a breaking change, and run the probe before you publish.

```rust
pub struct ConfigV1<'a> { pub name: &'a str }

fn shorten<'a>(c: ConfigV1<'static>, _tie: &'a str) -> ConfigV1<'a> { c }
```

```rust,compile_fail
use std::cell::Cell;

pub struct ConfigV2<'a> { pub name: Cell<&'a str> }

fn shorten<'a>(c: ConfigV2<'static>, _tie: &'a str) -> ConfigV2<'a> { c }
```

```text
error: lifetime may not live long enough
5 | fn shorten<'a>(c: ConfigV2<'static>, _tie: &'a str) -> ConfigV2<'a> { c }
  |            -- lifetime `'a` defined here                              ^ returning this value requires that `'a` must outlive `'static`
  = note: the struct `ConfigV2<'a>` is invariant over the parameter `'a`
```

Two more field changes break the same coercion. A `*mut T` field, or a `Box<dyn Fn(&'a T)>` field
in place of `fn(&'a T)`, makes the struct invariant over `'a`. A `&'a mut T` field is different: it
makes the struct invariant over `T`, and keeps it covariant over `'a`, so it breaks only a type
coercion.

## Checklist

- Every public type with a lifetime parameter has a recorded variance, measured with the probe.
- No public function takes `&mut Container<&'a T>` where a caller may hold a longer-lived container.
- No trait object carries a free lifetime in its parameter list unless invariance is intended.
- Every producer passed to an `F: FnMut() -> &'a T` bound declares an unbounded output lifetime,
  or the call site wraps it in a closure.
- Every `unsafe fn` that returns a reference names the lifetime in an input.
- Every `PhantomData` states the intent: `&'a T` to borrow, `T` to own, `fn(T)` for
  contravariance, `*mut T` or `Cell<T>` for invariance.
- Adding interior mutability to a published struct goes in the breaking-change section of the
  changelog.
- A variance change is re-probed against the previous definition before release.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-unsafe` | Raw-pointer validity, `PhantomData` on FFI handles, and the Miri workflow behind the unbounded-lifetime example |
| `rust-compiler-errors` | Reading E0597, E0521, and E0106 in general, beyond the variance shapes here |
| `rust-callback-bounds` | Choosing `Fn`, `FnMut`, `FnOnce`, or a `fn` pointer for a callback, once variance is settled |
| `rust-type-erasure` | `Box<dyn Trait>` design: object safety, vtables, and the cost of the indirection |
| `rust-send-sync` | The auto-trait half of the `PhantomData` table, and `unsafe impl Send` |
| `rust-discipline` | API review, including `PhantomData<fn() -> S>` on type-state tags and what counts as a breaking change |
| `memory-model` | `UnsafeCell` and the atomics whose invariance this skill only cites |
