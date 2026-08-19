---
name: rust-type-erasure
description: Use when you store values in a type-keyed map or erase a type at run time — Box<dyn Any>, TypeId, downcast_ref, a request-extension map, a resource registry, or an ECS-style world — and above all when the values are not 'static. Covers why Any is bound to 'static and how that bound surfaces as E0597 at the caller instead of at the map, why type_name is not a type key, a three-rung ladder from a lifetime-parameterized enum through a plain Box<dyn Any> type map to the GAT owner/element bijection that keys borrowed data on a 'static tag, the E0271 and lifetime-mismatch collisions the compiler rejects for you, the for<'x> bound a generic helper needs, the use-after-free an extractor layer reintroduces when it detaches the lifetime, and the E0117 orphan limit on shipping the pattern as a library. Triggers on "TypeId", "dyn Any", "downcast_ref", "type erasure", "anymap", "type map", "extensions map", "type_name", "non-static Any", "GAT bijection", "resource registry", "system param", or "E0117".
license: BSD-3-Clause
---

# Rust type erasure

## Purpose

Decide how to hold values whose types the code does not name, and stop before you erase more
than you must. The one sentence not to get wrong: **`Any` keys nothing that borrows**, because
`impl<T: 'static + ?Sized> Any for T` is the only impl, and the error for that bound lands on
your caller, not on your map.

This skill owns the design of a type-keyed store, not the taste question of whether to erase at
all. `rust-discipline` owns that. Every error text and observed output below comes from rustc
1.97.0, edition 2024, on aarch64-apple-darwin, with Miri 0.1.0 on nightly.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0597]: ... argument requires that s is borrowed for 'static`, or `error: lifetime may not live long enough ... requires that 'a must outlive 'static` | [`Any` is bound to `'static`](#any-is-bound-to-static) |
| You reached for `type_name` because `TypeId::of` refused | [`type_name` is not a type key](#type_name-is-not-a-type-key) |
| Choosing between an enum, a `dyn Any` map, and something exotic | [The ladder](#the-ladder) |
| You must store a `Cow<'a, str>`, a `&'a [u8]`, or any borrow, keyed by type | [Rung 3](#rung-3-an-open-set-of-borrowed-values) |
| `error[E0271]: type mismatch resolving <P<'a> as Element<'a>>::Owner == Tag` | [The bijection is the collision proof](#the-bijection-is-the-collision-proof) |
| `error: incompatible lifetime on type` on an `Owner` or `Element` impl | [The bijection is the collision proof](#the-bijection-is-the-collision-proof) |
| `error[E0277]: the trait bound S: Element<'_> is not satisfied` in a helper | [The helper bound is `for<'x>`](#the-helper-bound-is-forx-not-static) |
| You are writing an extractor, a system param, or a `from_world` | [Where it breaks](#where-it-breaks-an-extractor-that-detaches-the-lifetime) |
| `error[E0117]: only traits defined in the current crate ...` in a user crate | [The orphan rule](#the-orphan-rule-caps-the-pattern-at-one-crate) |

## `Any` is bound to `'static`

`std::any::Any` has exactly one impl: `impl<T: 'static + ?Sized> Any for T`. `TypeId::of::<T>`
carries the same bound. Both are writable for a borrowed type, and neither is satisfiable:
`TypeId::of::<&'a str>()` inside `fn f<'a>()` gives `error: lifetime may not live long enough ...
requires that 'a must outlive 'static`.

The trap is that the bound does not fail where you wrote it. A generic `put<S: Any>` compiles
clean. Region inference propagates the `'static` requirement outward, so the first failure is at
the call site, and it blames a local variable:

```rust,compile_fail
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
refused. That is what makes it dangerous. It renders every lifetime as `'_`, and the std
documentation gives no uniqueness guarantee: the output is diagnostic-only, and two distinct types
may share one string.

```rust
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

Rule: never key a map, a registry, or a cache on `type_name`. Use it in a panic message, a log
line, or an error string, and nowhere else.

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
or with an owned copy at the map boundary. `rust-copy-on-write` has the allocation counts that
decide whether that copy is affordable.

### Rung 3: an open set of borrowed values

Key on a `'static` **owner tag** instead of on the element type, and tie the two together with a
pair of mutually constraining GAT metafunctions. The tag is `'static`, so `TypeId::of` accepts
it. The element carries the lifetime.

```rust
use std::any::TypeId;
use std::borrow::Cow;
use std::cell::UnsafeCell;
use std::collections::HashMap;
use std::marker::PhantomData;
use std::ops::Deref;

trait AnyDrop {}                    // storage and drop only, not `Any`
impl<T> AnyDrop for T {}

trait Owner: 'static { type Element<'a>: Element<'a, Owner = Self>; }   // the key
trait Element<'a>: 'a { type Owner: Owner<Element<'a> = Self>; }       // the value

#[derive(Default)]
struct AnyMap<'a> {
    invariant: PhantomData<UnsafeCell<&'a mut ()>>,
    table: HashMap<TypeId, Box<dyn AnyDrop + 'a>>,
}

impl<'a> AnyMap<'a> {
    fn put<E: Element<'a>>(&mut self, value: E) {
        self.table.insert(TypeId::of::<E::Owner>(), Box::new(value));
    }
    fn get<E: Element<'a>>(&self) -> Option<&E> {
        let boxed = self.table.get(&TypeId::of::<E::Owner>())?;
        let erased: &(dyn AnyDrop + 'a) = Box::deref(boxed);
        // SAFETY: `E: Element<'a>` pins `<E::Owner as Owner>::Element<'a> == E`,
        // an equality the compiler checked at the impl, so the key selects exactly
        // this type. The returned borrow is elided from `&self`, so nothing detaches.
        unsafe {
            (erased as *const (dyn AnyDrop + 'a)
                    as *const <E::Owner as Owner>::Element<'a>).as_ref()
        }
    }
}

struct CowStrTag;
impl Owner for CowStrTag { type Element<'a> = Cow<'a, str>; }
impl<'a> Element<'a> for Cow<'a, str> { type Owner = CowStrTag; }

fn main() {
    let s = String::from("hello world");
    let mut map = AnyMap::default();
    map.put(Cow::from(&s));
    assert_eq!(map.get::<Cow<str>>().map(|c| &**c), Some("hello world"));
}
```

Verdict on this half, measured: it is sound. `cargo +nightly miri run` and
`MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri run` both report no diagnostics. A borrow
shorter than the map is rejected at compile time with `error[E0597]`.

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

`references/gat-anymap.md` has `get_mut`, the drop demonstration, the Miri transcript, and the
list of attacks the trait pair defeats.

## The bijection is the collision proof

Two `TypeId` keys that collide would let `get` cast to the wrong type. The trait pair makes a
collision unconstructible, so the map needs no runtime type check. The compiler rejects each
miswiring at the impl that writes it, not at a use site.

A second tag claiming an element type that is already claimed:

```rust,compile_fail
trait Owner: 'static { type Element<'a>: Element<'a, Owner = Self>; }
trait Element<'a>: 'a { type Owner: Owner<Element<'a> = Self>; }

struct Payload<'a>(&'a str);
struct TagA;
struct TagB;
impl Owner for TagA { type Element<'a> = Payload<'a>; }
impl<'a> Element<'a> for Payload<'a> { type Owner = TagA; }

impl Owner for TagB { type Element<'a> = Payload<'a>; }
```

```text
error[E0271]: type mismatch resolving `<Payload<'a> as Element<'a>>::Owner == TagB`
10 | impl Owner for TagB { type Element<'a> = Payload<'a>; }
   |                                          ^^^^^^^^^^^
note: expected this to be `TagB`
 8 | impl<'a> Element<'a> for Payload<'a> { type Owner = TagA; }
note: required by a bound in `Owner::Element`
```

Every other miswiring is rejected the same way, at the impl:

| Miswiring | Diagnostic |
| --- | --- |
| A tag and its element impl that disagree on `'a` | `error: incompatible lifetime on type`, plus `error[E0308]: mismatched types ... lifetime mismatch` |
| An `Element<'static>`-only impl, to smuggle in a fixed lifetime | `error: incompatible lifetime on type` |
| Shrinking the map by value to shorten `'a` | `error: lifetime may not live long enough`, with `note: the struct AnyMap<'a> is invariant over the parameter 'a` |

The bijection proves key uniqueness. It does not prove that the element uses its lifetime. A tag
whose `Element<'x>` ignores `'x` compiles clean: `impl Owner for String { type Element<'a> = Self; }`
is that shape, and every `'static` element needs it. Do not expect the compiler to reject a GAT
that drops its lifetime. That hole is what the extractor below exploits.

## The helper bound is `for<'x>`, not `'static`

A helper that reads the map but does not know the map's `'a` cannot write `T: 'static`. It must
demand the element trait at every lifetime:

```text
error[E0277]: the trait bound `S: Element<'_>` is not satisfied
58 |         let s = world.get::<S>().expect("must be in world");
   |                       ---   ^ the trait `Element<'_>` is not implemented for `S`
note: required by a bound in `AnyMap::<'a>::get`
23 |     fn get<E: Element<'a>>(&self) -> Option<&E> {
```

The bound that compiles:

```rust,ignore
impl<S: 'static + for<'x> Element<'x>> Extractor for State<&S> { /* ... */ }
```

Adding `'static` alone is the wrong instinct and does not help: `get` is quantified over the
map's `'a`, which the helper impl never names.

## Where it breaks: an extractor that detaches the lifetime

The map is sound. A layer on top that hands closures their arguments — an extractor, a system
param, a `from_world` — is where soundness is lost. This shape is unsound. Do not copy it:

```rust,ignore
trait Extractor {
    type Extracted: ExtractedType;
    unsafe fn from_world(world: &AnyMap) -> Self;   // no lifetime ties to `world`
}
trait ExtractedType: 'static { type Extractor<'a>: Extractor<Extracted = Self>; }
```

`from_world` returns `Self`, whose lifetime is unrelated to `world`. The design then leans on a
higher-ranked bound, `F: for<'a> FnMut(A1::Extractor<'a>, A2::Extractor<'a>)`, to stop the closure
keeping the reference. **That bound is vacuous when `Extractor<'a>` is constant in `'a`.** Nothing
forces a GAT to use its lifetime parameter, so one user impl whose `type Extractor<'a>` reads
`Evil<&'static S>` turns the guarantee off. The closure then gets a real `&'static` into the world
and stores it. Measured: `cargo run` prints `resurrected: ""` after the world is dropped, and both
borrow models call it undefined behaviour.

```text
error: Undefined Behavior: constructing invalid value of type
std::option::Option<&std::string::String>: at .<enum-variant(Some)>.0,
encountered a dangling reference (use-after-free)
   --> src/main.rs:137:35
```

The closure that observes the dangling reference contains no `unsafe` and no `transmute`. The
`unsafe` sits in the user's `from_world`, whose body is byte-for-byte the reference
implementation's own body. The attack is in the paired `ExtractedType` impl, where the GAT drops
`'a`, and that impl is safe code.

The rule: an extraction API must return a type whose signature ties the result to the input
borrow, for example `fn from_world<'w>(world: &'w AnyMap<'w>) -> Self::Out<'w>`. An `unsafe fn`
that returns `Self` gives the caller an obligation no caller can discharge. The runnable exploit
is in `references/gat-anymap.md`.

### The reverse constraint does not fix it

A published version of this design calls the reverse equality constraint on `Extractor` optional,
and predicts that adding it produces `E0207: the lifetime parameter is not constrained by the impl
trait, self type, or predicates`. Both halves are wrong. Declare the constrained pair,
`trait Extractor<'a>: 'a` with `type Extracted: ExtractedType<Extractor<'a> = Self>`, and this
still compiles:

```rust,ignore
impl<'a, S: 'static> Extractor<'a> for Evil<&'static S> { type Extracted = EvilExtracted<S>; }
impl<S: 'static> ExtractedType for EvilExtracted<S> { type Extractor<'a> = Evil<&'static S>; }
```

E0207 asks whether a parameter appears in the impl's trait reference **or** self type.
`impl<'a, S> Extractor<'a> for Evil<&'static S>` names `'a` in the trait reference, so it passes,
and the GAT is still a constant function of `'a`. No bound in Rust forces a GAT to use its
lifetime. The only fix is not to detach the lifetime. The compiled proof is in
`references/gat-anymap.md`.

## The orphan rule caps the pattern at one crate

The registration mechanism that makes rung three safe is a user-written trait impl, and coherence
blocks the user. A downstream crate cannot register a foreign type:

```rust,ignore
impl<'a> Element<'a> for Cow<'a, str> { type Owner = MyCowTag; }   // downstream crate
```

```text
error[E0117]: only traits defined in the current crate can be implemented for types defined outside of the crate
4 | impl<'a> Element<'a> for Cow<'a, str> { type Owner = MyCowTag; }
  | ^^^^^^^^^^^^^^^^^^^^^^^^^------------
  |                          `Cow` is not defined in the current crate
```

Consequences for a published crate:

- Ship `Owner` and `Element` impls for every std type users will store: `Cow<'a, str>`,
  `Cow<'a, [u8]>`, `&'a str`, `&'a [u8]`, `String`, and the integers.
- Document the newtype workaround for everything else. A local `struct MyCow<'a>(Cow<'a, str>)`
  with its own tag compiles downstream and works.
- Do not offer a `register::<T>()` macro to hide the error. It does not remove it.

## Checklist

- Is the value set closed? Use an enum with a lifetime parameter, and stop.
- Can the value be owned or `Arc`-shared at the boundary? Use `HashMap<TypeId, Box<dyn Any>>`,
  and stop.
- No `type_name` appears in a key, a hash, or an equality test.
- No `TypeId::of::<T>` sits under a signature that a borrowed `T` can reach.
- Every `get` on a lifetime-carrying store returns a borrow elided from `&self`, never `&'a`.
- Every stored type has one owner tag, and that tag has one element type.
- Every `unsafe` cast carries a SAFETY comment that names the GAT equality.
- No API returns `Self` from a function whose only lifetime source is a `&` argument.
- A generic helper over stored types is bounded `for<'x> Element<'x>`, not `'static`.
- The store runs clean under `cargo +nightly miri run` and under `-Zmiri-tree-borrows`.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-discipline` | Whether to erase at all: a `downcast_ref` chain is a `match` with the exhaustiveness check removed |
| `rust-unsafe` | The mechanics of the pointer cast, SAFETY comment review, and why a raw pointer never buys a lifetime |
| `rust-sanitizers-miri` | Running Miri, Stacked Borrows against Tree Borrows, and what a clean run does not prove |
| `rust-compiler-errors` | E0597, E0277, E0271 and E0308 in general, beyond the shapes here |
| `rust-copy-on-write` | The allocation cost of owning the value instead of borrowing it, which keeps you on rung two |
| `rust-crate-architecture` | Coherence and the orphan rule as a crate-boundary constraint |
