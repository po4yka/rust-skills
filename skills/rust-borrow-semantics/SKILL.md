---
name: rust-borrow-semantics
description: Use when Rust borrowing behavior depends on expression form, including temporary lifetime extension, drop scopes, two-phase borrows, place versus value expressions, method autoref, or code that changes after manual desugaring. Triggers on "temporary lifetime", "drop scope", "two-phase borrow", "place expression", "borrow changes after desugaring", "method autoref", or E0716 in an expression-form question.
license: BSD-3-Clause
---

# Rust Borrow Semantics

## Purpose

Find the exact borrow and drop points when types alone do not explain the result. Preserve the
source expression until the analysis is complete. A manual desugaring can remove an implicit
two-phase borrow or change a temporary scope.

Use `rust-compiler-errors` for general diagnostic triage. Use this skill when two expressions
with similar types behave differently because their syntax differs.

## Start with four facts

Record these facts before you propose a fix:

1. Is each operand a place expression or a value expression?
2. Which expression creates each temporary?
3. Which borrow is explicit and which borrow is inserted by autoref or reborrow?
4. Which edition defines the temporary scopes?

Then write the expected reservation, activation, and drop points. Verify them with a small
probe on the workspace toolchain.

## Place expressions and value expressions

A place expression identifies storage. A value expression produces a value. This difference
controls whether an operation moves from existing storage or creates a temporary.

| Shape | Usually a place | Usually a value |
| --- | --- | --- |
| Local, static, dereference, index, field | Yes | No |
| Literal, arithmetic result, function call, constructor | No | Yes |
| Parentheses | Keep the inner classification | Keep the inner classification |
| Block tail | Depends on the tail expression | Depends on the tail expression |

Do not classify from the type. `String` can be a local place or the value returned by a call.

## Temporary scopes

A temporary normally drops at the end of its enclosing temporary scope. Important scopes
include the statement, a condition, a match arm, and a block tail. Edition 2024 narrows some
temporary scopes, including the `if let` scrutinee and a block tail expression.

Use braces to make a drop point explicit when a resource guard must release before later work:

```rust
use std::sync::Mutex;

let state = Mutex::new(vec![1]);
let first = {
    let guard = state.lock().unwrap();
    guard[0]
};
assert_eq!(first, 1);
assert!(state.try_lock().is_ok());
```

Do not use an edition migration as a lock-lifetime refactor. Run behavior tests for code whose
temporaries own locks, transactions, file descriptors, or guards.

## Temporary lifetime extension

Some `let` patterns and initializers extend a borrowed temporary to the end of the block. The
rule is syntactic. It is not general lifetime inference.

```rust,run
fn make() -> String { String::from("alive") }

fn main() {
    let value = &make();
    assert_eq!(value, "alive");
}
```

A borrow passed through an ordinary function call does not get the same extension:

```rust,compile_fail,E0716
fn make() -> String { String::from("short") }
fn keep(value: &String) -> &String { value }

fn main() {
    let value = keep(&make());
    println!("{value}");
}
```

Fix this shape by naming the owner before the borrow:

```rust
fn make() -> String { String::from("long") }
fn keep(value: &String) -> &String { value }

let owner = make();
let value = keep(&owner);
assert_eq!(value, "long");
```

Do not promise that a refactor which adds or removes a call preserves the temporary lifetime.
Compile the exact new expression.

## Two-phase borrows

A two-phase mutable borrow starts as a reservation and becomes exclusive at activation. Shared
access can occur between those points. Rust creates two-phase borrows only for selected implicit
borrows:

| Implicit shape | Typical example |
| --- | --- |
| Autoref of a mutable method receiver | `values.push(values.len())` |
| Mutable reborrow in a function argument | Passing an existing `&mut T` to another call |
| Mutable borrow for overloaded compound assignment | `place += rhs` |

The standard method-call shape compiles:

```rust,run
fn main() {
    let mut values = vec![10, 20];
    values.push(values.len());
    assert_eq!(values, [10, 20, 2]);
}
```

An explicit `&mut` borrow is not automatically two-phase. A manual UFCS rewrite can therefore
fail even when the method call compiles:

```rust,compile_fail,E0502
fn main() {
    let mut values = vec![10, 20];
    let receiver = &mut values;
    Vec::push(receiver, values.len());
}
```

Do not explain the first program as evaluation order alone. Record these points:

1. Reserve the implicit mutable receiver borrow.
2. Evaluate the other arguments. Shared access is allowed during reservation.
3. Activate the mutable borrow at the call.
4. End the borrow after the call unless the result keeps it alive.

Any conflicting write between reservation and activation is still rejected.

## Do not use clone as a scope operator

Cloning can hide the real ownership contract. Before a clone, decide whether the value is:

- a small independent value;
- shared read-only state;
- one resource identity;
- a buffer that should move once;
- a guard whose drop point is the actual problem.

If the problem is a temporary scope, name the owner or add a block. If the problem is two-phase
borrowing, preserve the method-call shape or restructure the argument calculation. A clone is
not the default repair.

## Edition-sensitive review

For an edition change, search for these shapes:

```bash
rg -n 'if let|while let|match|\.lock\(|\.borrow(_mut)?\(' --type rust
```

Run `cargo fix --edition`, but review the diff before accepting it. Test observable destructor
and lock timing. Crates of different editions can coexist during a staged migration; use
`cargo-workflows` for that process.

## Verification ladder

Use the smallest proof that decides the question:

1. Put the exact expression in a standalone file.
2. Compile it with the workspace edition and MSRV when the rule can vary by version.
3. Use a `compile_fail` probe for a rejected borrow and name the expected error code.
4. Use a runtime assertion when the question is the drop point or destructor order.
5. Repeat the real workspace test after the probe. The probe proves the language rule, not the
   application invariant.

Do not use Miri to answer whether code type-checks. Use Miri after compilation when unsafe
aliasing or provenance is also in scope.

## Triage

| Symptom | Likely cause | First action |
| --- | --- | --- |
| Method call compiles, UFCS rewrite fails | The rewrite removed an implicit two-phase borrow | Restore the method call or compute the other argument first |
| E0716 appears after adding a helper call | The helper call removed temporary lifetime extension | Name the temporary owner before the call |
| Lock stays held longer after an edition change | A temporary scope changed | Bind the guard and add an explicit block |
| Adding braces changes whether code compiles | The block changed a temporary or borrow scope | Mark the exact creation and drop points |
| Clone makes the error disappear | Ownership was duplicated, not explained | Decide whether duplication matches the domain |

## Checklist

- [ ] Every relevant operand is classified as a place or value expression.
- [ ] Every temporary has a stated enclosing scope and drop point.
- [ ] Temporary lifetime extension is justified from the exact syntax.
- [ ] Every two-phase borrow comes from an eligible implicit borrow.
- [ ] Reservation and activation points are separate in the explanation.
- [ ] No manual desugaring is treated as semantics-preserving without a compile probe.
- [ ] Edition and MSRV match the supported workspace lane.
- [ ] Runtime tests cover resource drop timing when it affects behavior.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-compiler-errors` | General E0499, E0502, E0597, and E0716 triage |
| `rust-pattern-semantics` | Binding modes, match guards, partial moves, and scrutinee behavior |
| `rust-callback-bounds` | Closure inference and higher-ranked callable bounds |
| `rust-variance` | Lifetime subtyping and coercion through type constructors |
| `cargo-workflows` | Edition migration and MSRV verification |
| `rust-unsafe` | Aliasing, invalid values, and provenance after safe borrow checking ends |
