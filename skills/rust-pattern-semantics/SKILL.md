---
name: rust-pattern-semantics
description: Use when a Rust pattern, match guard, or if let guard decides what moves, borrows, or drops, or when an edition 2024 pattern or let chain fails to compile. Triggers on "match guard", "if let guard", "partial move", "binding mode", "match ergonomics", "ref pattern", "scrutinee lifetime", "let chains", "implicitly-borrowing pattern", "guard runs twice", E0510, E0594, or E0596 in a guard.
license: BSD-3-Clause
---

# Rust Pattern Semantics

## Analysis order

For the pattern that the question or the error names, determine:

1. The crate edition and the MSRV (`rust-version` in `Cargo.toml`). They decide which syntax
   compiles. See [Version gates](#version-gates).
2. Whether the scrutinee is a place or a value expression.
3. The alternatives of each or-pattern.
4. The default binding mode at each nesting level.
5. Whether each binding is by value, `ref`, or `ref mut`, and which fields a partial move leaves
   initialized.
6. When the guard runs, and whether it can run more than once.
7. Where the scrutinee temporaries, the guard temporaries, and the bindings drop.

Do not propose a clone, a wildcard arm, or a `ref` keyword before this pass. Each one can
compile and change what the code moves, borrows, or matches.

## Version gates

| Feature | Needs | Error when the gate is not met |
| --- | --- | --- |
| Let chains in `if` and `while` (`if let A = a && cond`) | Edition 2024 and rustc 1.88+ | Edition 2021: `let chains are only allowed in Rust 2024 or later` (no error code). Edition 2024 on rustc 1.85-1.87: E0658 `` `let` expressions in this position are unstable `` (measured on rustc 1.87.0) |
| `if let` guards, and a `let` chain inside a guard (`if let P = e && cond`) | rustc 1.95+, every edition | E0658 `` `if let` guards are experimental `` (measured on rustc 1.94.0) |
| `std::assert_matches!` | rustc 1.96+ | E0658 `` use of unstable library feature `assert_matches` `` on rustc 1.95, and for the `use` form on older toolchains. E0433 or `cannot find macro` for the path form on rustc 1.94 and older (measured on rustc 1.87.0-1.95.0) |
| Match ergonomics reservations | Edition 2024 | Uncoded errors, see [Edition 2024 match ergonomics](#edition-2024-match-ergonomics) |

Do not add a `#![feature]` gate for an E0658 from this table. Raise `rust-version`, or use the
fallback: a nested `if let`, or `assert!(matches!(..))`. The `rust-compiler-errors` skill, when it
is installed, lists the other compile-error repair hazards.

A `let` chain inside a match guard compiles on edition 2021 (measured on rustc 1.98.1). A chain in
an `if` or `while` condition does not.

## Verify

| Claim | Check | What a pass does not prove |
| --- | --- | --- |
| Binding type or mode | `let () = binding;` and read the E0308 label; or a typed call as in [Binding modes](#binding-modes) | Drop timing or guard repetition |
| Guard count, drop point, lock hold | A `#[test]` or a doctest (it runs by default) that asserts on a counter or on `Mutex::try_lock`, built with the crate's edition | Behavior on another edition |
| Pattern shape in a test | `std::assert_matches!(value, Some(n) if n > 2);` on MSRV 1.96+; else `assert!(matches!(..))` | Fields that the pattern does not name |
| A pattern must not compile | A `compile_fail` doctest that holds only the probe code: `compile_fail,E0xxx` when rustc prints a code (E0004, E0509, E0510, E0594, E0596), a bare `compile_fail` for the uncoded edition 2024 errors. To prove the code on stable, run `cargo check --message-format=short` on the probe and find `error[E0xxx]`, or use a `trybuild` case, which compares the full stderr | The reason for the failure. Stable rustdoc accepts any compile error and ignores a named code; only nightly rustdoc checks it |
| Syntax builds on the MSRV | `cargo +<msrv> check --locked` for a let chain, an `if let` guard, or `assert_matches!` | Behavior, and code behind other features or targets |

`std::assert_matches!` is not in the prelude. Call it by path, or import it with
`use std::assert_matches;`. `use std::assert_matches::assert_matches;` fails with E0432.

## Triage

| Symptom | Likely cause | First action |
| --- | --- | --- |
| Value is partly usable after destructuring | The pattern made a partial move | List moved and initialized fields |
| Partial move fails only after adding `Drop` | The destructor needs the whole value | Add a consuming method or `Option::take` |
| Guard side effect occurs twice | Overlapping or-pattern alternatives both matched | Remove the side effect or split the arms |
| E0510, or E0594/E0596 with "immutable for the pattern guard" | The guard mutates or mutably borrows the scrutinee or a pattern binding | Move the mutation into the arm body. A signature change does not help |
| Lock or borrow stays held inside the arm | The lock is in the `match` scrutinee or an `if let` guard | Copy or clone the value out before the `match`, or bind the guard in a braced block that returns an owned value |
| Binding became `&T` after a refactor | Match ergonomics changed the default binding mode | Probe the binding type in the target edition |
| `... within an implicitly-borrowing pattern` | Edition 2024 reservation | Apply the fix from the edition 2024 table |
| `let chains are only allowed in Rust 2024 or later` | Let chain in an edition 2021 `if` or `while` | Nest the `if let` and repeat the `else` branch at each level, or migrate to edition 2024 with MSRV 1.88+ (the `cargo-workflows` skill) |
| E0658 on a let chain, an `if let` guard, or `assert_matches!` | The toolchain is older than the [version gate](#version-gates) | Raise `rust-version` or use the fallback. Do not add `#![feature]` |
| Wildcard fixes exhaustiveness but tests fail | The missing variant needed a semantic policy | Add an explicit arm and behavior test |

## Binding modes

A non-reference pattern binds by value. When a non-reference pattern matches a reference, match
ergonomics switches the default binding mode to `ref` or `ref mut`, and the inner bindings
borrow:

```rust
fn shared(_: &String) {}
fn mutable(_: &mut String) {}

let mut value = Some(String::from("x"));
if let Some(text) = &value { shared(text); }
if let Some(text) = &mut value { mutable(text); }
```

A function argument coerces `&mut T` to `&T`, so `shared(text)` proves only that `text` is some
reference. To see the exact type, write `let () = text;`. The E0308 label says
``this expression has type `&String` ``. Remove the line after you read it.

Edition 2024 restricts explicit `mut`, `ref`, `ref mut`, and `&` inside a pattern that borrows
implicitly. See [Edition 2024 match ergonomics](#edition-2024-match-ergonomics).

## Partial moves

A pattern can move one field and borrow another. The original value then cannot be used as a
whole, but fields that were not moved remain usable.

```rust,run
struct Record {
    name: String,
    count: u32,
}

fn main() {
    let record = Record { name: String::from("job"), count: 3 };
    let Record { name, ref count } = record;
    assert_eq!(name, "job");
    assert_eq!(*count, 3);
    assert_eq!(record.count, 3);
}
```

A type with a `Drop` implementation cannot be partially moved because `drop` must receive the
whole value:

```rust,compile_fail,E0509
struct Resource { name: String }
impl Drop for Resource { fn drop(&mut self) {} }

fn main() {
    let resource = Resource { name: String::from("owned") };
    let Resource { name } = resource;
    println!("{name}");
}
```

Use `Option::take`, `mem::replace`, or an explicit consuming method when a resource owner must
release one field before its destructor.

## Match guards

A guard runs after the pattern matches and before the arm body. The bindings are shared borrows
while the guard runs. A by-value binding moves or copies only after the guard succeeds.

### A guard on an or-pattern can run more than once

The guard applies to the complete or-pattern. It runs once for each alternative that matches
until one succeeds. Do not put metrics, mutation, I/O, or one-shot work in it.

```rust,run
fn main() {
    let mut calls = 0;
    match 1 {
        1 | 1 if {
            calls += 1;
            false
        } => unreachable!(),
        1 => {}
        _ => unreachable!(),
    }
    assert_eq!(calls, 2);
}
```

If a guard needs expensive or stateful work, match first and run ordinary control flow in the
arm.

### Guard mutation

The example above mutates `calls`, a local that the pattern does not bind. That is legal. rustc
rejects two other mutations:

- Assigning to or mutably borrowing the scrutinee gives E0510 (`cannot assign ... in match
  guard`, `cannot mutably borrow ... in match guard`).
- Assignment through a pattern binding gives E0594. A `&mut` method call through it, such as
  `v.push(2)`, gives E0596. Both carry the note "variables bound in patterns are immutable until
  the end of the pattern guard". This applies to `ref mut` bindings too.

```rust,compile_fail,E0510
fn main() {
    let mut slot = Some(1);
    match slot {
        Some(_) if { slot = None; false } => {}
        _ => {}
    }
}
```

```rust,compile_fail,E0594
fn main() {
    let mut slot = Some(1);
    match slot {
        Some(ref mut n) if { *n += 1; false } => {}
        _ => {}
    }
}
```

Move the mutation into the arm body, or compute a boolean before the match. When rustc rejects
a guard, keep the exact pattern in the probe. A rewrite into an `if` proves a different program.

### Temporaries: scrutinee, `if let` guard, boolean guard

The three positions drop temporaries at different points. A `lock()` in the wrong position holds
the lock through the arm body:

| Position | Temporaries drop |
| --- | --- |
| `match` scrutinee | At the end of the enclosing temporary scope (usually the statement), after every arm |
| `if let` guard scrutinee | When the arm body ends. If the guard fails, before the next arm |
| Boolean guard (`if cond`) | As soon as the condition is evaluated |

```rust,run
use std::sync::Mutex;

fn main() {
    let state = Mutex::new(Some(1));

    match *state.lock().unwrap() {
        Some(_) => assert!(state.try_lock().is_err()),
        None => unreachable!(),
    }

    match 0 {
        _ if let Some(_) = *state.lock().unwrap() => assert!(state.try_lock().is_err()),
        _ => unreachable!(),
    }

    match 0 {
        _ if state.lock().unwrap().is_some() => assert!(state.try_lock().is_ok()),
        _ => unreachable!(),
    }
}
```

To release the lock before the arm body, copy or clone the value out before the `match`
(`let v = state.lock().expect("state mutex poisoned").clone();`), or bind the guard inside a
braced block that returns an owned value. Do not bind the guard itself to a local in the same
block: it then lives to the end of the block.

An arm with any guard does not count toward exhaustiveness. This includes an `if let` guard
whose pattern cannot fail. rustc still reports E0004 for the value that the guard covers.

## Scrutinee place versus value

Matching a place inspects existing storage. Matching a value expression creates a temporary.
The `match` scrutinee is not a temporary scope, so that temporary lives until the end of the
enclosing temporary scope. That is usually the statement. For a `match` that is a block tail on
edition 2024, it is right after the tail expression.

| Scrutinee | Ownership question |
| --- | --- |
| `match local` | Which fields move from or borrow the local? |
| `match &local` | Which bindings inherit a reference binding mode? |
| `match make()` | The temporary lives through every arm. Does it hold a lock or borrow? |
| `match *pointer` | Is the dereference a safe place, and what can move from it? |
| `if let ... = make()` | Edition 2024 drops the temporary before `else`. Edition 2021 keeps it through `else` |

Do not change a scrutinee between a place and a value (a named guard versus an inline `lock()`),
and do not rewrite `match` into `if let` or the reverse, without checking destructor and borrow
timing. The `rust-borrow-semantics` skill, when it is installed, has the full temporary-scope
analysis.

## Or-patterns

Every alternative must bind the same names with the same types and binding modes. Prefer one arm
per case when alternatives need different guards or side effects. Use an or-pattern when the
alternatives have the same binding contract and the same body.

## Match exhaustiveness is a behavior decision

Do not add `_ => {}` only to satisfy rustc. A new variant then takes the wildcard path
silently. For a closed enum this crate owns, list every variant. The `rust-discipline` skill, when
it is installed, holds the exhaustiveness policy and the `wildcard_enum_match_arm` lint.

## Edition 2024 match ergonomics

Edition 2024 adds two rules:

- A `mut`, `ref`, or `ref mut` modifier on a binding is an error when the default binding mode
  is `ref` or `ref mut`.
- A reference pattern (`&` or `&mut`) can match only while the default binding mode is move.

The errors have no error code. Do not invent one for a probe.

| Message | Example on `value: &Option<T>` | Fix |
| --- | --- | --- |
| `cannot explicitly borrow within an implicitly-borrowing pattern` | `Some(ref x)` | Remove `ref`. `x` already borrows. On `&mut Option<T>`, write `&mut Some(ref x)` to keep a shared borrow (rustc's help) |
| `cannot mutably bind by value within an implicitly-borrowing pattern` | `Some(mut n)` | For a `Copy` type, write `&Some(mut n)`. Otherwise remove `mut` and clone into a new `let mut` in the body |
| `cannot explicitly dereference within an implicitly-borrowing pattern` | `Some(&n)` on `&Option<&u32>` | Write `&Some(&n)` |

In edition 2021, `mut` on a binding resets the default binding mode to move. `Some(mut n)` on
`&Option<u32>` compiles there and makes `n` a `u32` copy, not a `&u32`. On `&Option<String>` it
fails with E0507.

To migrate:

1. List the affected patterns with
   `cargo clippy --locked --all-targets --all-features -- -W rust_2024_incompatible_pat`. Use
   `--all-features` only when the features are additive. Otherwise run it once per supported
   feature set. Repeat it per shipping target as the `cargo-workflows` skill describes, when it is
   installed.
2. `cargo fix --edition` applies this lint, which is part of `rust-2024-compatibility`. It
   rewrites each pattern to a fully explicit form with the same meaning in every edition.
3. Review each rewrite. The explicit form keeps the 2021 meaning, including a silent copy. Decide
   per site whether a borrow was intended.

Do not copy a pattern from an edition 2021 example into an edition 2024 crate without compiling
it in the target crate.

## Related skills

Each applies when it is installed.

| Skill | Boundary |
| --- | --- |
| `rust-borrow-semantics` | Temporary scopes, place expressions, and two-phase borrows |
| `rust-compiler-errors` | General E0382, E0507, E0509, E0499, and E0502 triage |
| `rust-discipline` | Exhaustiveness policy and public API review |
| `rust-callback-bounds` | Closure patterns and higher-ranked callback bounds |
| `cargo-workflows` | Edition migration and compatibility lints |
