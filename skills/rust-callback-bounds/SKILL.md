---
name: rust-callback-bounds
description: Use when you shape a callable in a public signature — a callback bound such as Fn(&T) -> K, a key projection, a visitor, or a struct field that holds a closure. Covers which bound accepts which closure, why for<'a> FnMut(&'a T) -> &'a K compiles today while a free type parameter cannot name the higher-ranked lifetime, HRTB as a no-escape promise, closure signature inference by syntactic position, the E0309 E0621 E0502 cascade that follows from hoisting a lifetime, and the cost table for a generic F field against Box<dyn Fn> and a bare fn pointer field. Triggers on "lifetime may not live long enough" from a closure, "one type is more general than the other", "borrowed data escapes outside of closure", "for<'a>", "hrtb", "sort_by_key", "callback returns a reference", "store a closure in a struct", "Box<dyn Fn>", "fn pointer field", "E0747", "E0562", "Arc<dyn Fn>", "reached the recursion limit while instantiating", or "function item types cannot be named directly".
license: BSD-3-Clause
---

# Rust callback bounds

## Purpose

Two decisions, one subject: how to bound a callback parameter so the closures your callers write
are accepted, and how to store a callable in a struct field so your users can still name the type.

The sentence to get right: `for<'a> FnMut(&'a T) -> &'a K` **is legal and compiles today**. Only a
*separate* generic parameter, as in `FnMut(&T) -> K`, cannot name the higher-ranked lifetime. Do
not reach for a GAT, a macro crate, or `Box<dyn Fn>` when the callback returns a plain borrow of
its argument.

Every diagnostic, size, and allocation count below comes from rustc 1.97.0, edition 2024, on
aarch64-apple-darwin.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| Choosing a bound and nothing has failed yet | [Pick the bound from the return type](#pick-the-bound-from-the-return-type) |
| `error: lifetime may not live long enough`, `return type of closure is &'2 ...` | [A free type parameter cannot name 'a](#a-free-type-parameter-cannot-name-a) |
| Callback must return a borrow of its argument | [Return a borrow of the argument](#return-a-borrow-of-the-argument) |
| `error[E0521]: borrowed data escapes outside of closure` | [for<'a> is a no-escape promise](#fora-is-a-no-escape-promise) |
| `error[E0308]: ... one type is more general than the other` | [Closure inference is positional](#closure-inference-is-positional) |
| `error[E0282]: type annotations needed` on a closure argument | [Closure inference is positional](#closure-inference-is-positional) |
| `error[E0309]` then `error[E0621]` then `error[E0502]` on one function | [Do not hoist the lifetime](#do-not-hoist-the-lifetime) |
| `sort_by_key` rejects `\|o\| &o.field` | [Change what the callback receives](#change-what-the-callback-receives) |
| Callback output is generic over `'a` and your signature cannot name it | [Generic outputs](#generic-outputs-need-rpitit-or-a-gat) |
| Deciding between `F: Fn`, `Box<dyn Fn>`, and `fn(..)` in a field | [Store a callable in a field](#store-a-callable-in-a-field) |
| `error[E0747]: constant provided when a type was expected` | [Store a callable in a field](#store-a-callable-in-a-field) |
| `error[E0562]: impl Trait is not allowed in field types` | [Store a callable in a field](#store-a-callable-in-a-field) |
| `Fn()` is not implemented for `Arc<dyn Fn()>` | `references/storing-callables.md` |
| `error: reached the recursion limit while instantiating` | `references/storing-callables.md` |
| The callback is `async` | `rust-async-internals` |

## Pick the bound from the return type

Read the row that matches what the callback returns. The argument is always `&T`.

| The callback returns | Write this bound | Accepts a bare closure |
| --- | --- | --- |
| Nothing borrowed, no reference at all | `impl Fn(T) -> U` | Yes |
| One concrete type, named in your signature | `impl Fn(&T) -> String` | Yes |
| A free type parameter `K` of the outer function | `impl Fn(&T) -> K` | **No** for a projection that borrows from the argument. A projection through an inner reference (`T = &U`) is accepted |
| A borrow of the argument | `impl for<'a> Fn(&'a T) -> &'a K`, plus `K: ?Sized` | Yes |
| A composite over `'a` your signature can name | `impl for<'a> FnMut(&'a T) -> Reverse<&'a str>` | Yes |
| An output that stays a type parameter over `'a` | Your own trait with RPITIT, or with a GAT | No. Pass a named unit struct |
| A `Future` that borrows the argument | `Pin<Box<dyn Future<Output = R> + Send + 'a>>`. See `rust-async-internals` | No |

Add `K: ?Sized` on every `-> &'a K` row. Without it `|o| &o.name` on a `String` field still
works, but `|o| o.name.as_str()` and `|b| &b.bytes[..]` fail, because `str` and `[u8]` are not
`Sized`.

## A free type parameter cannot name 'a

`impl FnMut(&T) -> K` desugars to `for<'a> FnMut(&'a T) -> K`. The binder introduces `'a`, but
`K` was fixed at the outer function's scope, before `'a` existed. No closure that returns a borrow
of its argument can satisfy it:

```rust,compile_fail
struct Order { country: String }

fn sort_by_key<T, K: Ord>(_arr: &mut [T], _key: impl FnMut(&T) -> K) {}

fn process(orders: &mut [Order]) {
    sort_by_key(orders, |order| &order.country);
}
```

```text
error: lifetime may not live long enough
7 |     sort_by_key(orders, |order| &order.country);
  |                          ------ ^^^^^^^^^^^^^^ returning this value requires that `'1` must outlive `'2`
  |                          |    |
  |                          |    return type of closure is &'2 String
  |                          has type `&'1 Order`
```

`std` has the same shape. `Vec::sort_by_key` is `FnMut(&T) -> K`, so `v.sort_by_key(|o| &o.country)`
reports the same error, word for word. The error names the closure, so the reflex is to annotate
the closure. No annotation repairs it. The bound is wrong, not the closure.

## Return a borrow of the argument

Put the output inside the binder. `for<'a> FnMut(&'a T) -> &'a K` is valid syntax, it compiles on
stable, and it accepts an unannotated closure:

```rust
struct Order { country: String, code: u32 }

fn sort_by_key_ref<T, K: Ord + ?Sized>(
    arr: &mut [T],
    mut key: impl for<'a> FnMut(&'a T) -> &'a K,
) {
    for i in 0..arr.len() {
        for j in (i + 1)..arr.len() {
            if key(&arr[j]) < key(&arr[i]) { arr.swap(i, j); }
        }
    }
}

fn main() {
    let mut v = vec![
        Order { country: "cz".into(), code: 3 },
        Order { country: "at".into(), code: 1 },
    ];
    sort_by_key_ref(&mut v, |o| &o.country); // bare closure, no annotation
    assert_eq!(v[0].code, 1);
}
```

The `&mut [T]` receiver stays mutable inside the body. That is the whole point: the higher-ranked
`'a` ends at each call, so no borrow of an element survives to block `arr.swap`.

The minimal form compiles too, with both an annotated and an unannotated closure:

```rust
fn register<F: for<'a> FnMut(&'a str) -> &'a str>(_f: F) {}

fn main() {
    register(|s: &str| s);
    register(|s| s);
}
```

Write the binder explicitly so the shared region is visible in the signature. Elision refuses a
second reference argument with `error[E0106]`; the explicit `for<'a> FnMut(&'a A, &'a B) -> &'a K`
compiles and ties both arguments to one region, so give the second its own `'b` unless you mean to
tie them. The shape also works when `T` itself carries a lifetime, such as `Order<'s>`. A trait
with a lifetime parameter does not; see `references/storing-callables.md`.

## for<'a> is a no-escape promise

`for<'a>` on a callback bound is machine-checked: the callback cannot store the reference
anywhere that outlives the call. A fixed `'a` silently permits the store.

```rust,compile_fail
struct Order { code: u32 }

// Fixed 'a: the callback IS allowed to keep the reference.
fn visit_fixed<'a, T, K>(arr: &'a [T], mut key: impl FnMut(&'a T) -> K) {
    for e in arr { key(e); }
}
// HRTB: the callback cannot name any place that outlives the call.
fn visit_hrtb<T, K>(arr: &[T], mut key: impl for<'x> FnMut(&'x T) -> K) {
    for e in arr { key(e); }
}

fn main() {
    let v = vec![Order { code: 7 }];
    let mut stash: Option<&Order> = None;
    visit_fixed(&v, |o| { stash = Some(o); });  // accepted
    assert_eq!(stash.unwrap().code, 7);

    let mut stash2: Option<&Order> = None;
    visit_hrtb(&v, |o| { stash2 = Some(o); });  // error[E0521]
}
```

```text
error[E0521]: borrowed data escapes outside of closure
18 |     let mut stash2: Option<&Order> = None;
   |         ---------- `stash2` declared here, outside of the closure body
19 |     visit_hrtb(&v, |o| { stash2 = Some(o); });
   |                     -    ^^^^^^^^^^^^^^^^ `o` escapes the closure body here
   |                     |
   |                     `o` is a reference that is only valid in the closure body
```

Do not widen the lifetime to silence this. E0521 here means the caller's closure wants to keep a
reference that your API promised it would not keep. Widening compiles whenever your body does
not also mutate the collection — `visit_fixed` above is proof. The API then silently permits the
store and no diagnostic ever appears. Widening fails loudly when the body mutates; see
[Do not hoist the lifetime](#do-not-hoist-the-lifetime). Treat E0521 as a signal to fix the
caller, never to relax the bound.

E0521 also fires for `'static` escapes out of `thread::spawn`. That variant is a different cause
with a different fix; see `rust-compiler-errors`.

## Closure inference is positional

A reference-projecting closure must be written **inline at the call site**. Bind the identical
text to a `let` first and it stops satisfying the identical bound:

```rust,compile_fail
struct Order { country: String }
fn register<F: for<'a> FnMut(&'a Order) -> &'a String>(_f: F) {}

fn main() {
    register(|o: &Order| &o.country);  // OK: the expectation is higher-ranked

    let g = |o: &Order| &o.country;    // error: lifetime may not live long enough
    register(g);                       // error[E0308]: one type is more general
}
```

```text
error: lifetime may not live long enough
7 |     let g = |o: &Order| &o.country;
  |                 -     - ^^^^^^^^^^ returning this value requires that `'1` must outlive `'2`

error[E0308]: mismatched types
8 |     register(g);
  |     ^^^^^^^^^^^ one type is more general than the other
  |
  = note: expected reference `&String`
             found reference `&'a String`
```

The cause is not the compiler version. Closure signature inference reads the *expectation* at the
closure expression. At a call site the expectation is the higher-ranked parameter bound, so the
closure is inferred higher-ranked. A bare `let` supplies no expectation, so each region becomes a
fresh inference variable and resolves to one fixed region. An annotation supplies the expectation:
`let g: fn(&Order) -> &String = |o| &o.country;` makes the closure higher-ranked, and `register(g)`
compiles. That form needs an empty capture set; for a capturing closure annotate
`&dyn for<'a> Fn(&'a Order) -> &'a String`, or use `hrtb_ref` below.

To keep a `let`, route it through one generic identity function. One copy serves the whole crate:

```rust
fn hrtb_ref<In, Out: ?Sized, F>(f: F) -> F
where
    F: for<'a> FnMut(&'a In) -> &'a Out,
{
    f
}

struct Order { country: String }
fn register<F: for<'a> FnMut(&'a Order) -> &'a String>(_f: F) {}

fn main() {
    let g = hrtb_ref::<Order, String, _>(|o| &o.country);
    register(g);
}
```

Do not add a macro crate for this, and do not write a per-type `force_hrtb`. The turbofish is
needed only when the surrounding call leaves `In` or `Out` ambiguous.

### A custom trait supplies no expectation at all

The expectation comes only from an `Fn`, `FnMut`, or `FnOnce` obligation. Put the higher-ranked
bound on your own trait — `where for<'a> F: MyTrait<&'a T>` — and **every** closure form fails.
An unannotated closure gives `error[E0282]: type annotations needed`. An annotated parameter gives
`error: lifetime may not live long enough`. Annotating the return type as well gives the same
lifetime error. A named `fn` item is accepted, because a `fn` item's lifetimes are late bound at
declaration, so its item type is already higher-ranked.

Two escapes: pass a named `fn`, or wrap the closure in `hrtb_ref(..)`. The worked example and the
three diagnostics are in `references/storing-callables.md`.

## Do not hoist the lifetime

The first error names a closure, so the reflex is to add a lifetime to the function. rustc walks
you into a dead end and each `help:` on the way is locally correct.

```rust,compile_fail
// Terminal state of the "just add lifetimes" path. E0502, unfixable in the body.
fn sort_by_key<'a, T: 'a, K: Ord>(arr: &'a mut [T], mut key: impl FnMut(&'a T) -> K) {
    for i in 0..arr.len() {
        for j in (i + 1)..arr.len() {
            if key(&arr[j]) < key(&arr[i]) { arr.swap(i, j); }
        }
    }
}
```

From `fn sort_by_key<'a, T, K: Ord>(arr: &mut [T], mut key: impl FnMut(&'a T) -> K)`, rustc
reports all three at once:

```text
error[E0309]: the parameter type `T` may not live long enough
help: consider adding an explicit lifetime bound       // T: 'a

error[E0621]: explicit lifetime required in the type of `arr`
4 |             if key(&arr[j]) < key(&arr[i]) { arr.swap(i, j); }
  |                ^^^^^^^^^^^^ lifetime `'a` required
help: add explicit lifetime `'a` to the type of `arr`  // arr: &'a mut [T]

error[E0502]: cannot borrow `*arr` as mutable because it is also borrowed as immutable
4 |             if key(&arr[j]) < key(&arr[i]) { arr.swap(i, j); }
  |                ------------                  ^^^^^^^^^^^^^^ mutable borrow occurs here
  |                |   |
  |                |   immutable borrow occurs here
  |                argument requires that `arr[_]` is borrowed for `'a`
```

The E0502 is terminal. A fixed `'a` makes every element handed to the callback stay borrowed for
the whole of `'a`, which outlives the loop body, so the body can never mutate the collection. Two
`help:` lines were followed and the function is now unwriteable. Stop at the first error, restore
the elided argument, and pick a row from the decision table instead.

## Change what the callback receives

Before you build a projection DSL, change what the callback is handed. These both compile with
the very projection `Vec::sort_by_key` rejects:

```rust
struct Order { country: String, code: u32 }

fn main() {
    let v = vec![
        Order { country: "cz".into(), code: 3 },
        Order { country: "at".into(), code: 1 },
    ];
    // v.sort_by_key(|o| &o.country);   // would NOT compile

    let m = v.iter().max_by_key(|o| &o.country).unwrap();
    assert_eq!(m.code, 3);

    let mut refs: Vec<&Order> = v.iter().collect();
    refs.sort_by_key(|o| &o.country);
    assert_eq!(refs[0].code, 1);
}
```

For an iterator of `&'s T` the closure parameter is `&'x &'s T`. `&o.country` reborrows through
the inner `&'s T` and yields `&'s String`, whose lifetime the collection fixes, not the callback
binder. The higher-ranked `'x` never reaches the output, so a fixed `K` is satisfiable.

`Vec::sort_by(|a, b| a.country.cmp(&b.country))` is the third escape and needs no new type at
all. Reach for it before any of the trait machinery below.

## Generic outputs need RPITIT or a GAT

A composite your signature can name still fits a higher-ranked `Fn` bound.
`impl for<'a> FnMut(&'a T) -> Reverse<&'a str>` and `impl for<'a> FnMut(&'a T) -> (&'a str, u32)`
both accept a bare closure. Reach for a trait only when the output must stay a type *parameter*,
because no `Fn` bound can write `-> K<'a>`. `impl FnMut(&T) -> impl Ord` is not even valid syntax:
``error[E0562]: `impl Trait` is not allowed in the return type of `Fn` trait bounds``. Declare a
one-method trait with `fn project<'a>(&mut self, i: &'a In) -> impl Ord + use<'a, Self, In>`, and
have callers pass a named unit struct instead of a closure. That loss of the closure is the cost
of this row.

Three traps, all in `references/storing-callables.md` with the runnable examples: writing the
concrete type in the impl instead of `impl Ord + use<..>` triggers the on-by-default
`refining_impl_trait` lint; a lifetime parameter on the trait (`for<'a> K: KeyProjection<'a, T>`)
silently forces `T: 'static`; and a GAT `type Out<'a>` is the shape to use when callers must name
the output as an associated type.

## Store a callable in a field

Three shapes, and the choice is not stylistic.

| Field type | Size | Captures | Two instances in one `Vec` | Caller can name the type | Allocates |
| --- | --- | --- | --- | --- | --- |
| `F` on `struct S<F: Fn(u32)>` | Size of `F`. 0 for a non-capturing closure | Yes | No, `E0308` | No, `E0747` / `E0562` | No |
| `Box<dyn Fn(u32)>` | 16, fat pointer | Yes | Yes | Yes | Only if the closure captures |
| `fn(u32)` | 8 | **No** | Yes | Yes | No |
| `B` on `struct S<B: MyTrait>` with a blanket impl | Size of `B`. 0 for a user unit struct | Yes | No | Yes, if the user declares a named type | No |

The sizes are measurable, and the coercion to `fn(u32)` is silent — no warning, no lint:

```rust
fn h(_: u64) {}

fn main() {
    let f = h;
    assert_eq!(size_of_val(&f), 0);              // fn item: its own ZST
    let g: fn(u64) = h;
    assert_eq!(size_of_val(&g), 8);              // coerced: a real code pointer
    assert_eq!(size_of::<Box<dyn Fn()>>(), 16);  // fat pointer
    assert_eq!(size_of::<&dyn Fn()>(), 16);
}
```

`Box<dyn Fn(..)>` does **not** allocate for a non-capturing closure: `Box` of a ZST never calls
the allocator. Measured with a counting global allocator, `Box::new(|| {}) as Box<dyn Fn()>` costs
0 allocations and `Box::new(move || { let _ = &s; })` costs 1. Do not avoid `Box<dyn Fn>` for a
stateless callback on allocation grounds; the residual cost is 16 bytes inline and one indirect
call. See `references/storing-callables.md`.

### The generic field blocks naming, not `dyn`

A function item has no surface syntax. In type position the parser reads the path as a const
generic argument, so the diagnostic is about constants:

```rust,compile_fail
struct DropGuard<T, F: FnOnce(T)>(T, F);
fn report(_: u32) {}
struct Gadget { not_used: DropGuard<u32, report> }
```

```text
error[E0747]: constant provided when a type was expected
3 | struct Gadget { not_used: DropGuard<u32, report> }
  |                                          ^^^^^^
  = help: `report` is a function item, not a type
  = help: function item types cannot be named directly
```

Returning `-> Gadget<impl Fn(u32)>` only defers the problem. The value flows on into generic
positions, but the caller can never *name* it, so a field type that must be written is E0562:

```rust,compile_fail
struct Gadget<F: Fn(u32)> { f: F }
fn new_gadget() -> Gadget<impl Fn(u32)> { Gadget { f: |x| { let _ = x; } } }
struct Holder { g: Gadget<impl Fn(u32)> }
```

```text
error[E0562]: `impl Trait` is not allowed in field types
3 | struct Holder { g: Gadget<impl Fn(u32)> }
  |                           ^^^^^^^^^^^^
  = note: `impl Trait` is only allowed in arguments and return types of functions and methods
```

What the generic parameter does **not** block is `dyn`. Erasure happens at your trait, not at the
struct, so every monomorphisation gets a vtable:

```rust
struct Gadget<F: Fn(u32)> { f: F }
trait Run { fn run(&self); }
impl<F: Fn(u32)> Run for Gadget<F> { fn run(&self) { (self.f)(1) } }

fn main() {
    let a = Gadget { f: |x| assert_eq!(x, 1) };
    let b = Gadget { f: |x| assert!(x > 0) };
    // vec![a, b] is E0308: "no two closures, even if identical, have the same type"
    let v: Vec<Box<dyn Run>> = vec![Box::new(a), Box::new(b)];
    for g in &v { g.run(); }
}
```

### Declare your own callable trait

This is the shape for a public generic type that stores user-supplied behaviour. One method, plus
a blanket impl over `FnOnce`. Callers keep passing closures. A caller who needs a nameable,
zero-sized callable declares one:

```rust
pub trait DropBehavior<T> { fn on_drop(self, val: T); }

impl<T, F: FnOnce(T)> DropBehavior<T> for F {
    fn on_drop(self, val: T) { self(val) }
}

pub struct DropGuard<T, B: DropBehavior<T>> {
    val: std::mem::ManuallyDrop<T>,
    beh: std::mem::ManuallyDrop<B>,
}

// A downstream crate can name this. A closure type has no name.
pub struct ReportNotUsed;
impl DropBehavior<u32> for ReportNotUsed {
    fn on_drop(self, v: u32) { assert_eq!(v, 7); }
}

fn main() {
    assert_eq!(size_of::<DropGuard<u32, ReportNotUsed>>(), 4);
    assert_eq!(size_of::<DropGuard<u32, fn(u32)>>(), 16);
    ReportNotUsed.on_drop(7u32);
    (|v: u32| assert_eq!(v, 7)).on_drop(7u32);
}
```

Coherence accepts the second impl, here and across a crate boundary, because `ReportNotUsed` does
not satisfy `FnOnce(u32)` and rustc knows every impl a local type has. The `fn_traits` gate keeps
this true: no crate can add the `FnOnce` impl that would create the overlap. The payoff is in the
two `size_of` lines: 4 bytes against 16.

There is no stable shortcut. `type OnDrop = impl FnOnce(u32);` in an associated type is
`error[E0658]`, issue #63063. Write the trait.

## Checklist

- No callback bound of the form `Fn(&T) -> K` where `K` is a free type parameter and a caller may
  project a field.
- Every `-> &'a K` bound carries an explicit `for<'a>` and a `K: ?Sized`.
- No `'a` was hoisted onto the enclosing function, and no `for<'a>` was widened to a fixed `'a`,
  to silence a closure error.
- Every reference-projecting closure is inline, annotated as `fn`/`dyn Fn`, or in `hrtb_ref`.
- A higher-ranked bound a closure must satisfy lives on `Fn`/`FnMut`/`FnOnce`, not a custom trait.
- `sort_by`, `iter().max_by_key`, or `Vec<&T>` was considered before any projection trait.
- A trait method that returns `impl Trait` repeats the opaque form in the impl, with `use<..>`.
- No public struct hands users a value through `-> S<impl Fn(..)>`.
- A callable field that is always the same function is not typed `fn(..)`; that coercion costs 8
  bytes silently.
- A public generic type that stores behaviour declares its own trait with a blanket `FnOnce` impl.
- No `Arc<dyn Fn()>` or `Rc<dyn Fn()>` is passed to an `F: Fn()` bound.
- No trait method takes a writer or visitor as `impl Trait` **by value** while a delegating
  `impl<T: Trait + ?Sized> Trait for &mut T` is in scope.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-discipline` | The API-review checklist this skill supplies the callback rows for: `Box<dyn Fn>` against `Box<dyn FnMut>`, lifetime infection, delegating impls |
| `rust-compiler-errors` | Reading E0521, E0502, E0277, and E0107 in general, beyond the callback shapes here |
| `rust-async-internals` | An `async` callback over a reference: `AsyncFn`, `Pin<Box<dyn Future + Send + 'a>>`, and the `Send` bound that spawn needs |
| `rust-iterator-impl` | The producing side, when the answer is a lending iterator rather than a callback |
| `rust-performance` | Build-time cost of a by-value `impl Trait` parameter, measured with `cargo --timings` and `llvm-lines` |
| `rust-lints` | The `refining_impl_trait` lint and the workspace lint tables that gate it |
