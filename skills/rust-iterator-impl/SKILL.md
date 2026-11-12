---
name: rust-iterator-impl
description: Use when writing a custom iterator or making a type iterable, to implement Iterator, IntoIterator, FromIterator, Extend, size_hint, ExactSizeIterator, or DoubleEndedIterator. Triggers on a for loop or collect that rejects a container, a lending iterator and E0207, an ExactSizeIterator len panic, an unconditional_recursion warning in into_iter, E0658 on impl Trait in an associated IntoIter type, enumerate().rev() needing ExactSizeIterator, and iter::from_fn in place of a nightly gen block. Not for calling-side combinator style (rust-code-style) or iteration speed (rust-hot-path).
license: BSD-3-Clause
---

# Rust iterator impl

Every error text, warning, and number below comes from rustc 1.98.1, edition 2024, on
aarch64-apple-darwin.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0277]: &Bag is not an iterator` on `for v in &bag` | [The three IntoIterator impls](#the-three-intoiterator-impls) |
| `error[E0658]: impl Trait in associated types is unstable` on `type IntoIter` | [The three IntoIterator impls](#the-three-intoiterator-impls) |
| `warning: function cannot return without recursing`, then `has overflowed its stack` | [Never call self.into_iter() in the impl](#never-call-selfinto_iter-in-the-impl) |
| `error[E0277]: a value of type X cannot be built from an iterator` | [A collection newtype needs four impls](#a-collection-newtype-needs-four-impls) |
| `error[E0207]: the lifetime parameter 'a is not constrained` | [Iterator cannot borrow from itself](#iterator-cannot-borrow-from-itself) |
| A panic inside `core/src/iter/traits/exact_size.rs` | [size_hint is a contract](#size_hint-is-a-contract) |
| `error[E0277]: ... ExactSizeIterator is not satisfied`, pointing at `.rev()` | [Adapter order](#adapter-order-enumeraterev-needs-exactsizeiterator) |
| `error[E0658]: gen blocks are experimental` | [Stateful generators](#stateful-generators-use-iterfrom_fn) |
| `error[E0432]: unresolved import std::ops::Generator` | [Stateful generators](#stateful-generators-use-iterfrom_fn) |
| The impls are correct, and iteration is slow | the `rust-hot-path` skill |

## Verify

Set these lint levels once. Use `[workspace.lints.*]` with `[lints] workspace = true` in each
member, or `[lints.*]` in a single-package manifest.

```toml
[workspace.lints.rust]
unconditional_recursion = "deny"

[workspace.lints.clippy]
iter_without_into_iter = "warn"
into_iter_without_iter = "warn"
```

While you iterate, run `cargo test --locked -p <crate>`. Before commit, run
`cargo clippy --locked --workspace --all-targets -- -D warnings`. The `rust-lints` skill owns
the full lint tables and the workspace gate.

| Check | Catches |
| --- | --- |
| `unconditional_recursion = "deny"` | An `into_iter` body that calls itself directly |
| `clippy::iter_without_into_iter`, `clippy::into_iter_without_iter` (pedantic, allow by default) | An exported (reachable from the crate root) `iter` or `iter_mut` without its `IntoIterator for &T` or `&mut T`, and the reverse |
| `clippy::should_implement_trait` (style, warn by default) | An inherent `fn next` or `fn into_iter` on an exported type |
| A test that calls `next()` once, then asserts `size_hint()` and `len()` | A wrapper that drops `size_hint`, and an off-by-one after partial use |
| A test on `(index, element)` pairs | A swap of `enumerate().rev()` and `rev().enumerate()` |
| A test that alternates `next` and `next_back` to the end | A `next_back` that yields one element twice or skips one |

A green lint run proves little. The clippy lints skip every type that is not
exported, including a `pub` type in a private module. No lint
sees a missing `IntoIterator for T`, `FromIterator`, or `Extend`, a wrong `size_hint`, or
recursion through a second function. The tests above and the
[review checklist](#review-checklist) cover those.

## Review checklist

The change is done when the Verify commands pass and a reading confirms each item:

- Every container that a `for` loop iterates has `IntoIterator` for `T` and `&T`, and for
  `&mut T` when the type hands out mutable access to its elements.
- A collection newtype has `FromIterator` and `Extend`, not a `Deref` that pretends to.
- A `Deref` on a newtype targets `[T]` or `str`, never the owning collection.
- On a type that is not exported, no inherent `fn into_iter` or `fn next` exists.
- No `IntoIterator::into_iter` body reaches `self.into_iter()`, directly or through a helper.
  Each body names the concrete constructor, such as `self.items.into_iter()`. See
  [Never call self.into_iter() in the impl](#never-call-selfinto_iter-in-the-impl).
- A 1:1 iterator newtype forwards `size_hint` and each trait of the inner iterator. Any other
  wrapper computes its own `size_hint`.
- Every `ExactSizeIterator` impl has a `size_hint` override that returns `(n, Some(n))`. The
  default `len()` panics otherwise.
- No `ExactSizeIterator` impl on a source whose count is unknown before iteration.
- No `enumerate().rev()` after `filter`, `flat_map`, `take_while`, `chars`, or `chain`.
- No iterator escapes E0207 through a raw pointer or `RefCell::as_ptr`. The yielded reference
  outlives the tracked borrow, which is unsound. See
  [Iterator cannot borrow from itself](#iterator-cannot-borrow-from-itself).
- A generator uses `iter::from_fn`, `successors`, or `repeat_with`, not a nightly `gen` block.

## The three IntoIterator impls

An inherent `fn iter(&self)` serves `bag.iter()` and nothing else. The `for` loop and every
`I: IntoIterator` bound resolve through the trait, so a container that offers only `iter`
fails at the call site:

```text
error[E0277]: `&Bag` is not an iterator
5 |     for v in &b { println!("{v}"); }
  |              ^^ `&Bag` is not an iterator
  = help: the trait `Iterator` is not implemented for `&Bag`
  = note: required for `&Bag` to implement `IntoIterator`
```

The error names the call site, so the usual repair is `for v in b.iter()`. That hides the
defect instead of fixing it. Write all three impls once, on the container: `&'a C`, `&'a mut C`,
and `C`. Read [references/impl-examples.md](references/impl-examples.md#the-three-intoiterator-impls-on-one-container)
when you write the impls: it has a run-tested container with all three, a forwarding wrapper
iterator, and the inherent `iter` and `iter_mut` they delegate to.

Rules:

- Do not add an inherent `fn into_iter`. Clippy asks you to delete it:
  `warning: method into_iter can be confused for the standard trait method
  std::iter::IntoIterator::into_iter`, lint `clippy::should_implement_trait`.
- Keep the inherent `iter` and `iter_mut`. The borrowing trait impls delegate to them, and
  `clippy::iter_without_into_iter` checks that each has its trait impl.
- A newtype that yields exactly the inner iterator's items forwards `size_hint` and
  re-implements each trait the inner iterator has: `DoubleEndedIterator`, `ExactSizeIterator`,
  `FusedIterator`, `Clone`. A newtype that forwards only `next` reports `(0, None)`. `collect`
  then loses the capacity hint, and an `ExactSizeIterator` impl on it panics in `len()`.
- A wrapper that drops, adds, or merges items computes its own `size_hint`. A filter reports a
  lower bound of 0. Claim `ExactSizeIterator` only for an exact `size_hint`; a forwarded one
  makes `len()` wrong.
- Give `IntoIter` a named public type when the caller may store it. `std::slice::Iter<'a, u32>`
  in a `pub` signature ties your API to that std type forever. The `&mut` impl in the reference
  still names `std::slice::IterMut` to keep the block short. Wrap it the same way in a published
  crate.
- Do not write `type IntoIter = impl Iterator<Item = T>;`. It fails on stable with
  `error[E0658]: impl Trait in associated types is unstable` (issue 63063). Name the std type,
  write a wrapper, or use `Box<dyn Iterator<Item = T> + 'a>` at the cost of one
  allocation and a dynamic call per item. A closure that captures nothing coerces to a `fn`
  pointer, so `std::iter::Map<std::slice::Iter<'a, T>, fn(&'a T) -> U>` is a nameable type on
  stable.

## Never call self.into_iter() in the impl

This body is the trap:

```rust
pub struct Bag { items: Vec<u32> }

impl IntoIterator for Bag {
    type Item = u32;
    type IntoIter = std::vec::IntoIter<u32>;
    fn into_iter(self) -> Self::IntoIter { self.into_iter() }   // calls itself
}
```

It compiles and links. The only signal is a warning:

```text
warning: function cannot return without recursing
5 |     fn into_iter(self) -> Self::IntoIter { self.into_iter() }
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ---------------- recursive call site
  = note: `#[warn(unconditional_recursion)]` on by default
```

Running it aborts with exit 134:

```text
thread 'main' (<id>) has overflowed its stack
fatal runtime error: stack overflow, aborting
```

The body survives review because it usually works when it is written. An inherent
`fn into_iter(self)` on the same type shadows the trait method, because inherent methods win
over trait methods in resolution. Delete that inherent method, which is what
`clippy::should_implement_trait` tells you to do, and the same body starts to call itself.

The `unconditional_recursion = "deny"` level in [Verify](#verify) stops the build with
`error: function cannot return without recursing`. Without it, a CI job that does not deny
warnings ships the defect. In a codebase without that lint level, search for the shape:
`rg -nU 'fn into_iter\(self\) -> [^{]*\{\s*self\.into_iter' --type rust`. Keep `-U`: rustfmt splits the
body across lines.

## A collection newtype needs four impls

`Deref` does not supply them. Method-call syntax follows a deref; trait resolution does not.
The failures a `Deref<Target = Vec<T>>` newtype still has, all measured on one wrapper:

| Call site | Result with only `Deref` |
| --- | --- |
| `for v in w` | `error[E0277]: WrappedVec<i32> is not an iterator` |
| `let c: WrappedVec<i32> = (0..3).collect();` | `error[E0277]: a value of type WrappedVec<i32> cannot be built from an iterator over elements of type {integer}` |
| `total(w)`, where `total` takes `I: IntoIterator` | `error[E0277]: WrappedVec<i32> is not an iterator` |
| `w.into_iter()` | `error[E0507]: cannot move out of dereference of WrappedVec<i32>` |
| `w.extend([2, 3])` | `error[E0596]: cannot borrow data in dereference of WrappedVec<i32> as mutable` |

Adding `DerefMut` makes the last row compile, because `extend` is a method call. It fixes none
of the others. Write the impls:

Read [references/impl-examples.md](references/impl-examples.md#a-collection-newtype-with-four-impls)
when you write them: it has a run-tested newtype with the four impls and a `Deref<Target = [T]>`.

`Deref<Target = [T]>` costs the caller nothing and keeps the growth API private:
`b.push(4)` then fails with `error[E0599]: no method named push found for struct Bag<u32>`.
Do not add `DerefMut` to get mutation back. Add one named inherent method for each mutation
the type really offers. The `rust-discipline` skill treats a `Deref` impl on a non-pointer
newtype as a review item for this reason.

## Iterator cannot borrow from itself

`Item` is an associated type on the impl, so it cannot name the lifetime of `&mut self`. An
iterator that owns its buffer therefore cannot yield references into that buffer. rustc gives
`error[E0207]: the lifetime parameter 'a is not constrained`, then
`error: lifetime may not live long enough`. The `help` line misleads on this shape, and no
attribute, bound, or `PhantomData` field fixes it. Pick one of three options that work:

1. **Borrow the data, do not own it.** Put the lifetime on the iterator struct:
   `struct Frames<'a> { data: &'a [u8], pos: usize }` with `type Item = &'a [u8]`.
2. **Yield a guard that owns its borrow**, such as `Ref<'a, T>` from a borrowed
   `&'a [RefCell<T>]`.
3. **Drop the `Iterator` impl and expose an inherent method**, such as
   `fn next_frame(&mut self) -> Option<&[u8]>`. The caller loses every adapter and uses
   `while let`. Do not name it `next`: `clippy::should_implement_trait` flags it.

Read `references/lending-iterators.md` for a tested example of each option, the full E0207
output, and a generic-associated-type lending trait when generic code must accept several
lending sources.

A raw pointer or `RefCell::as_ptr` that escapes the lifetime is not a fourth option.
The yielded reference outlives the borrow the compiler tracks. Nothing then stops the caller
from holding it across a `push` that reallocates the buffer. Change the API. Miri reports the
defect only when a test interleaves the fabricated reference with a write. The
`rust-sanitizers-miri` skill, when installed, owns Miri; a clean
`cargo +nightly miri test --locked` run proves nothing here.

## size_hint is a contract

The default `size_hint` is `(0, None)`. Two consequences.

**`collect` falls back to the growth ladder.** Measured on 1.99.1: 500 items from a source
with no hint collect into a `Vec` of capacity 512; the same 500 items from a `Range` land on
capacity 500. The `rust-hot-path` skill has the allocation counts.

**`ExactSizeIterator` panics at run time.** `impl ExactSizeIterator for X {}` compiles clean
with no `size_hint` override. The default `len()` asserts that the hint is exact, so the first
call panics with exit 101:

```text
thread 'main' (<id>) panicked at .../core/src/iter/traits/exact_size.rs:<line>:<col>:
assertion `left == right` failed
  left: None
 right: Some(0)
```

Override `size_hint` before you implement `ExactSizeIterator`. Implement `DoubleEndedIterator` as
well when the sequence has a defined end, because `.rev()` and `.enumerate().rev()` both need
it:

Read [references/impl-examples.md](references/impl-examples.md#an-exact-size-double-ended-iterator)
when you write the impls: it has a run-tested iterator with both.

Rules for the two traits:

- Implement `ExactSizeIterator` only when the count is known before iteration and fits `usize`.
  A filtered or input-driven source does not qualify.
- `next_back` must yield the same elements as `next`, from the other end. `next` and
  `next_back` meet in the middle and must not hand out one element twice.
- The `size_hint` lower bound is a promise to `collect` and `extend`, not a guess. An
  over-large lower bound reserves memory that never fills.

## Adapter order: enumerate().rev() needs ExactSizeIterator

`Enumerate<I>` implements `DoubleEndedIterator` only when `I: DoubleEndedIterator +
ExactSizeIterator`. An adapter that loses the exact length breaks a later `.rev()`, and the
error blames `.rev()`, not the adapter: `error[E0277]: the trait bound Chars<'_>:
ExactSizeIterator is not satisfied`. A follow-on E0599 on the next method call goes away with
the E0277.

Swapping the two adapters compiles, and gives a different function. `v.iter().enumerate().rev()`
keeps the forward index. `v.iter().rev().enumerate()` renumbers from 0 at the tail. Both yield
the same elements in the same order, so a test on the elements alone passes with either. Assert
on the pair.

Read `references/adapters-and-generators.md` when you need to know which adapter keeps the exact
length, or want the full error and the three orderings side by side.

## Stateful generators: use iter::from_fn

Coroutines and `gen` blocks are still nightly on 1.99.1: a `gen` block gives
`error[E0658]: gen blocks are experimental`, and `#![feature(coroutines)]` gives
`error[E0554]: #![feature] may not be used on the stable release channel`. Pinning
`rust-toolchain.toml` to nightly for one iterator pins the whole workspace to nightly.
`use std::ops::Generator;` gives `error[E0432]` on every channel, because the trait no longer
exists.

`std::iter::from_fn` is the stable shape. A `move` closure owns the state, and the function
returns `impl Iterator`. No allocation, no `Pin`, no `Box<dyn>`:

```rust,run
fn evens(limit: u32) -> impl Iterator<Item = u32> {
    let mut next = 0;
    std::iter::from_fn(move || {
        if next >= limit { return None; }
        next += 2;
        Some(next - 2)
    })
}

fn main() {
    assert_eq!(evens(10).collect::<Vec<_>>(), vec![0, 2, 4, 6, 8]);
    assert_eq!(evens(10).size_hint(), (0, None));
}
```

`FromFn` is never `DoubleEndedIterator` and never `ExactSizeIterator`. Write a named struct with
a manual impl as soon as a caller needs `len()`, `.rev()`, or an independent `Clone`. Read
`references/adapters-and-generators.md` when you port an old `Generator` snippet, or need
`successors`, `repeat_with`, or the `FromFn` cost table.

## Related skills

Use these skills by name when they are installed. `rust-code-style` covers the consuming side:
which combinator to call, and when a `for` loop reads better. `rust-compiler-errors` covers
E0277, E0507, and E0596 beyond the shapes here.
