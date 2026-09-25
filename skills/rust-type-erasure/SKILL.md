---
name: rust-type-erasure
description: Use when designing or reviewing type erasure or a type map keyed by TypeId — Box<dyn Any>, downcast_ref, an anymap, an extensions map, a resource registry, an ECS-style world — above all when the stored values borrow and are not 'static. Also for upcasting dyn Trait to dyn Any, E0597 blamed on the caller of an Any-bounded map, a type_name used as a key, the GAT bijection that keys borrowed values, an extractor or system param that detaches a lifetime, and E0117 when shipping the pattern as a library.
license: BSD-3-Clause
---

# Rust type erasure

`Any` keys nothing that borrows. Its only impl is `impl<T: 'static + ?Sized> Any for T`, and the
error for that bound lands on the caller, not on the map. Erase no more than the design needs;
see [the ladder](#the-ladder).

Quoted rustc output comes from rustc 1.98.1, edition 2024, aarch64-apple-darwin. Quoted Miri
output comes from Miri 0.1.0 on nightly 2026-05-15.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0597]: ... argument requires that s is borrowed for 'static`, or `error: lifetime may not live long enough ... requires that 'a must outlive 'static` | [`Any` is bound to `'static`](#any-is-bound-to-static) |
| You reached for `type_name` because `TypeId::of` refused | [`type_name` is not a type key](#type_name-is-not-a-type-key) |
| Choosing between an enum, a `dyn Any` map, and something exotic | [The ladder](#the-ladder) |
| `.type_id()` on a `Box`, `Arc`, or `Rc` never equals `TypeId::of::<T>()`, or you are about to write `fn as_any` | [Get the concrete type back from `dyn Trait`](#get-the-concrete-type-back-from-dyn-trait) |
| You must store a `Cow<'a, str>`, a `&'a [u8]`, or any borrow, keyed by type | [Rung 3](#rung-3-an-open-set-of-borrowed-values) |
| `error[E0271]: type mismatch resolving <P<'a> as Element<'a>>::Owner == Tag` | [The bijection is the collision proof](#the-bijection-is-the-collision-proof) |
| `error: incompatible lifetime on type` on an `Owner` or `Element` impl | [The bijection is the collision proof](#the-bijection-is-the-collision-proof) |
| `error[E0277]: the trait bound S: Element<'_> is not satisfied` in a helper | [The helper bound is `for<'x>`](#the-helper-bound-is-forx-not-static) |
| You are writing an extractor, a system param, or a `from_world` | [Where it breaks](#where-it-breaks-an-extractor-that-detaches-the-lifetime) |
| `error[E0117]: only traits defined in the current crate ...` in a user crate | [The orphan rule](#the-orphan-rule-caps-the-pattern-at-one-crate) |
| You add or change a lifetime-carrying store, its accessors, or its `unsafe` cast | [Verify the store](#verify-the-store) |

## Verify the store

Rungs one and two need only ordinary tests. Run these checks when you add or change a
lifetime-carrying store (rung three), its accessors, its extraction layer, or its `unsafe` cast:

1. If a nightly toolchain with the miri component is installed (`rustup +nightly component add
   miri`), run `cargo +nightly miri test --locked` on the store's tests. This is the default
   Stacked Borrows model, and it is the gate. Without Miri, report the `unsafe` cast as not
   checked by Miri.
2. Run `MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked` after it, as additional
   evidence. Never make it the only gate. The `rust-sanitizers-miri` skill, when it is installed,
   owns the Miri policy.
3. Pin each rejection the design relies on with a `compile_fail` doctest: a borrow shorter than
   the map in `put`, a `get` result used after the map drops, a `Cell` element shortened through
   `&AnyMap<'short>`, a second tag for one element type, and, for an extraction layer, a system
   closure that stores its extracted argument in an outer variable (`E0521` for an argument of
   type `&'w T`). A doctest compiles as a separate crate, so it can use only public items. Run
   `cargo +nightly test --doc --locked` as well when a nightly toolchain is installed, so rustdoc
   enforces each named code such as `compile_fail,E0597`. Stable accepts any error, so on stable
   a doctest that fails on a private path still passes. Without nightly, confirm each code with
   `cargo check` on a probe crate, or report the codes as unchecked.
4. Run `cargo clippy --locked --all-targets -- -D warnings`. `clippy::type_id_on_box` catches
   `.type_id()` on a `Box` only.
5. Review each extraction signature: no function returns `Self`, or any type that does not name
   the input borrow's lifetime, from a `&` argument. No test or Miri run catches that edit.

Miri checks only the paths the tests execute, and correct callers never detach a lifetime. A
`get` that returns `&'a E`, or a map without the invariance marker, passes every test and every
Miri run of correct code. Only the `compile_fail` doctests in step 3 catch that edit. Keep each
doctest to the one failure it guards.

## `Any` is bound to `'static`

`TypeId::of::<T>` carries the same `T: 'static` bound as the only `Any` impl. Both are writable
for a borrowed type, and neither is satisfiable:
`TypeId::of::<&'a str>()` inside `fn f<'a>()` gives `error: lifetime may not live long enough ...
requires that 'a must outlive 'static`.

The trap is that the bound does not fail where you wrote it. A generic `put<S: Any>` compiles
clean. Region inference propagates the `'static` requirement outward, so the first failure is at
the call site, and it blames a local variable:

```rust,compile_fail,E0597
use std::any::{Any, TypeId};
use std::borrow::Cow;
use std::collections::HashMap;

#[derive(Default)]
struct AnyMap { table: HashMap<TypeId, Box<dyn Any>> }

impl AnyMap {
    // This definition compiles clean. The bound never fails here.
    fn put<S: Any>(&mut self, x: S) { self.table.insert(TypeId::of::<S>(), Box::new(x)); }
}

fn main() {
    let s = String::from("hello world");
    let mut map = AnyMap::default();
    map.put(Cow::from(&s));         // error[E0597] blames `s`, not `put`
}
```

```text
error[E0597]: `s` does not live long enough
16 |     map.put(Cow::from(&s));
   |     ------------------^^--
   |     |                 borrowed value does not live long enough
   |     argument requires that `s` is borrowed for `'static`
note: requirement that the value outlives `'static` introduced here
10 |     fn put<S: Any>(&mut self, x: S) { ... }
   |               ^^^
```

Read the trailing `note:`, not the span. The span names the local; the note names the bound. A
longer-lived `s` never fixes this shape. Change the store instead.

## `type_name` is not a type key

`std::any::type_name::<T>()` has no `T: 'static` bound, so it compiles exactly where `TypeId::of`
refused. That is what makes it dangerous. The std documentation says the string is not a unique
identifier and can change between compiler versions. As of Rust 1.98.1 it prints a lifetime
argument of a named type as `'_` (`Wrapper<'_>`) and omits reference lifetimes (`&str`). Rust 1.88
omitted both. No version can tell two lifetimes apart, because rustc erases lifetimes before code
generation. Two distinct types can share one string:

```rust,run
use std::any::type_name;

struct Wrapper<'a>(&'a str);

// Compiles for every `'a`. `type_name` carries no `T: 'static` bound.
fn name_of<'a>(_: &'a str) -> &'static str { type_name::<Wrapper<'a>>() }

fn main() {
    let s = String::from("x");
    assert_eq!(type_name::<Wrapper<'static>>(), name_of(&s));   // "<module>::Wrapper<'_>"
    assert_eq!(type_name::<&'static str>(), type_name::<&str>());   // "&str"
}
```

Never key a map, a registry, or a cache on `type_name`, and never compare two `type_name` strings
to decide a cast, because a collision casts to the wrong type or extends a lifetime. Use it in a
panic message, a log line, or an error string.

## The ladder

Stop at the first rung that holds. Most designs stop at rung one or two, and should.

| Value set | Value ownership | Use |
| --- | --- | --- |
| Closed: you name every type | owned or borrowed | A lifetime-parameterized enum. No `unsafe`, exhaustive `match` |
| Open: other modules register types | owned, or shared behind `Arc` | `HashMap<TypeId, Box<dyn Any>>`. No `unsafe` |
| Open | borrows a buffer that outlives the map | The GAT owner/element bijection. One `unsafe` block |

Rung three is exotic. Take it only when the value set is genuinely open **and** the values
genuinely borrow. If either half is false, the rung above costs less and proves more.

### Rung 1: a closed value set

An enum parameterized by the lifetime holds borrowed data with no erasure at all. A new variant
then breaks every `match` with `E0004`, which is the point.

```rust
use std::borrow::Cow;
use std::collections::HashMap;

enum Slot<'a> { Text(Cow<'a, str>), Count(u32) }

fn text<'a>(table: &'a HashMap<&str, Slot<'a>>, k: &str) -> Option<&'a Cow<'a, str>> {
    match table.get(k)? { Slot::Text(c) => Some(c), Slot::Count(_) => None }
}

fn main() {
    let s = String::from("hello world");
    let mut table = HashMap::new();
    table.insert("greeting", Slot::Text(Cow::from(&s)));
    table.insert("retries", Slot::Count(3));
    assert_eq!(text(&table, "greeting").map(|c| &**c), Some("hello world"));
    assert!(text(&table, "retries").is_none());
}
```

### Rung 2: an open set of owned values

This is what a request-extension map and a resource registry actually do. They store owned
values, or `Arc` clones of a shared value, so the `'static` bound costs nothing.

```rust
use std::any::{Any, TypeId};
use std::collections::HashMap;
use std::sync::Arc;

#[derive(Default)]
struct Extensions { table: HashMap<TypeId, Box<dyn Any + Send + Sync>> }

impl Extensions {
    fn insert<T: Any + Send + Sync>(&mut self, value: T) {
        self.table.insert(TypeId::of::<T>(), Box::new(value));
    }
    fn get<T: Any + Send + Sync>(&self) -> Option<&T> {
        self.table.get(&TypeId::of::<T>())?.downcast_ref()
    }
}

fn main() {
    let mut ext = Extensions::default();
    ext.insert(Arc::<str>::from("hello world"));   // share the buffer, do not borrow it
    assert_eq!(ext.get::<Arc<str>>().map(|s| &**s), Some("hello world"));
    assert_eq!(ext.get::<i64>(), None);
}
```

Before you climb to rung three, try to reach this rung instead: replace the borrow with `Arc<T>`
or with an owned copy at the map boundary. The `rust-copy-on-write` skill, when it is installed,
has the allocation counts that decide whether that copy is affordable.

### Get the concrete type back from `dyn Trait`

Make `Any` a supertrait and let the compiler upcast `dyn Trait` to `dyn Any` (stable since 1.86).
Do not add a `fn as_any(&self) -> &dyn Any` method to every impl unless the MSRV is below 1.86.

Dereference the smart pointer before you ask for a `TypeId`. `boxed.type_id()` compiles and
returns the `TypeId` of the `Box`, because a `'static` box is itself `Any` and method lookup stops
there. A `TypeId` comparison or a hand-written downcast then fails silently.
`clippy::type_id_on_box` (warn by default) flags the call. It flags only `Box`. `Arc<dyn Any>` and
`Rc<dyn Trait>` have the same bug and no lint, so write `(*ptr).type_id()` or upcast to `&dyn Any`
first.

```rust,run
use std::any::{Any, TypeId};

trait Plugin: Any { fn name(&self) -> &'static str; }

struct Metrics;
impl Plugin for Metrics { fn name(&self) -> &'static str { "metrics" } }

fn main() {
    let boxed: Box<dyn Plugin> = Box::new(Metrics);
    // Method lookup stops at the `Box`, which is `'static` and so is `Any` itself.
    assert_eq!(boxed.type_id(), TypeId::of::<Box<dyn Plugin>>());
    // Deref to the trait object, then upcast. This reaches the value.
    let any: &dyn Any = &*boxed;
    assert_eq!(any.type_id(), TypeId::of::<Metrics>());
    assert!(any.downcast_ref::<Metrics>().is_some());
    // An owned upcast keeps the allocation and allows `downcast`.
    let owned: Box<dyn Any> = boxed;
    let metrics: Box<Metrics> = owned.downcast().expect("stored as Metrics");
    assert_eq!(metrics.name(), "metrics");
}
```

`trait Plugin: Any` makes every implementor `'static`. A plugin that borrows cannot implement it;
go back to the ladder.

### Rung 3: an open set of borrowed values

Key on a `'static` **owner tag** instead of on the element type, and tie the two together with a
pair of mutually constraining GAT metafunctions. The tag is `'static`, so `TypeId::of` accepts
it. The element carries the lifetime.

```rust
use std::any::TypeId;
use std::cell::UnsafeCell;
use std::collections::HashMap;
use std::marker::PhantomData;

trait AnyDrop {}                    // storage and drop only, not `Any`
impl<T> AnyDrop for T {}

trait Owner: 'static { type Element<'a>: Element<'a, Owner = Self>; }   // the key
trait Element<'a>: 'a { type Owner: Owner<Element<'a> = Self>; }       // the value

struct AnyMap<'a> {
    invariant: PhantomData<UnsafeCell<&'a mut ()>>,
    table: HashMap<TypeId, Box<dyn AnyDrop + 'a>>,   // keyed by `TypeId::of::<E::Owner>()`
}
```

Read [references/gat-anymap.md](references/gat-anymap.md) when you implement or review rung
three. It has the complete store with `get`, `get_mut`, and the cast, the Miri verdict, the drop
probe, every attack with its diagnostic, the extractor exploit, and the library rules.

Four properties do the work. Any edit that drops one breaks the proof:

- `get` returns `Option<&E>` with an elided output lifetime, so the borrow is the `&self` borrow.
  Never write `fn get<E: Element<'a>>(&self) -> Option<&'a E>`. That signature compiles with no
  diagnostic and returns a reference that outlives the map.
- `put` takes `E` by value at the map's own `'a`, and `Box<dyn AnyDrop + 'a>` forces `E: 'a`.
- `AnyDrop` is an empty marker trait, not `Any`. A trait object's vtable carries a drop slot
  whatever the trait's method set, so `Box<dyn AnyDrop + 'a>` still runs the concrete `Drop`,
  including on the value a `HashMap::insert` displaces. `Any` would re-impose `'static`.
- `PhantomData<UnsafeCell<&'a mut ()>>` makes the map invariant in `'a`. Drop it and safe code
  writes a short borrow into a long slot through any element type with interior mutability.

`get` casts `*const (dyn AnyDrop + 'a)` to `*const <E::Owner as Owner>::Element<'a>`. Its SAFETY
comment must name the GAT equality `<E::Owner as Owner>::Element<'a> == E`, because that equality
is the whole proof that the key selects the right type.

## The bijection is the collision proof

Two colliding `TypeId` keys would let `get` cast to the wrong type. The trait pair makes a
collision unconstructible, so the map needs no runtime type check. rustc rejects each miswiring
at the impl that writes it: a second tag for a claimed element type gives `error[E0271]`, and a
tag and element impl that disagree on `'a`, or an `Element<'static>`-only impl, give
`error: incompatible lifetime on type`. Each error means the guard works. Fix the impl, or give
the second use its own newtype and tag; do not weaken the trait pair. The
[attack table](references/gat-anymap.md#attacks-that-the-trait-pair-defeats) has each diagnostic.

The bijection proves key uniqueness. It does not prove that the element uses its lifetime. A tag
whose `Element<'x>` ignores `'x` compiles clean: `impl Owner for String { type Element<'a> = Self; }`
is that shape, and every `'static` element needs it. Do not expect the compiler to reject a GAT
that drops its lifetime. That hole is what the extractor below exploits.

## The helper bound is `for<'x>`, not `'static`

A helper that reads the map but does not know the map's `'a` must demand the element trait at
every lifetime. With `S: 'static` alone, `get` fails with
`error[E0277]: the trait bound S: Element<'_> is not satisfied`. Do not apply rustc's `help:`
bound `S: 'static + Element<'_>`: `'_` is not allowed there (`error[E0637]`). The bound that
compiles:

```rust
impl<S: 'static + for<'x> Element<'x>> Extractor for State<&S> { /* ... */ }
```

## Where it breaks: an extractor that detaches the lifetime

The map is sound. A layer on top that hands closures their arguments (an extractor, a system
param, a `from_world`) is where soundness is lost. This shape is unsound. Do not copy it:

```rust
trait Extractor {
    type Extracted: ExtractedType;
    unsafe fn from_world(world: &AnyMap) -> Self;   // no lifetime ties to `world`
}
trait ExtractedType: 'static { type Extractor<'a>: Extractor<Extracted = Self>; }
```

The design leans on `F: for<'a> FnMut(A1::Extractor<'a>, A2::Extractor<'a>)` to stop the closure
keeping the reference. **That bound is vacuous when `Extractor<'a>` is constant in `'a`.** One safe
user impl whose `type Extractor<'a>` reads `Evil<&'static S>` gives the closure a real `&'static`
into the world. Measured: a use-after-free after the world drops, which both Miri borrow models
report, observed by a closure with no `unsafe`. Adding the reverse equality
`type Extracted: ExtractedType<Extractor<'a> = Self>` does not fix it, and E0207 does not fire. No
bound in Rust forces a GAT to use its lifetime.

The rule: an extraction API must return a type whose signature ties the result to the input
borrow, for example `fn from_world<'w, 'm>(world: &'w AnyMap<'m>) -> Self::Out<'w>`. Keep the two
lifetimes apart. `&'w AnyMap<'w>` borrows the invariant map until its destructor runs, so every
caller fails with `E0597` on the map, and removing the invariance marker to silence it makes the
map unsound. An `unsafe fn` that returns `Self` gives the caller an obligation no caller can
discharge. Read the
[exploit and the reverse-constraint proof](references/gat-anymap.md#the-extractor-exploit-in-full)
when you review an extraction layer.

## The orphan rule caps the pattern at one crate

Registration is a user-written trait impl, and coherence blocks a downstream crate from
registering a foreign type: `impl<'a> Element<'a> for Cow<'a, str>` there fails with
`error[E0117]`. A published map crate must ship the `Owner` and `Element` impls for the std types
its users store, and document a local newtype for everything else. Read
[Shipping it as a library](references/gat-anymap.md#shipping-it-as-a-library) when you publish
the pattern.

## Related skills

Use these skills by name, when they are installed.

| Skill | Boundary |
| --- | --- |
| `rust-discipline` | Whether to erase at all: a `downcast_ref` chain is a `match` with the exhaustiveness check removed |
| `rust-unsafe` | The mechanics of the pointer cast, SAFETY comment review, and why a raw pointer never buys a lifetime |
| `rust-sanitizers-miri` | Running Miri, Stacked Borrows against Tree Borrows, and what a clean run does not prove |
| `rust-variance` | Why `PhantomData<UnsafeCell<&'a mut ()>>` makes a type invariant, and how to probe variance |
| `rust-compiler-errors` | E0597, E0277, E0271 and E0308 in general, beyond the shapes here |
| `rust-copy-on-write` | The allocation cost of owning the value instead of borrowing it, which keeps you on rung two |
| `rust-crate-architecture` | Coherence and the orphan rule as a crate-boundary constraint |
