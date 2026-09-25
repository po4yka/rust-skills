---
name: rust-callback-bounds
description: Use when choosing or repairing the bound on a callback parameter or a stored callable — Fn(&T) -> K, a for<'a> HRTB, a sort_by_key key projection, a visitor, or a struct field that holds a closure (generic F, Box<dyn Fn>, Arc<dyn Fn>, fn pointer field). Triggers on "lifetime may not live long enough" from a closure, "one type is more general than the other", "borrowed data escapes outside of closure", "callback returns a reference", "store a closure in a struct", "function item types cannot be named directly", E0747, E0562, or "reached the recursion limit while instantiating" on a writer or visitor trait.
license: BSD-3-Clause
---

# Rust callback bounds

`for<'a> FnMut(&'a T) -> &'a K` **is legal and compiles on stable**. Only a *separate* generic
parameter, as in `FnMut(&T) -> K`, cannot name the higher-ranked lifetime. Do not reach for a GAT,
a macro crate, or `Box<dyn Fn>` when the callback returns a plain borrow of its argument.

Every quoted diagnostic comes from rustc 1.98.1, edition 2024, on aarch64-apple-darwin.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| Choosing a bound and nothing has failed yet | [Pick the bound from the return type](#pick-the-bound-from-the-return-type) |
| `error: lifetime may not live long enough`, `return type of closure is &'2 ...` | [A free type parameter cannot name 'a](#a-free-type-parameter-cannot-name-a) |
| Callback must return a borrow of its argument | [Return a borrow of the argument](#return-a-borrow-of-the-argument) |
| `error[E0521]: borrowed data escapes outside of closure` | [for<'a> is a no-escape promise](#fora-is-a-no-escape-promise) |
| `error[E0308]: ... one type is more general than the other` | [Closure inference is positional](#closure-inference-is-positional) |
| `error[E0282]: type annotations needed` on a closure argument | [Closure inference is positional](#closure-inference-is-positional). For `\|o\| async move { .. }` against `AsyncFn`, write `async \|o\| ..`; see [Pick the bound](#pick-the-bound-from-the-return-type) |
| `error[E0309]` then `error[E0621]` then `error[E0502]` on one function | [Do not hoist the lifetime](#do-not-hoist-the-lifetime) |
| `sort_by_key` rejects `\|o\| &o.field` | [Change what the callback receives](#change-what-the-callback-receives) |
| Callback output is generic over `'a` and your signature cannot name it | [Generic outputs](#generic-outputs-need-rpitit-or-a-gat) |
| Deciding between `F: Fn`, `Box<dyn Fn>`, and `fn(..)` in a field | [Store a callable in a field](#store-a-callable-in-a-field) |
| `error[E0747]: constant provided when a type was expected` | [Store a callable in a field](#store-a-callable-in-a-field) |
| `error[E0562]: impl Trait is not allowed in field types` | [Store a callable in a field](#store-a-callable-in-a-field) |
| `expected an Fn() closure, found Arc<dyn Fn()>` | Read [storing-callables.md](references/storing-callables.md#arc-and-rc-of-dyn-fn-do-not-implement-fn) |
| `reached the recursion limit while instantiating` on a writer or visitor trait | Read [storing-callables.md](references/storing-callables.md#by-value-impl-trait-plus-a-delegating-impl-is-a-monomorphization-bomb) |
| A `move` closure unexpectedly implements `Fn`, captures a whole owner, or changes drop timing | Read [closure-capture-semantics.md](references/closure-capture-semantics.md) |
| New E0502, E0505, or E0506 on a closure after a toolchain bump, from a `match` or `let` inside it | Read [closure-capture-semantics.md](references/closure-capture-semantics.md#capture-precision-depends-on-the-projection) |
| The callback is `async` | [Pick the bound](#pick-the-bound-from-the-return-type), then the `rust-async-internals` skill |

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
| An async result, awaited on the caller's task | `impl AsyncFn(&T) -> R` (Rust 1.85+) | Yes, as `async \|o\| ..`. `\|o\| async move { .. }` fails with E0282 |
| A future that must be `Send` because the task that awaits it is spawned (`tokio::spawn`), or a callback stored as `Box<dyn ..>` | `impl for<'a> Fn(&'a T) -> Pin<Box<dyn Future<Output = R> + Send + 'a>>` | Yes, when the body is `Box::pin(async move { .. })` |

`AsyncFn` has no stable way to bound its future as `Send`, and it is not dyn compatible:
`Box<dyn AsyncFn(&T) -> R>` is E0038. A generic field `F: AsyncFn(&T) -> R` compiles; only a
type-erased store needs the boxed form. A future that borrows `&T` is not `'static`, so spawning
the callback's own future fails with E0521; take the argument by value or as `Arc<T>` for that.
The `rust-async-internals` skill owns the rest of the async rules.

Add `K: ?Sized` on every `-> &'a K` row. Without it `|o| &o.name` on a `String` field still
works, but `|o| o.name.as_str()` and `|b| &b.bytes[..]` fail, because `str` and `[u8]` are not
`Sized`.

## for<'a> is a no-escape promise

`for<'a>` on a callback bound is machine-checked: the callback cannot store the reference
anywhere that outlives the call. Do not widen it to a fixed `'a` (`impl FnMut(&'a T) -> K` with
`arr: &'a [T]`) to silence E0521. The error means the caller's closure wants to keep a reference
that your API promised it would not keep. When the body does not mutate the collection,
widening compiles and the API silently permits the store from then on. When the body mutates,
widening fails loudly; see [Do not hoist the lifetime](#do-not-hoist-the-lifetime). Fix the
caller, not the bound. Read [hrtb-diagnostics.md](references/hrtb-diagnostics.md#a-fixed-a-permits-the-escape)
when you need the side-by-side example and the full E0521 text.

E0521 also fires for `'static` escapes out of `thread::spawn`. That variant is a different cause
with a different fix; see the `rust-compiler-errors` skill.

## Verify

A bound error appears at the call site, not in your signature. `cargo check` on the library alone
proves nothing about the closures callers write.

| Claim | Check |
| --- | --- |
| The bound accepts the closures callers write | A caller test or doctest that passes inline, unannotated closures: `\|o\| &o.field`, `\|o\| o.name.as_str()`, and one that captures a local. Run `cargo test` |
| The API promises no escape | A minimal `compile_fail` doctest whose closure stores the argument in an outer variable (E0521). If someone widens `for<'a>` to a fixed `'a`, the doctest compiles and the test fails. Stable rustdoc ignores the error code, so pair it with a passing doctest that differs only in the store line; the pair proves the failure comes from the escape |
| A size or allocation claim for a stored callable | A `size_of` assertion, the size probe in [storing-callables.md](references/storing-callables.md#field-sizes-are-measurable), or the counting-allocator probe in [storing-callables.md](references/storing-callables.md#boxdyn-fn-allocates-for-a-non-zero-sized-closure-value) |
| A writer or visitor trait that takes `impl Trait` | A test or example that calls the method with a concrete writer, such as `t.ser(Vec::new())`, then `cargo test` or `cargo build --all-targets`. A library-only `cargo build` instantiates no generic method and exits 0. `cargo check` and `cargo clippy` also miss the recursion-limit error |
| The MSRV accepts the syntax | `cargo +<msrv> check` when `rust-version` is below 1.85 (`AsyncFn`, `async \|..\|`) or 1.87 (`use<..>` in a trait) |

## Checklist

- No `Fn(&T) -> K` with a free `K` where a caller may project a field. Every `-> &'a K` bound has
  an explicit `for<'a>` and `K: ?Sized`.
- No `'a` was hoisted onto the function, and no `for<'a>` was widened, to silence a closure error.
- Every reference-projecting closure is inline, annotated as `fn`/`dyn Fn`, or in `hrtb_ref`. Its
  higher-ranked bound is on `Fn`/`FnMut`/`FnOnce`, not a custom trait.
- `sort_by`, `iter().max_by_key`, or `Vec<&T>` was considered before any projection trait. An
  RPITIT impl repeats `impl Trait + use<..>`, not the concrete type.
- An async callback takes `AsyncFn` unless its future must be `Send` or the callback is `dyn`.
- A public generic type that stores behaviour declares its own trait with a blanket `FnOnce` impl.
  No public struct hands users a value through `-> S<impl Fn(..)>`.
- A field that always holds the same function is not typed `fn(..)`: the coercion silently adds
  one machine word and an indirect call.
- No `Arc<dyn Fn()>` or `Rc<dyn Fn()>` is passed to an `F: Fn()` bound.
- The call trait comes from the closure body, not from `move`. Capture precision and drop timing
  are tested when they affect ownership, `Send`, or cleanup. Read
  [closure-capture-semantics.md](references/closure-capture-semantics.md) when they do.
- No trait method takes a writer or visitor as `impl Trait` by value while a delegating
  `impl<T: Trait + ?Sized> Trait for &mut T` is in scope.
- Every [Verify](#verify) row that the change touches has run and passed.

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

`std` has the same shape. `Vec::sort_by_key` is `FnMut(&T) -> K`, so `v.sort_by_key(|o| &o.country)`
reports the same error, word for word. The error names the closure, so the reflex is to annotate
the closure. No annotation repairs it. The bound is wrong, not the closure. Read
[hrtb-diagnostics.md](references/hrtb-diagnostics.md#a-free-type-parameter-cannot-name-a) when
you need the full diagnostic to match against.

## Do not hoist the lifetime

The first error names a closure, so the reflex is to add a lifetime to the function. Each `help:`
on that path is locally correct, and the path is a dead end. Hoist `'a` into
`impl FnMut(&'a T) -> K` and rustc reports E0309 (add `T: 'a`), E0621 (add `arr: &'a mut [T]`),
and E0502. Follow both `help:` lines and E0502 remains, and no change to the body can fix it: a
fixed `'a` keeps every element handed to the callback borrowed past the loop body, so the body
can never mutate the collection. Stop at the first error, restore the elided argument, and pick a
row from the decision table. Read
[hrtb-diagnostics.md](references/hrtb-diagnostics.md#the-hoisted-lifetime-dead-end) when you need
the terminal code and the three diagnostics.

## Return a borrow of the argument

Put the output inside the binder. The bound accepts an unannotated closure:

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

Write the binder explicitly. Elision refuses a second reference argument with `error[E0106]`;
`for<'a> FnMut(&'a A, &'a B) -> &'a K` compiles and ties both arguments to one region, so give the
second its own `'b` unless you mean to tie them. The shape also works for a `T` that carries a
lifetime, such as `Order<'s>`; a trait with a lifetime parameter can fail there (see
[Generic outputs](#generic-outputs-need-rpitit-or-a-gat)).

## Closure inference is positional

A reference-projecting closure must be written **inline at the call site**. Bind the identical
text to a `let` first (`let g = |o: &Order| &o.country; register(g);`) and it stops satisfying the
identical bound: `lifetime may not live long enough` on the `let`, then
`error[E0308]: ... one type is more general than the other` on the call.

Closure signature inference reads the *expectation* at the closure expression. At a call site the
expectation is the higher-ranked parameter bound, so the closure is inferred higher-ranked. A bare
`let` supplies none, so each region resolves to one fixed region. An annotation supplies the
expectation: `let g: fn(&Order) -> &String = |o| &o.country;` compiles for a closure that captures
nothing, and `&dyn for<'a> Fn(&'a Order) -> &'a String` works for a capturing closure. Or route
the `let` through one generic identity function. One copy serves the whole crate:

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

Only an `Fn`, `FnMut`, or `FnOnce` obligation supplies the expectation. Put the higher-ranked
bound on your own trait (`where for<'a> F: MyTrait<&'a T>`) and **every** closure form fails:
E0282 unannotated, `lifetime may not live long enough` annotated, even with the return type
annotated. Pass a named `fn`, whose item type is already higher-ranked, or wrap the closure in
`hrtb_ref(..)`. Read [hrtb-diagnostics.md](references/hrtb-diagnostics.md) when you need the
worked examples and the full diagnostics.

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
because no `Fn` bound can write `-> K<'a>`. `impl FnMut(&T) -> impl Ord` is rejected:
``error[E0562]: `impl Trait` is not allowed in the return type of `Fn` trait bounds``. Declare a
one-method trait with `fn project<'a>(&mut self, i: &'a In) -> impl Ord + use<'a, Self, In>`, and
have callers pass a named unit struct instead of a closure. That loss of the closure is the cost
of this row. `use<..>` in a trait method needs Rust 1.87, and it is load-bearing: without it the
result also captures the `&mut self` borrow, and two calls in one comparison fail with E0499.

Read [storing-callables.md](references/storing-callables.md#composite-outputs-rpitit) when you
write this trait. It has the runnable examples and three traps: repeat `impl Ord + use<..>` in
the impl (a concrete type triggers `refining_impl_trait`), keep the lifetime off the trait
(`for<'a> K: KeyProjection<'a, T>` breaks on a borrowed `T`), and use a GAT `type Out<'a>` when
callers must name the output.

## Store a callable in a field

Four shapes, and the choice is not stylistic.

| Field type | Size | Captures | Different expressions in one `Vec` | Caller can name the type | Allocates |
| --- | --- | --- | --- | --- | --- |
| `F` on `struct S<F: Fn(u32)>` | Size of `F`. 0 for a non-capturing closure | Yes | No, `E0308` | No, `E0747` / `E0562` | No |
| `Box<dyn Fn(u32)>` | Two machine words, fat pointer | Yes | Yes | Yes | Only if the closure value is not zero-sized |
| `fn(u32)` | One machine word | **No** | Yes | Yes | No |
| `B` on `struct S<B: MyTrait>` with a blanket impl | Size of `B`. 0 for a user unit struct | Yes | No | Yes, if the user declares a named type | No |

The coercion to `fn(u32)` is silent: no warning, no lint. Read
[storing-callables.md](references/storing-callables.md#field-sizes-are-measurable) when you
need the size probe.

`Box` of a zero-sized value does not call the allocator. A non-capturing closure is a ZST, and so
is a closure that captures only zero-sized values. Measure the closure value with `size_of_val`;
capture presence alone is not the rule. Read
[storing-callables.md](references/storing-callables.md#boxdyn-fn-allocates-for-a-non-zero-sized-closure-value)
when you must prove an allocation claim.

A caller cannot write the type of a generic callable field. A `fn` item path in type position is
`error[E0747]: constant provided when a type was expected` ("function item types cannot be named
directly"). Returning `-> Gadget<impl Fn(u32)>` only defers the problem: a field typed
`Gadget<impl Fn(u32)>` is ``error[E0562]: `impl Trait` is not allowed in field types``. The
generic parameter does not block `dyn`: implement your own trait for `Gadget<F>` and box that.
Read [storing-callables.md](references/storing-callables.md#a-generic-callable-field-cannot-be-named)
when you need the three compile-checked examples.

A public generic type that stores user-supplied behaviour declares its own one-method trait plus
a blanket impl over `FnOnce`. Callers keep passing closures, and a caller who needs a nameable,
zero-sized callable implements the trait for a unit struct. Coherence accepts both impls because
`fn_traits` is unstable, so no crate can implement `FnOnce` for that struct. There is no stable
shortcut: `type OnDrop = impl FnOnce(u32);` in an associated type is still `error[E0658]` on
1.98.1, issue #63063. Read
[storing-callables.md](references/storing-callables.md#declare-your-own-callable-trait) when you
write the trait.

## Related skills

Use these skills when they are installed.

| Skill | Boundary |
| --- | --- |
| `rust-discipline` | API review of stored callbacks: `Box<dyn Fn>` over `Box<dyn FnMut>`, `&'a mut` fields, forwarding impls |
| `rust-compiler-errors` | Reading E0521, E0502, and E0277 in general, beyond the callback shapes here |
| `rust-async-internals` | Every other `async` callback rule: `AsyncFn`, boxed `Send` futures, spawn |
| `rust-iterator-impl` | The producing side, when the answer is a lending iterator rather than a callback |
| `rust-performance` | Build-time cost of a by-value `impl Trait` parameter (`cargo --timings`, `llvm-lines`) |
| `rust-lints` | The `refining_impl_trait` lint and the workspace lint tables that gate it |
