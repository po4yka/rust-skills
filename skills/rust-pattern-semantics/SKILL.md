---
name: rust-pattern-semantics
description: Use when a Rust pattern changes ownership, borrowing, guard execution, or temporary lifetime, including match guards, partial moves, binding modes, match ergonomics, place versus value scrutinees, ref patterns, or edition 2024 pattern changes. Triggers on "match guard", "partial move", "binding mode", "match ergonomics", "scrutinee lifetime", "ref pattern", or "guard runs twice".
license: BSD-3-Clause
---

# Rust Pattern Semantics

## Purpose

State exactly what each pattern binding moves or borrows, when a guard runs, and when the
scrutinee drops. Do not read a pattern as destructuring syntax only. It is an ownership and
control-flow operation.

Use `rust-compiler-errors` for a general move or borrow diagnostic. Use this skill when the
answer depends on the pattern, guard, scrutinee form, or edition.

## Analysis order

For each `match`, `if let`, `while let`, or `let else`:

1. Record the crate edition.
2. Classify the scrutinee as a place or value expression.
3. Expand or-patterns into alternatives for reasoning.
4. State the default binding mode at every nesting level.
5. Mark each binding as by value, `ref`, or `ref mut`.
6. Mark partial moves and the fields that remain initialized.
7. Evaluate guard timing and possible repetition.
8. State the scrutinee and binding drop points.

Do not propose a clone, wildcard arm, or `ref` keyword before this pass.

## Binding modes

A non-reference pattern normally binds by value. Match ergonomics can change the default
binding mode when a non-reference pattern matches a reference. An explicit reference pattern
can reset or constrain that mode, and edition 2024 makes these rules more explicit.

Use a type probe when the inferred binding is not obvious:

```rust
fn takes_str(_: &str) {}

let value = Some(String::from("x"));
if let Some(text) = &value {
    takes_str(text);
}
```

Here `text` is a shared borrow. The source is `&Option<String>`, so the inner binding does not
move the `String`.

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

## Match guards run before the arm body

A guard is not an ordinary `if` after the pattern move. Bindings stay protected while the guard
runs. A move into the arm body occurs only after the guard succeeds.

Keep guards pure when practical. A guard attached to an or-pattern can run more than once when
more than one alternative matches. Do not put metrics, mutation, I/O, or one-shot work in it.

```rust,run
#![allow(unreachable_patterns)]

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

If a guard needs expensive or stateful work, match first and run an ordinary control-flow block
in the arm.

## Guard mutation is restricted

Do not infer that a `mut` binding makes guard mutation valid. The match machinery can retain a
shared borrow until the guard completes. Move mutation into the arm body after the guard has
selected the arm, or compute a separate boolean before the match.

When rustc rejects a guard mutation, keep the exact pattern in the probe. Rewriting it as an
`if` proves a different program.

## Scrutinee place versus value

Matching a place inspects existing storage. Matching a value expression creates a temporary
scrutinee. Its lifetime can extend through the match expression.

| Scrutinee | Ownership question |
| --- | --- |
| `match local` | Which fields move from or borrow the local? |
| `match &local` | Which bindings inherit a reference binding mode? |
| `match make()` | How long does the temporary result live? |
| `match *pointer` | Is the dereference a safe place, and what can move from it? |

Do not refactor `match local` to `match make()` or the reverse without checking destructor and
borrow timing. Use `rust-borrow-semantics` for the full temporary-scope analysis.

## Or-patterns

Every alternative must bind the same names with compatible types and binding modes. The guard
applies to the complete or-pattern, not only to the last alternative.

Prefer an arm per case when alternatives need different guards or side effects. Use an
or-pattern when the alternatives have the same binding contract and the same body.

## Match exhaustiveness is a behavior decision

Do not add `_ => {}` only to satisfy rustc. Decide whether the enum is:

- closed and owned by this crate;
- `#[non_exhaustive]` and owned elsewhere;
- a protocol value with an unknown-value policy;
- a state machine where a new state must fail loudly.

Choose an explicit error, a logged unknown case, or a wildcard only after that decision. A
compiler-clean wildcard can hide a semantic regression, which is a repeated LLM repair failure.

## Edition 2024 match ergonomics

Edition 2024 reserves `mut`, `ref`, and `ref mut` modifiers for positions where the binding mode
is fully explicit. A reference pattern can appear only while the default binding mode is move.

During migration:

1. Run the compatibility lints before changing the edition.
2. Apply `cargo fix --edition`.
3. Review every changed pattern for its binding type and move behavior.
4. Compile on the declared MSRV and current toolchain.
5. Run behavior tests for guards and destructor timing.

Do not copy a pattern from an edition 2021 example into an edition 2024 crate without compiling
it in the target crate.

## Verification probes

Use compile-time type assertions to make a binding mode visible:

```rust
fn shared(_: &String) {}
fn mutable(_: &mut String) {}

let mut value = Some(String::from("x"));
if let Some(text) = &value { shared(text); }
if let Some(text) = &mut value { mutable(text); }
```

Use runtime assertions for guard count and drop order. Use `compile_fail` with an error code for
partial moves and edition syntax when rustc provides a stable code.

## Triage

| Symptom | Likely cause | First action |
| --- | --- | --- |
| Value is partly usable after destructuring | The pattern made a partial move | List moved and initialized fields |
| Partial move fails only after adding `Drop` | The destructor needs the whole value | Add a consuming method or `Option::take` |
| Guard side effect occurs twice | Overlapping or-pattern alternatives both matched | Remove the side effect or split the arms |
| Binding became `&T` after a refactor | Match ergonomics changed the default binding mode | Probe the binding type in the target edition |
| Wildcard fixes exhaustiveness but tests fail | The missing variant needed a semantic policy | Add an explicit arm and behavior test |
| Borrow lasts through the whole match | The scrutinee is a place or a temporary with match scope | Mark the exact scrutinee and drop point |

## Checklist

- [ ] The crate edition is known.
- [ ] The scrutinee is classified as a place or value.
- [ ] Every binding has an explicit move or borrow description.
- [ ] Every partial move lists the fields that remain initialized.
- [ ] No partial move comes from a type with `Drop`.
- [ ] Guards are free of one-shot side effects, or repetition is tested.
- [ ] The guard applies to the intended complete or-pattern.
- [ ] A wildcard arm has an explicit compatibility or unknown-value policy.
- [ ] Compile and behavior probes use the target edition and MSRV.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-borrow-semantics` | Temporary scopes, place expressions, and two-phase borrows |
| `rust-compiler-errors` | General E0382, E0507, E0509, E0499, and E0502 triage |
| `rust-discipline` | Exhaustiveness policy and public API review |
| `rust-callback-bounds` | Closure patterns and higher-ranked callback bounds |
| `cargo-workflows` | Edition migration and compatibility lints |
