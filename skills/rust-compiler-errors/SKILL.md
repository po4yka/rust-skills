---
name: rust-compiler-errors
description: Use when rustc or cargo reports a numbered error and you need the cause rather than the first fix that compiles. Covers ownership and move errors (E0382, E0505, E0507, E0509), borrow conflicts (E0499, E0502, E0596), lifetime errors (E0597, E0716, E0515, E0521, E0106), trait and type errors (E0038, E0277, E0271, E0282, E0283, E0284, E0308, E0599, E0631, E0275), Drop impl errors (E0184, E0367, E0740), the unnumbered Send error on a future, resolution errors (E0433, E0425, E0603), and layout errors (E0072, E0793). States which reflexive fix hides the bug and which one resolves it. Triggers on any "E0" code that no topic skill owns (E0207 is rust-iterator-impl, E0793 is rust-unsafe, Send and Sync go to rust-send-sync), "borrow checker", "value moved", "does not live long enough", "cannot borrow", "missing lifetime specifier", "trait bound not satisfied", "not dyn compatible", "dyn compatibility", "object safety", "overflow evaluating the requirement", or a paste of a cargo build failure.
license: BSD-3-Clause
---

# Rust compiler errors

## Purpose

Map a compiler error to its cause, then to the fix that resolves it instead of the fix that
moves it. Most numbered errors have an obvious escape (`.clone()`, `'static`, `Rc<RefCell<T>>`)
that compiles and leaves the real problem in place. This skill names both.

## First moves

```bash
# The full explanation, with a worked example. Works offline.
rustc --explain E0499

# One line per diagnostic. Use it when the build produces a wall of output.
cargo build --message-format=short

# Use Cargo's default failure behavior. Add `--keep-going` only when you want
# Cargo to continue with independent crates after one crate fails.
cargo build

# Machine-readable, for counting error codes across a large failure.
cargo build --message-format=json 2>/dev/null | grep -o '"code":{"code":"E[0-9]*"' | sort | uniq -c | sort -rn
```

Fix the first error, then rebuild. A single move error produces a cascade of type errors
downstream, and most of them disappear on their own.

## Triage table

| Code | Message | What it means | First move |
| --- | --- | --- | --- |
| E0382 | borrow of moved value | The value was consumed, then used again | Decide the owner; borrow instead of moving |
| E0505 | cannot move out of `x` because it is borrowed | A live borrow outlives the move | Shorten the borrow, or move before borrowing |
| E0507 | cannot move out of `x` which is behind a shared reference | You need ownership but only hold `&` | `mem::take`, `Option::take`, `clone`, or take `self` |
| E0509 | cannot move out of type `T`, which implements the `Drop` trait | A `Drop` impl blocks every partial move out of the value | Make the field an `Option` and call `.take()`, or `mem::replace` |
| E0499 | cannot borrow `*x` as mutable more than once | Two live `&mut` to the same place | `split_at_mut`, index disjointly, or scope one borrow |
| E0502 | cannot borrow as mutable because it is also borrowed as immutable | A read borrow is live across a write | Copy the value out, then mutate |
| E0596 | cannot borrow as mutable, as it is behind a `&` reference | The parameter is `&T`, not `&mut T` | Change the signature; do not reach for interior mutability first |
| E0597 | `x` does not live long enough | A named local is dropped while borrowed | Move the binding to the outer scope |
| E0716 | temporary value dropped while borrowed | A temporary ended before its borrow | Name the owner, then verify the syntax-sensitive temporary scope |
| E0515 | cannot return reference to local variable | The callee owns the data the caller wants | Return owned, or accept a buffer parameter |
| E0521 | borrowed data escapes outside of function | A borrow crossed a `'static` boundary such as `thread::spawn` | Clone, or pass an `Arc` |
| E0106 | missing lifetime specifier | A struct or return type holds a reference with no stated source | Name the lifetime, or store owned data |
| E0277 | the trait bound `T: X` is not satisfied | A required trait is missing or not in scope | Read which trait; import it or add the bound |
| E0271 | expected `A` to be an iterator that yields `B` | An associated type does not match | Fix the item type, usually with `map` |
| E0308 | mismatched types | The two sides differ, often by one reference layer | Compare the two types the note prints, not the expressions |
| E0599 | no method named `m` found | Typo, or the trait that defines `m` is not imported | `use` the trait |
| E0631 | type mismatch in function arguments | A function item was passed to a higher-order call; no deref coercion applies at a trait bound | Wrap the call in a closure, or insert `.map(String::as_str)` |
| E0275 | overflow evaluating the requirement `T: X` | A generic impl builds an unbounded type chain at instantiation | Fix the signature; never raise `recursion_limit` |
| E0038 | the trait `T` is not dyn compatible | One item of the trait gets no vtable slot | Read the `...because` note; add `where Self: Sized` to that item |
| E0562 | `impl Trait` is not allowed in the return type of `Fn` trait bounds | `impl FnMut(&T) -> impl Ord` puts `impl Trait` in an associated-type binding | Name a generic parameter instead: `<K: Ord>` |
| E0184 | the trait `Copy` cannot be implemented for this type; the type has a destructor | One type asks for both `Copy` and `Drop` | Remove the `Copy` derive; a resource handle is not `Copy` |
| E0367 | `Drop` impl requires `T: Clone` but the struct it is implemented for does not | The `Drop` impl added a bound the type definition does not carry | Move the bound onto the struct definition |
| E0740 | field must implement `Copy` or be wrapped in `ManuallyDrop<...>` | A union field has drop glue | Wrap the field in `std::mem::ManuallyDrop` and drop it by hand |
| E0433 | cannot find module or crate | The dependency is missing or the path is wrong | `cargo add`, or fix the path |
| E0425 | cannot find value in this scope | Typo, or the item is not imported | Check the `use` list |
| E0603 | module is private | The path exists but is not exported | `pub use` it, or use the public path |
| E0072 | recursive type has infinite size | A type contains itself by value | `Box`, `Rc`, or `Arc` the recursive field |
| E0793 | reference to field of packed struct is unaligned | A reference into `#[repr(packed)]` | See the `rust-unsafe` skill |

## The clone reflex

`E0382` has one fix that always compiles:

```rust
let s = String::from("x");
let t = s.clone();   // compiles
```

Treat that as a diagnostic, not a fix. The error stated that two places want the same value. A
clone answers "both get one", which is right when the value is a small owned copy and wrong when
the value is an identity, a handle, a large buffer, or shared state.

Decide which case you are in before you type `.clone()`:

| The value is | The answer |
| --- | --- |
| Small and `Copy`-like, and the copy is the point | Clone, or derive `Copy` |
| Read by several places, never written | `&T`, or `Arc<T>` when it must cross a thread |
| Written by several places | `Arc<Mutex<T>>`, and check the lock order |
| An identity: a connection, a file, a job | One owner. Pass `&mut` down, or pass a handle |
| Large and consumed once | Move it, and restructure the caller so it can be moved |

A clone inside a loop is the version of this mistake that reaches production. It compiles, it is
correct, and it allocates once per iteration. See the `rust-performance` skill.

## Borrow conflicts are usually a split problem

`E0499` and `E0502` almost never require interior mutability. They require the compiler to see
that two borrows touch different data.

```rust
// E0499: two &mut into the same slice.
let a = &mut v[0];
let b = &mut v[1];

// Fix: split, so the two halves are provably disjoint.
let (left, right) = v.split_at_mut(1);
left[0] += right[0];
```

```rust
// E0502: a read borrow is still live when the write starts.
let first = &v[0];
v.push(1);
println!("{first}");

// Fix: end the read by copying the value out.
let first = v[0];
v.push(first);
```

Reach for `RefCell` only after both of these fail. `RefCell` moves the check from compile time
to run time; it converts a build error into a `RefCell already borrowed` panic in
production. Reach for it when the graph shape genuinely requires it, not to silence a message.

The full catalogue of splits is in
[references/borrow-checker-fixes.md](references/borrow-checker-fixes.md).

## E0597 and E0716 are the same shape with different data

Both say a borrow outlived its target. They differ in what the target was.

```rust,compile_fail
// E0597: `s` is a named local. It is dropped at the end of the inner block.
let r;
{
    let s = String::from("x");
    r = &s;
}
println!("{r}");
```

Fix by moving the binding out, so the owner lives at least as long as the borrow.

```rust,compile_fail,E0716
fn foo() -> Vec<u8> { vec![1, 2, 3] }
fn bar(v: &Vec<u8>) -> &u8 { &v[0] }

// E0716: `foo()` produced a temporary with no name. It dies at the `;`.
let p = bar(&foo());
let q = *p;
```

Fix by giving the temporary a name, which extends it to the end of the enclosing block:

```rust
fn foo() -> Vec<u8> { vec![1, 2, 3] }
fn bar(v: &Vec<u8>) -> &u8 { &v[0] }

let tmp = foo();
let p = bar(&tmp);
let q = *p;
```

Do not turn this example into the false rule that every temporary dies at the semicolon. Rust
extends some temporaries from an extending `let` pattern or expression to the end of the block:

```rust,run
fn make() -> String { String::from("extended") }

fn main() {
    let borrowed = &make();
    assert_eq!(borrowed, "extended");
}
```

A function argument such as `bar(&foo())` does not get that extension. Match the exact syntax,
then name the temporary when the consumer needs a longer lifetime. Use `rust-borrow-semantics`
for temporary-scope, place-expression, and two-phase-borrow analysis.

## E0282, E0283, and E0284 need a type anchor

These errors mean the available constraints do not select one type. Rust does not infer every
method or operator input backward from the final result type. Add the smallest local anchor:

```rust
let parsed: u64 = "42".parse()?;
let bytes = Vec::<u8>::new();
let converted = u64::from(7_u8);
```

Prefer a typed local, a turbofish on the constructor or method that owns the unknown type, or a
fully qualified call. Do not change a public return type, add `'static`, or add a broad trait
bound only to silence inference. Rebuild after the one anchor; later diagnostics can be a
cascade from the first unknown type.

## E0507: you hold a reference and you need the value

```rust,compile_fail
struct S { name: String }
fn f(s: &S) -> String { s.name }   // E0507
```

Pick by what should happen to the original:

| Intent | Call |
| --- | --- |
| The original keeps its value | `s.name.clone()` |
| The original is left empty and is still valid | `std::mem::take(&mut s.name)` |
| The original is left holding something else | `std::mem::replace(&mut s.name, other)` |
| The field is optional and becomes `None` | `s.name.take()` on an `Option` |
| The caller is finished with the whole value | Change the signature to take `self` |

`mem::take` needs `&mut` and needs `Default`. It is the cheapest of these: no allocation, no
clone.

## A `Drop` impl changes the borrow checker

`impl Drop` is not a local change. It breaks code that compiled before, and no error title names
`Drop`.

| You add `Drop` to | The new error | Cause |
| --- | --- | --- |
| a type with a lifetime parameter | E0597 on the borrowed local | dropck extends the borrow to the drop point |
| a guard that holds `&mut T` | E0502 at the next read of `T` | the drop point is one more use, after the last visible use |
| any type | E0509 at each partial move out of it | drop glue needs the whole value |
| a type that derives `Copy` | E0184 at the derive | `Copy` and `Drop` are exclusive |

```rust,compile_fail
struct Guard<'a>(&'a mut u32);
impl Drop for Guard<'_> {
    fn drop(&mut self) {}
}

fn read_while_guarded() {
    let mut x = 0u32;
    let _g = Guard(&mut x);
    println!("{x}");   // E0502
}
```

The note states the cause: "mutable borrow might be used here, when `_g` is dropped and runs the
`Drop` code for type `Guard`". NLL ends a borrow at its last use, and a `Drop` impl adds one last
use at the end of the scope. Call `drop(_g)` before the read, scope the guard in an inner block,
or leave the type `Drop`-free.

Inside `drop` you hold `&mut self`, so a by-value pattern on a field is E0507. Match on `self`
instead: match ergonomics then bind the payload as `&mut`. That fix, the dropck E0597 case, and
the E0509 partial-move case are in
[references/borrow-checker-fixes.md](references/borrow-checker-fixes.md).

## Send and Sync

`thread::spawn` reports a numbered error:

```text
error[E0277]: `Rc<i32>` cannot be sent between threads safely
```

An async block reports the same class of problem with **no error code**, so searching for E0277
finds nothing:

```text
error: future cannot be sent between threads safely
  = help: within `{async block}`, the trait `Send` is not implemented for `Rc<i32>`
note: future is not `Send` as this value is used across an await
```

Read the `note:`. It names the exact value and the exact `.await` that traps it. The usual causes
are an `Rc` where an `Arc` belongs, and a `MutexGuard` or `RefCell` borrow held across an
`.await`.

The fix is almost never to add an `unsafe impl Send`. Drop the guard before the await:

```rust
let value = {
    let guard = state.lock().unwrap();
    guard.value.clone()
};              // guard is dropped here
do_async(value).await;
```

`clippy::await_holding_lock` catches the lock case at build time. See the `rust-send-sync` skill
to decide whether a type is `Send` or `Sync` at all, the `rust-async-internals` skill for cancel
safety, and the `rust-lints` skill for the lint configuration.

## E0106: missing lifetime specifier

```rust,compile_fail
struct S { name: &str }   // E0106
```

Two answers, and the right one is usually the second:

```rust
struct Borrowed<'a> { name: &'a str }   // the struct cannot outlive the source
struct Owned { name: String }           // the struct owns its data
```

Store owned data unless the type is a short-lived view built inside one function and consumed
inside it. A lifetime parameter on a struct spreads: every type that holds it needs one too, and
the annotation reaches the whole call graph. Pay that cost for a parser view or a zero-copy
frame, not for a config or a message.

Never answer E0106 with `'static` on a struct field. It does not extend the data; it demands the
data already live forever, and it moves the error to the caller.

## E0072: recursive type has infinite size

```rust,compile_fail
struct Node { next: Option<Node> }   // E0072: the size is unbounded
```

```rust
struct Node { next: Option<Box<Node>> }   // one pointer, so the size is known
```

`Box` for a single owner, `Rc` for shared and single-threaded, `Arc` for shared across threads.
If the structure has cycles, `Rc` alone leaks: the cycle keeps the count above zero. Use `Weak`
for the back edge.

## E0038: the trait is not dyn compatible

`dyn Trait` needs a vtable. One item that cannot get a vtable slot removes the whole trait from
`dyn` use, so the error points at the `dyn Trait` type and not at the call that broke:

```text
error[E0038]: the trait `NoSelf` is not dyn compatible
note: for a trait to be dyn compatible it needs to allow building a vtable
   |     fn describe() -> String;
   |        ^^^^^^^^ ...because associated function `describe` has no `self` parameter
```

Read the `...because` note first. rustc prints one note per shape; these ten are the common
ones.

| Shape in the trait | The `...because` note |
| --- | --- |
| `fn describe() -> String;` | ...because associated function `describe` has no `self` parameter |
| `fn go<T: Copy>(&self, t: T);` | ...because method `go` has generic type parameters |
| `fn ser(&self, out: impl Write);` | ...because method `ser` has generic type parameters |
| `fn dup(&self) -> Self;` | ...because method `dup` references the `Self` type in its return type |
| `fn eq_me(&self, other: &Self) -> bool;` | ...because method `eq_me` references the `Self` type in this parameter |
| `fn it(&self) -> impl Iterator<Item = u8>;` | ...because method `it` references an `impl Trait` type in its return type |
| `async fn m(&self) -> u32;` | ...because method `m` is `async` |
| `const N: usize;` | ...because it contains associated const `N` |
| `type Item<T>;` | ...because it contains generic associated type `Item` |
| `trait T: Clone` or `trait T: Sized` | ...because it requires `Self: Sized` |
| `trait T: PartialEq<Self>` | ...because it uses `Self` as a type parameter |

Row two and row three print the same note for signatures that look nothing alike. An
argument-position `impl Trait` is a hidden generic parameter: `fn ser(&self, out: impl Write)` is
`fn ser<W: Write>(&self, out: W)`. Take `&mut dyn Write` when a consumer may need `Box<dyn Trait>`.

The last four rows name no method, so they read like a different error. `Clone` has `Sized` as
a supertrait, so `: Clone` on the trait alone removes the vtable.

The first seven sit on one item, and one clause on that item is the whole fix:

```rust
pub trait Codec {
    fn decode(&self, src: &[u8]) -> Vec<u8>;   // keeps its vtable slot
    fn name() -> &'static str
    where
        Self: Sized;                           // leaves the vtable
}
```

`Vec<Box<dyn Codec>>` now compiles. Each implementor still calls `name()` through its concrete
type.

Know the cost before you type the clause: the item leaves the trait-object API. A later call
through `dyn` fails at the call site, not at the trait definition, and the message never mentions
dyn compatibility:

```text
error[E0277]: the size for values of type `dyn Codec` cannot be known at compilation time
note: required by a bound in `Codec::name`
```

Add `where Self: Sized` only to an item no caller needs through `dyn`. If callers need it, move
the item to a second trait, or take `&self` and return an owned type instead of `Self`.

`where Self: Sized` does not answer the last four rows. A supertrait bound is not an item, and
an associated const rejects the clause: rustc reports `error[E0658]: generic const items are
experimental`. Move an associated const or a generic associated type to a second trait. Drop a
`Clone` supertrait and put the clone in the vtable:

```rust
trait Shape {
    fn area(&self) -> f64;
    fn clone_box(&self) -> Box<dyn Shape>;
}

impl Clone for Box<dyn Shape> {
    fn clone(&self) -> Self {
        self.clone_box()
    }
}
```

rustc renamed this check from "object safety" to "dyn compatibility". A grep of a current build
log for "object safe" finds nothing. Grep for `E0038` or for "dyn compatible".

## `cargo check` and `cargo build` disagree on recursive generic instantiation

```text
error: reached the recursion limit while instantiating `<Node as Serialize>::serialize::<&mut &mut &mut &mut &mut &mut ...>`
  = note: the full name for the type has been written to '<crate>.long-type-<hash>.txt'
```

**`cargo check` exits 0 on a crate that `cargo build` rejects.** `cargo check` stops after
type-checking and metadata emission. The instantiation chain is walked only by the
monomorphization collector, which runs during codegen. The collector starts at reachable roots, so
an uncalled generic function stays silent until a caller appears. Gate CI on `cargo build`, not on
`cargo check`, for any crate with recursive generic trait impls.

**A higher `recursion_limit` only makes the failure slower.** The `&mut &mut ... &mut T` chain is
infinite by construction, so no finite `recursion_limit` ends it. Measured on the `Node` shape
below with rustc 1.97.0 on aarch64-apple-darwin: the default limit of 128 fails in 0.10 s, and
`#![recursion_limit = "1024"]` fails in 11.1 s with the identical message. This error prints no
`help:` line.

The cause is a trait method that takes its writer by value and hands `&mut out` to the recursive
call, so the type grows one `&mut` per level:

```rust,ignore
// W, then &mut W, then &mut &mut W, without end.
trait Serialize { fn serialize(&self, out: impl Write) -> io::Result<()>; }
// impl Serialize for Node { ... for c in &self.children { c.serialize(&mut out)?; } ... }
```

Take `&mut dyn Write` in the trait method. It is one concrete type at every depth, and it keeps
the trait dyn compatible. In a free function `&mut impl Write` also stops the chain, but its
implicit `Sized` bound rejects a caller that already holds `&mut dyn Write`, with E0277 "the size
for values of type `dyn Write` cannot be known at compilation time". Write `&mut (impl Write +
?Sized)` when both callers must work. See the `rust-type-erasure` skill for the wider trade.

`error[E0275]: overflow evaluating the requirement ...` is a different error. The trait solver
emits it during type checking, so `cargo check` does report it. It carries a `help:` line that
asks for double the current `recursion_limit` every time. Do not take it either; the chain is
still unbounded.

## Escalation rule

Three failed attempts at the same error is a signal, not bad luck. Stop editing and answer these:

1. Which single component should own this data for its whole lifetime?
2. Is the borrow crossing a boundary it should not cross: a thread, an `.await`, a callback, an
   FFI call?
3. Would the error disappear if the data were owned rather than borrowed, and what does that
   cost?

Errors that mean the design is wrong, not the syntax: E0382 fixed by cloning in a hot loop,
E0499 fixed by `RefCell`, E0597 fixed by `'static`, E0521 fixed by leaking. Each compiles. Each
converts a build error into a run-time cost or a run-time panic.

See the `rust-crate-architecture` skill for ownership across module boundaries, and the
`rust-discipline` skill for the API shapes that avoid these errors.

## Related skills

- `rust-unsafe` — E0793 and the layout rules behind it
- `rust-send-sync` — the auto trait decision behind every `cannot be sent` message
- `rust-async-internals` — `Send` across `.await`, cancel safety, and shutdown
- `rust-lints` — where `clippy::await_holding_lock` and the rest are configured
- `rust-crate-architecture` — ownership and dependency direction across crates
- `rust-discipline` — the API shapes that avoid E0038 and the borrow errors
- `rust-callback-bounds` — E0309, E0621, and E0502 on a `Fn(&T) -> K` parameter
- `rust-type-erasure` — `&mut dyn Trait` against `impl Trait`, and what each costs
- `rust-performance` — the cost of the clone that silenced the error
- `cargo-workflows` — build and check commands in full

For the split-borrow catalogue, see
[references/borrow-checker-fixes.md](references/borrow-checker-fixes.md).
