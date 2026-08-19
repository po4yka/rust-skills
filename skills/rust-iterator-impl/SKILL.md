---
name: rust-iterator-impl
description: Use when you write the producing side of iteration for your own type, including a hand-written Iterator impl, the three IntoIterator impls for a container, FromIterator, Extend, size_hint, and an adapter chain that fails on a trait bound. Covers the unconditional_recursion stack overflow from self.into_iter(), why a Deref newtype still gets no for loop and no collect, E0207 on a lending iterator that borrows from itself, the ExactSizeIterator len panic, why enumerate().rev() needs ExactSizeIterator while rev().enumerate() renumbers the indices, and std::iter::from_fn in place of nightly gen blocks. Triggers on "implement Iterator", "custom iterator", "IntoIterator", "into_iter", "FromIterator", "Extend", "size_hint", "ExactSizeIterator", "DoubleEndedIterator", "next_back", "lending iterator", "iter::from_fn", "gen block", "enumerate().rev()", "E0207", or "unconditional_recursion".
license: BSD-3-Clause
---

# Rust iterator impl

## Purpose

Write the producing side of the iterator protocol: a hand-written `Iterator`, the
`IntoIterator` impls a container owes its callers, `FromIterator`, `Extend`, `size_hint`, and
the adapter bounds that decide whether a chain compiles. Each rule here fixes a defect that
the compiler accepts with a warning, or reports against the wrong line, or moves to run time.

This skill stops at the trait impls. Combinator style on the calling side belongs to
`rust-code-style`. Iteration cost, once the impls are correct, belongs to `rust-hot-path`.

Every error text, warning, and number below comes from rustc 1.97.0, edition 2024, on
aarch64-apple-darwin.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0277]: &Bag is not an iterator` on `for v in &bag` | [The three IntoIterator impls](#the-three-intoiterator-impls) |
| `warning: function cannot return without recursing`, then `stack overflow` | [Never call self.into_iter() in the impl](#never-call-selfinto_iter-in-the-impl) |
| `error[E0277]: a value of type X cannot be built from an iterator` | [A collection newtype needs four impls](#a-collection-newtype-needs-four-impls) |
| `error[E0207]: the lifetime parameter 'a is not constrained` | [Iterator cannot borrow from itself](#iterator-cannot-borrow-from-itself) |
| A panic inside `core/src/iter/traits/exact_size.rs` | [size_hint is a contract](#size_hint-is-a-contract) |
| `error[E0277]: ... ExactSizeIterator is not satisfied`, pointing at `.rev()` | [Adapter order](#adapter-order-enumeraterev-needs-exactsizeiterator) |
| `error[E0658]: gen blocks are experimental` | [Stateful generators](#stateful-generators-use-iterfrom_fn) |
| `error[E0432]: unresolved import std::ops::Generator` | [Stateful generators](#stateful-generators-use-iterfrom_fn) |
| The impls are correct, and iteration is slow | `rust-hot-path` |

## The three IntoIterator impls

An inherent `fn iter(&self)` serves `bag.iter()` and nothing else. The `for` loop and every
`I: IntoIterator` bound resolve through the trait, so a container that offers only `iter`
fails at the call site:

```text
error[E0277]: `&Bag` is not an iterator
7 |     for v in &b { println!("{v}"); }
  |              ^^ `&Bag` is not an iterator
  = help: the trait `Iterator` is not implemented for `&Bag`
  = note: required for `&Bag` to implement `IntoIterator`
```

The error names the call site, so the usual repair is `for v in b.iter()`. That hides the
defect instead of fixing it. Write all three impls once, on the container:

```rust
pub struct Bag { items: Vec<u32> }

pub struct Iter<'a>(std::slice::Iter<'a, u32>);

impl<'a> Iterator for Iter<'a> {
    type Item = &'a u32;
    fn next(&mut self) -> Option<&'a u32> { self.0.next() }
}

impl Bag {
    // Keep these two. `bag.iter()` is the readable form, and clippy does not flag the names.
    pub fn iter(&self) -> Iter<'_> { Iter(self.items.iter()) }
    pub fn iter_mut(&mut self) -> std::slice::IterMut<'_, u32> { self.items.iter_mut() }
}

impl<'a> IntoIterator for &'a Bag {
    type Item = &'a u32;
    type IntoIter = Iter<'a>;
    fn into_iter(self) -> Iter<'a> { self.iter() }
}

impl<'a> IntoIterator for &'a mut Bag {
    type Item = &'a mut u32;
    type IntoIter = std::slice::IterMut<'a, u32>;
    fn into_iter(self) -> Self::IntoIter { self.iter_mut() }
}

impl IntoIterator for Bag {
    type Item = u32;
    type IntoIter = std::vec::IntoIter<u32>;
    // Name the concrete constructor. Never `self.into_iter()`.
    fn into_iter(self) -> Self::IntoIter { self.items.into_iter() }
}

fn total<I: IntoIterator<Item = u32>>(src: I) -> u32 { src.into_iter().sum() }

let mut bag = Bag { items: vec![1, 2, 3] };
for v in &bag { assert!(*v > 0); }
for v in &mut bag { *v += 1; }
assert_eq!(total(bag), 9);
```

Rules:

- Do not add an inherent `fn into_iter`. Clippy asks you to delete it:
  `warning: method into_iter can be confused for the standard trait method
  std::iter::IntoIterator::into_iter`, lint `clippy::should_implement_trait`, warn by default.
- Keep the inherent `iter` and `iter_mut`. Clippy does not flag those two names, and the
  borrowing trait impls delegate to them.
- Give `IntoIter` a named public type when the caller may store it. `std::slice::Iter<'a, u32>`
  in a `pub` signature ties your API to that std type forever. The `&mut` impl above still names
  `std::slice::IterMut` to keep the block short. Wrap it the same way in a published crate.

## Never call self.into_iter() in the impl

This body is the trap:

```rust,ignore
impl IntoIterator for Bag {
    type Item = u32;
    type IntoIter = std::vec::IntoIter<u32>;
    fn into_iter(self) -> Self::IntoIter { self.into_iter() }   // calls itself
}
```

It compiles and links. The only signal is a warning:

```text
warning: function cannot return without recursing
6 |     fn into_iter(self) -> Self::IntoIter { self.into_iter() }
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ---------------- recursive call site
  = note: `#[warn(unconditional_recursion)]` on by default
```

Running it aborts: `fatal runtime error: stack overflow, aborting`, exit 134.

The body survives review because it usually works when it is written. An inherent
`fn into_iter(self)` on the same type shadows the trait method, because inherent methods win
over trait methods in resolution. Delete that inherent method, which is what
`clippy::should_implement_trait` tells you to do, and the same body starts to call itself.

Two defences, both cheap:

- Put `unconditional_recursion = "deny"` in the `[lints.rust]` table of the workspace
  manifest. The build then stops with `error: function cannot return without recursing`. A CI
  job without `-D warnings` ships the defect otherwise. See `rust-lints`.
- Grep before merge: `rg -n 'fn into_iter\(self\) -> [^{]*\{\s*self\.into_iter' --type rust`.

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

```rust
pub struct Bag<T>(Vec<T>);

impl<T> IntoIterator for Bag<T> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;
    fn into_iter(self) -> Self::IntoIter { self.0.into_iter() }
}

impl<'a, T> IntoIterator for &'a Bag<T> {
    type Item = &'a T;
    type IntoIter = std::slice::Iter<'a, T>;
    fn into_iter(self) -> Self::IntoIter { self.0.iter() }
}

impl<T> FromIterator<T> for Bag<T> {
    fn from_iter<I: IntoIterator<Item = T>>(src: I) -> Self { Bag(src.into_iter().collect()) }
}

impl<T> Extend<T> for Bag<T> {
    fn extend<I: IntoIterator<Item = T>>(&mut self, src: I) { self.0.extend(src) }
}

// Deref to the slice, not to the Vec. The read API is exposed; `push` and `truncate` are not.
impl<T> std::ops::Deref for Bag<T> {
    type Target = [T];
    fn deref(&self) -> &[T] { &self.0 }
}

let mut b: Bag<u32> = (0..3).collect();
b.extend([3, 4]);
assert_eq!(b.len(), 5);                       // through the [T] deref
assert_eq!(b.iter().copied().max(), Some(4)); // through the [T] deref
assert_eq!(b.into_iter().count(), 5);         // through the trait impl
```

`Deref<Target = [T]>` costs the caller nothing and keeps the growth API private:
`b.push(4)` then fails with `error[E0599]: no method named push found for struct Bag<u32>`.
Do not add `DerefMut` to get mutation back. Add one named inherent method for each mutation
the type really offers. `rust-discipline` treats a `Deref` impl on a non-pointer newtype as a
review item for this reason.

## Iterator cannot borrow from itself

`Item` is an associated type on the impl, so it cannot name the lifetime of `&mut self`. An
iterator that owns its buffer therefore cannot yield references into that buffer:

```text
error[E0207]: the lifetime parameter `'a` is not constrained by the impl trait, self type, or predicates
3 | impl<'a> Iterator for Chunks {
  |      ^^ unconstrained lifetime parameter
error: lifetime may not live long enough
8 |         Some(s)
  |         ^^^^^^^ method was supposed to return data with lifetime `'a`
  |                 but it is returning data with lifetime `'1`
```

There is no attribute and no bound that fixes this shape. Pick one of three that work.

**1. Borrow the data, do not own it.** The lifetime goes on the iterator struct, so the impl
constrains it:

```rust
pub struct Frames<'a> { data: &'a [u8], pos: usize }

impl<'a> Iterator for Frames<'a> {
    type Item = &'a [u8];
    fn next(&mut self) -> Option<&'a [u8]> {
        let end = (self.pos + 4).min(self.data.len());
        let frame = self.data.get(self.pos..end)?;
        self.pos = end;
        if frame.is_empty() { None } else { Some(frame) }
    }
}

let buf = [0u8; 10];
assert_eq!(Frames { data: &buf, pos: 0 }.count(), 3);
```

**2. Yield a guard that owns its borrow.** The item is `Ref<'a, T>`, and `'a` comes from the
container the iterator borrows:

```rust
use std::cell::{Ref, RefCell};

pub struct NodeIter<'a> { cells: &'a [RefCell<u32>], pos: usize }

impl<'a> Iterator for NodeIter<'a> {
    type Item = Ref<'a, u32>;
    fn next(&mut self) -> Option<Ref<'a, u32>> {
        let cell = self.cells.get(self.pos)?;
        self.pos += 1;
        Some(cell.borrow())
    }
}
```

**3. Drop the `Iterator` impl and expose an inherent method.** The elided lifetime ties the
item to `&mut self`, which is exactly what `Iterator` cannot express. The caller loses every
adapter and uses `while let`:

```rust
pub struct Decoder { buf: Vec<u8>, pos: usize }

impl Decoder {
    /// Not an `Iterator`: the item borrows `self`, so no `Item` type can name it.
    pub fn next_frame(&mut self) -> Option<&[u8]> {
        let end = (self.pos + 4).min(self.buf.len());
        let frame = self.buf.get(self.pos..end).filter(|f| !f.is_empty())?;
        self.pos = end;
        Some(frame)
    }
}

let mut d = Decoder { buf: vec![1, 2, 3, 4, 5], pos: 0 };
let mut seen = 0;
while let Some(frame) = d.next_frame() { seen += frame.len(); }
assert_eq!(seen, 5);
```

Do not name that method `next`. `clippy::should_implement_trait` flags an inherent `next`
exactly as it flags an inherent `into_iter`: `warning: method next can be confused for the
standard trait method std::iter::Iterator::next`, warn by default. A workspace with
`-D warnings` then fails to build. `next_frame` is clippy-clean and reads the same at the call
site.

Reaching for `RefCell::as_ptr` or a raw pointer to escape the lifetime is not a fourth option.
The yielded reference outlives the borrow the compiler tracks. Nothing then stops the caller
from holding it across a `push` that reallocates the buffer. Do not ask Miri to confirm this.
Both shapes run clean under Stacked Borrows and under `-Zmiri-tree-borrows` while no code
mutates the data. Miri reports the defect only when the program interleaves the fabricated
reference with a write. An `unsafe { &*cell.as_ptr() }` followed by
`cell.borrow_mut().push_str(" MOO")` gives `error: Undefined Behavior: trying to retag from
<TAG> for SharedReadOnly permission at ALLOC[0x18], but that tag does not exist in the borrow
stack for this location` under Stacked Borrows, and `error: Undefined Behavior: reborrow through
<TAG> at ALLOC[0x18] is forbidden` under Tree Borrows. Change the API. A clean Miri run on this
shape is no evidence. See `rust-unsafe`.

## size_hint is a contract

The default `size_hint` is `(0, None)`. Two consequences.

**`collect` falls back to the growth ladder.** Measured on 1.97.0: 500 items from a source
with no hint collect into a `Vec` of capacity 512; the same 500 items from a `Range` land on
capacity 500. `rust-hot-path` has the allocation counts.

**`ExactSizeIterator` panics at run time.** `impl ExactSizeIterator for X {}` compiles clean
with no `size_hint` override. The default `len()` asserts that the hint is exact, so the first
call panics:

```text
thread 'main' panicked at core/src/iter/traits/exact_size.rs:122:9:
assertion `left == right` failed
  left: None
 right: Some(0)
exit=101
```

Override `size_hint` before you claim either marker trait. Implement `DoubleEndedIterator` as
well when the sequence has a defined end, because `.rev()` and `.enumerate().rev()` both need
it:

```rust
pub struct Ids { lo: u32, hi: u32 }

impl Iterator for Ids {
    type Item = u32;
    fn next(&mut self) -> Option<u32> {
        if self.lo >= self.hi { return None; }
        self.lo += 1;
        Some(self.lo - 1)
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = (self.hi - self.lo) as usize;
        (n, Some(n))
    }
}

impl ExactSizeIterator for Ids {}

impl DoubleEndedIterator for Ids {
    fn next_back(&mut self) -> Option<u32> {
        if self.lo >= self.hi { return None; }
        self.hi -= 1;
        Some(self.hi)
    }
}

assert_eq!(Ids { lo: 0, hi: 3 }.len(), 3);
assert_eq!(Ids { lo: 0, hi: 3 }.enumerate().rev().collect::<Vec<_>>(),
           vec![(2, 2), (1, 1), (0, 0)]);
```

Rules for the two markers:

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
ExactSizeIterator is not satisfied`, with the caret two positions after `.chars()`.

Swapping the two adapters compiles, and gives a different function. `v.iter().enumerate().rev()`
keeps the forward index. `v.iter().rev().enumerate()` renumbers from 0 at the tail. Both yield
the same elements in the same order, so a test on the elements alone passes with either. Assert
on the pair.

`references/adapters-and-generators.md` has the exact-length table and the worked orderings.

## Stateful generators: use iter::from_fn

Coroutines and `gen` blocks are nightly on 1.97.0: a `gen` block gives
`error[E0658]: gen blocks are experimental`, and `#![feature(coroutines)]` gives
`error[E0554]: #![feature] may not be used on the stable release channel`. Pinning
`rust-toolchain.toml` to nightly for one iterator pins the whole workspace to nightly.

Two further traps guard that road. First, `std::ops::Generator` does not exist. The trait was
renamed to `Coroutine`, so `use std::ops::Generator;` gives `error[E0432]: unresolved import
std::ops::Generator ... no Generator in ops` on stable and on nightly alike. Any snippet that
names `Generator` or `GeneratorState` from `std::ops` predates the rename. The current names are
`std::ops::Coroutine` and `std::ops::CoroutineState`, still behind `#![feature(coroutine_trait)]`,
issue 43122. Second, a nightly `gen` block is an `impl Iterator` and nothing more. It
implements no `Coroutine<R>` for any `R` other than `()`, so it accepts no resume argument:
`let _: &dyn Coroutine<&mut u32, Yield = i32, Return = ()> = &g;` fails with `error[E0277]: the
trait bound {gen block@...}: Coroutine<&mut u32> is not satisfied`, while the
`&dyn Iterator<Item = i32>` coercion on the same value compiles. Nightly buys no state-carrying
routine here, so `gen` is not a reason to leave stable.

`std::iter::from_fn` is the stable shape. A `move` closure owns the state, and the function
returns `impl Iterator`. No allocation, no `Pin`, no `Box<dyn>`:

```rust
fn evens(limit: u32) -> impl Iterator<Item = u32> {
    let mut next = 0;
    std::iter::from_fn(move || {
        if next >= limit { return None; }
        next += 2;
        Some(next - 2)
    })
}

assert_eq!(evens(10).collect::<Vec<_>>(), vec![0, 2, 4, 6, 8]);
assert_eq!(evens(10).size_hint(), (0, None));
```

`FromFn` is never `DoubleEndedIterator` and never `ExactSizeIterator`. Write a named struct with
a manual impl as soon as a caller needs `len()`, `.rev()`, or an independent `Clone`.
`references/adapters-and-generators.md` has `successors`, `repeat_with`, and the cost table.

## Review checklist

- Every container that a `for` loop iterates has `IntoIterator` for `T`, `&T`, and `&mut T`.
- No `IntoIterator::into_iter` body calls `self.into_iter()`.
- No inherent `fn into_iter` and no inherent `fn next` exist. `iter` and `iter_mut` stay.
- A collection newtype has `FromIterator` and `Extend`, not a `Deref` that pretends to.
- A `Deref` on a newtype targets `[T]` or `str`, never the owning collection.
- A hand-written `Iterator` overrides `size_hint` when the remaining count is known.
- No `ExactSizeIterator` impl without a matching exact `size_hint`.
- No `enumerate().rev()` after `filter`, `flat_map`, `take_while`, `chars`, or `chain`.
- Any change from `enumerate().rev()` to `rev().enumerate()` carries a test on the index, not
  only on the element.
- A generator uses `iter::from_fn`, `successors`, or `repeat_with`, not a nightly `gen` block.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-code-style` | The consuming side: which combinator to call, and when a `for` loop reads better |
| `rust-hot-path` | Iteration cost once the impls are right: `size_hint` allocation counts, `collect` capacity, `chunks_exact` |
| `rust-lints` | The workspace lint tables that hold `unconditional_recursion = "deny"` and `explicit_into_iter_loop` |
| `rust-compiler-errors` | Reading E0277, E0507, and E0596 in general, beyond the shapes here |
| `rust-discipline` | API-design review, including the `Deref`-on-a-newtype rule |
| `rust-unsafe` | Why a raw pointer does not buy a lending iterator, and the limits of a clean Miri run |
