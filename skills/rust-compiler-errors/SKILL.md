---
name: rust-compiler-errors
description: Use when rustc or cargo fails with a borrow checker, lifetime, trait bound, type inference, or unresolved import error, or any E0xxx code, and the cause matters more than the first fix that compiles. Names the fix that hides the bug and the fix that resolves it. Codes include E0382, E0499, E0502, E0506, E0507, E0373, E0597, E0716, E0521, E0106, E0277, E0308, E0599, E0282, E0283, E0284, E0425, E0432, E0433, E0038, E0275, E0658. Also "does not live long enough", "missing lifetime specifier", "not dyn compatible", "object safety", or a pasted rustc error. Not for E0207 (rust-iterator-impl for an iterator lifetime, rust-event-loop-state for a handler trait's state type), E0658 on impl Trait in an associated type (rust-iterator-impl), E0793 (rust-unsafe), or whether a type is Send (rust-send-sync).
license: BSD-3-Clause
---

# Rust compiler errors

## First moves

```bash
# The full explanation, with a worked example. Works offline.
rustc --explain E0499

# One line per diagnostic, for a wall of output.
cargo build --message-format=short

# Count the error codes in a large failure.
cargo build --message-format=json 2>/dev/null | grep -o '"code":{"code":"E[0-9]*"' | sort | uniq -c | sort -rn
```

Fix the first error, then rebuild. One move or type error produces a cascade downstream, and most
of the cascade disappears with the first fix.

## Prove the fix

- While you iterate, run `cargo check` with the same package, features, and target that failed.
  It reports the same type and borrow errors, faster.
- `cargo check` checks only library and binary targets. Add `--all-targets` when the error came
  from `cargo test`, a bench, or an example.
- Before you call the error fixed, run the command that failed. `cargo check` and `cargo clippy`
  stop before monomorphization and linking, so they exit 0 on "reached the recursion limit while
  instantiating" and on linker errors.
- A clean build proves that the types check, not that the behavior is right. Run the test that
  covers the changed code.

## Fixes that compile and hide the bug

Each of these removes the error and keeps the defect. Do not use one to silence a diagnostic.

| Reflex | What it hides | When it is right, or what to do instead |
| --- | --- | --- |
| `.clone()` for E0382 or E0505 | Two owners of an identity, a handle, or a large buffer; one allocation per loop iteration | The value is small and the copy is the point. Otherwise decide the owner, see [The clone reflex](#the-clone-reflex) |
| `'static` on a field or a bound for E0106, E0597, or E0521 | It demands data that lives forever, and it moves the error to the caller | Store owned data, or scope the borrow |
| `RefCell` or `Rc<RefCell<T>>` for E0499 or E0502 | A `RefCell already borrowed` panic at run time | A split failed and the graph shape needs it |
| `Box::leak` for E0521 or E0597 | Memory that grows once per call | Use `Arc` or `std::thread::scope` |
| `.unwrap()` or `.expect()` to get `T` out of `Option<T>` or `Result<T, E>` for E0308 or E0277 | A panic path. rustc's own `help:` for E0308 on an `Option` suggests `Option::expect` | Use `?` or handle `None` and `Err`. Use `.expect("<invariant>")` only for a documented invariant |
| An `unsafe` block, `unsafe impl Send`, or `transmute` | The check that found the bug; possible undefined behavior | Never for a type or borrow error. Fix the ownership or the type; see the `rust-unsafe` skill |
| `#![feature(...)]` for E0658 | E0554 on stable, and a crate that builds only on nightly | Never in a stable crate. Use a stable alternative, or raise the toolchain and MSRV on purpose |
| `cargo add <name>` from a `help:` line for E0432 or E0433 | rustc suggests `cargo add` for any unknown first path segment, a module of this crate included. A guessed name can be an unrelated or malicious package | Follow [Unresolved imports](#e0432-and-e0433-unresolved-imports) |
| A higher `#![recursion_limit]` for E0275 or "reached the recursion limit while instantiating" | An infinite type chain; the build fails later and slower | See the E0275 row and the "while instantiating" row of the triage table |

After three failed attempts at the same error, suspect the design, not the syntax. Stop editing
and answer these:

1. Which single component should own this data for its whole lifetime?
2. Does the borrow cross a boundary it should not cross: a thread, an `.await`, a callback, an
   FFI call?
3. Would the error disappear if the data were owned rather than borrowed, and what does that cost?

## Triage table

| Code | Message | What it means | First move |
| --- | --- | --- | --- |
| E0382 | borrow of moved value | The value was consumed, then used again | Decide the owner; borrow instead of moving |
| E0505 | cannot move out of `x` because it is borrowed | A live borrow outlives the move | Shorten the borrow, or move before borrowing |
| E0507 | cannot move out of `x` which is behind a shared reference | You need ownership but only hold `&` | Pick by what the original keeps: `mem::take` or `mem::replace` through `&mut`, `Option::take`, a `self` receiver, or a clone. See [references/borrow-checker-fixes.md](references/borrow-checker-fixes.md) |
| E0509 | cannot move out of type `T`, which implements the `Drop` trait | A `Drop` impl blocks every partial move out of the value | Move `Drop` to a one-field guard type and keep the aggregate `Drop`-free. When the cleanup consumes the guard's field, make that one field an `Option` and `.take()` it, or `mem::replace` it. Do not make the aggregate's fields `Option`: each use then needs an `unwrap` |
| E0499 | cannot borrow `x` as mutable more than once at a time | Two live `&mut` to the same place | `split_at_mut`, index disjointly, or scope one borrow |
| E0502 | cannot borrow `x` as mutable because it is also borrowed as immutable | A read borrow is live across a write | Copy the value out, then mutate |
| E0506 | cannot assign to `x` because it is borrowed | A write to a place while a borrow of it is live | Finish the read first, or borrow the fields instead of `self` |
| E0502, E0499 | note: this call may capture more lifetimes than intended | Edition 2024: a returned `impl Trait` captures every lifetime in scope | Add `+ use<..>` to the callee's return type when the returned value does not borrow that argument (1.82+; 1.87+ in a trait). If it does borrow it, end the borrow at the caller. Do not clone at the caller |
| E0596 | cannot borrow as mutable, as it is behind a `&` reference | The parameter is `&T`, not `&mut T` | Change the signature; do not reach for interior mutability first |
| E0373 | closure (or async block) may outlive the current function, but it borrows `x` | A `'static` closure or future (`thread::spawn`, `tokio::spawn`) borrows a local | Add `move`; clone an `Arc` first if the caller still needs the data, or use `thread::scope` |
| E0597 | `x` does not live long enough | A named local is dropped while borrowed | Move the binding to the outer scope |
| E0716 | temporary value dropped while borrowed | A temporary ended before its borrow | Name the owner in a `let`; a function argument such as `bar(&foo())` is never extended. See [references/borrow-checker-fixes.md](references/borrow-checker-fixes.md) |
| E0515 | cannot return reference to local variable | The callee owns the data the caller wants | Return owned, or accept a buffer parameter |
| E0521 | borrowed data escapes outside of function | A borrowed parameter reaches a `'static` bound such as `thread::spawn` | Pass an `Arc` or owned data, or use `thread::scope` |
| E0106 | missing lifetime specifier | A struct or return type holds a reference with no stated source | Struct field: store owned data unless the type is a short-lived view, such as a parser view or a zero-copy frame; a struct lifetime spreads to every type that holds it. Return type: name the input it borrows from, with the narrowest lifetime that is true. See [references/borrow-checker-fixes.md](references/borrow-checker-fixes.md) |
| E0277 | the trait bound `T: X` is not satisfied | A required trait is missing or not in scope | Read which trait and which type; import it or add the bound |
| E0277 | the trait bound `!: X` is not satisfied | Edition 2024 never-type fallback | Name the type, see [the fallback section](#e0282-e0283-e0284-and-the-never-type-need-a-type-anchor) |
| E0277 | `T` cannot be sent between threads safely | A non-`Send` value crosses a thread boundary | Decide with the `rust-send-sync` skill |
| (none) | future cannot be sent between threads safely | A non-`Send` value (an `Rc`, a lock guard, a `RefCell` borrow) lives across an `.await` | Read the `note:`; it names the value and the `.await`. Drop the value before the `.await`, or use `Arc`. `cargo clippy` flags a held lock guard (`clippy::await_holding_lock`, warn by default) |
| E0271 | expected `A` to be an iterator that yields `B` | An associated type does not match | Fix the item type, usually with `map` |
| E0308 | mismatched types | The two sides differ, often by one reference layer or one `Option` | Compare the two types the note prints, not the expressions |
| E0599 | no method named `m` found | Typo, the trait is not imported, or the method is from another version of the crate | `use` the trait from `help:`; otherwise read the locked source, see step 4 [below](#e0432-and-e0433-unresolved-imports) |
| E0631 | type mismatch in function arguments | A function item was passed to a higher-order call; no deref coercion applies at a trait bound | Wrap the call in a closure, or insert `.map(String::as_str)` |
| E0275 | overflow evaluating the requirement `T: X` | The trait solver reached the recursion limit during type checking | A repeating type in the note means an infinite chain: fix the impl. Raise the limit only for a finite, deep type |
| (none) | reached the recursion limit while instantiating | An infinite chain at monomorphization, often `&mut &mut ... W` from a recursive call on a by-value `impl Write` | `cargo check` exits 0 on it. Take `&mut dyn Write`; see the `rust-callback-bounds` skill |
| E0038 | the trait `T` is not dyn compatible | One item of the trait gets no vtable slot | Read the `...because` note. Read [references/dyn-compatibility.md](references/dyn-compatibility.md) when you choose the fix; it maps each note to its fix |
| E0562 | `impl Trait` is not allowed in the return type of `Fn` trait bounds | `impl FnMut(&T) -> impl Ord` puts `impl Trait` in an associated-type binding | Name a generic parameter instead: `<K: Ord>` |
| E0184 | the trait `Copy` cannot be implemented for this type; the type has a destructor | One type asks for both `Copy` and `Drop` | Remove the `Copy` derive; a resource handle is not `Copy` |
| E0367 | `Drop` impl requires `T: Clone` but the struct it is implemented for does not | The `Drop` impl added a bound the type definition does not carry | Move the bound onto the struct definition |
| E0740 | field must implement `Copy` or be wrapped in `ManuallyDrop<...>` | A union field is not `Copy`, `ManuallyDrop<T>`, a reference, or a tuple or array of those | Derive `Copy` when the type allows it. Otherwise wrap the field in `std::mem::ManuallyDrop` and drop it by hand |
| E0432 | unresolved import `x` | A feature is off, a path is wrong, or the crate is missing or does not exist | See [Unresolved imports](#e0432-and-e0433-unresolved-imports) |
| E0433 | cannot find type `T` in this scope; cannot find module or crate `x` in this scope. Before 1.95: failed to resolve: use of undeclared type `T`, or use of unresolved module or unlinked crate `x` | A missing `use`, often from `std`; a module path that needs `crate::` or `super::`; or a missing crate | See [Unresolved imports](#e0432-and-e0433-unresolved-imports) |
| E0425 | cannot find value, type, or function `x` in this scope (E0412 for a type on older toolchains) | Typo, a missing import, or an item behind an off feature | Read the `note:` and `help:`, see [Unresolved imports](#e0432-and-e0433-unresolved-imports) |
| E0603 | `x` is private | The path exists but is not exported | `pub use` it, or use the public path |
| E0658 | use of unstable library feature `f` | The API is unstable, or stable only in a newer Rust than this toolchain | Compare `rustc -V` and the crate's `rust-version` with the version on the API's docs page |
| E0072 | recursive type has infinite size | A type contains itself by value | `Box`, `Rc`, or `Arc` the recursive field; `Weak` for a back edge |
| E0793 | reference to field of packed struct is unaligned | A reference into `#[repr(packed)]` | See the `rust-unsafe` skill |

## The clone reflex

E0382 has one fix that always compiles: `.clone()`. Treat it as a diagnostic, not a fix. The
error stated that two places want the same value. A clone answers "both get one", which is right
for a small owned copy and wrong for an identity, a handle, a large buffer, or shared state.

| The value is | The answer |
| --- | --- |
| Small and `Copy`-like, and the copy is the point | Clone, or derive `Copy` |
| Read by several places, never written | `&T`, or `Arc<T>` when it must cross a thread |
| Written by several places | `Arc<Mutex<T>>`, and check the lock order |
| An identity: a connection, a file, a job | One owner. Pass `&mut` down, or pass a handle |
| Large and consumed once | Move it, and restructure the caller so it can be moved |

A clone inside a loop compiles, is correct, and allocates once per iteration. See the
`rust-performance` skill.

## Borrow conflicts are usually a split problem

E0499 and E0502 rarely need interior mutability. They need the compiler to see that two borrows
touch different data: `split_at_mut` or `get_disjoint_mut` for indices, field borrows instead of a
`&self` helper, or a copy of the value before the write. Reach for `RefCell` only after the splits
fail (see the hazard table).

Read [references/borrow-checker-fixes.md](references/borrow-checker-fixes.md) when the first move
in the triage table does not fit an E0499, E0502, E0506, E0507, E0716, E0373, E0521, or E0106
error, or to compare the cost of each interior mutability type.

## E0282, E0283, E0284, and the never type need a type anchor

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

An unconstrained generic call as a statement, such as `f()?;`, has no anchor at all. Edition 2024
falls back to `!` instead of `()`, so the error names the never type:

```rust,compile_fail,E0277
fn parse_or_default<T: Default>() -> Result<T, ()> { Ok(T::default()) }

fn load() -> Result<(), ()> {
    parse_or_default()?; // the trait bound `!: Default` is not satisfied
    Ok(())
}
```

The note says "this error might have been caused by changes to Rust's type-inference algorithm".
On edition 2021 the same code fails with the deny-by-default lint
`dependency_on_unit_never_type_fallback` (1.92+): "this function depends on never type fallback
being `()`". Both have one fix. Name the type:

```rust
fn parse_or_default<T: Default>() -> Result<T, ()> { Ok(T::default()) }

fn load() -> Result<(), ()> {
    parse_or_default::<()>()?;
    Ok(())
}
```

`let () = parse_or_default()?;` also works. Do not allow the lint; it is a hard error on 2024.

## E0432 and E0433: unresolved imports

Read the `note:` and `help:` lines before you add a dependency. A `cargo add` line in `help:` is
not a fix (see the hazard table). Stop at the first step that matches:

1. `note: found an item that was configured out` with "the item is gated behind the `f`
   feature". The feature is off. Read the file path under the note.
   - The item is in a dependency: enable its feature with `cargo add <crate> --features f`, or
     add `f` to that dependency's `features` list. Do not rewrite the import.
   - The item is in this crate: the caller lacks the item's gate. Put the same
     `#[cfg(feature = "f")]` on the caller, or build with `--features f`. Do not add `f` to
     `default` to silence the error; that hides the break in the build without the feature.
2. `help:` offers a `use` path ("consider importing") or says "a similar path exists". This
   covers `cannot find type` and `cannot find value` (E0425 or E0433) and E0432. Take that path:
   `std::...`, `crate::...`, or `super::...`. Check `std` and this crate before any new crate.
3. The first path segment is a module of this crate: `grep -rn 'mod <segment>' src` finds it.
   Write the path from `crate::` or `super::`.
4. The first path segment is a crate that `Cargo.toml` already lists. The item path is wrong, or
   the item exists only in another version. Read the source of the version in `Cargo.lock`, not
   the documentation of the latest release. Use the package name as `Cargo.toml` writes it: the
   path segment `tokio_util` is the package `tokio-util`.

   ```bash
   cargo metadata --format-version 1 --locked \
     | jq -r '.packages[] | select(.name == "<package>") | "\(.version) \(.manifest_path)"'
   ```

   If `jq` is not installed, `cargo tree -i <package> --locked --depth 0` prints the locked
   version.
5. The crate is not in `Cargo.toml`. Add a crate only when the code was written against that
   crate, or the task asks for a new dependency. Otherwise use `std` or an existing dependency.
   Run `cargo info <name>`: it prints the description, version, `rust-version`, repository, and
   features of that exact package, or "could not find". It proves that the name exists, not that
   it is the crate the code expects. Compare its `repository` and `description` with that crate.
   If they do not match, or the name came only from rustc's `help:` line, do not add it; ask the
   user. Otherwise run `cargo add <name>`.

## A `Drop` impl changes the borrow checker

`impl Drop` is not a local change. It breaks code that compiled before with E0597, E0502, E0509,
or E0184, and no error title names `Drop`: the drop point is one more use of every borrow the value
holds. The note says "... when `_g` is dropped and runs the `Drop` code for type `Guard`". Drop the
guard before the read, scope it in an inner block, or keep the type `Drop`-free. Read the `Drop`
section of [references/borrow-checker-fixes.md](references/borrow-checker-fixes.md) when an error
follows a new `impl Drop`, or for E0507 inside `drop(&mut self)`.

## Related skills

Refer to these by name when they are installed.

| Skill | Use it for |
| --- | --- |
| `rust-borrow-semantics` | Temporary scopes, lifetime extension, two-phase borrows, edition 2024 drop order |
| `rust-callback-bounds` | E0309, E0621, E0502 on a `Fn(&T) -> K` parameter; the `&mut impl Write` recursion chain; `&mut dyn Trait` against `impl Trait` |
| `rust-send-sync` | Whether a type is `Send` or `Sync`, behind every `cannot be sent` message |
| `rust-async-internals` | `Send` across `.await`, cancel safety, and shutdown |
| `rust-unsafe` | E0793 and the layout rules behind it |
| `rust-iterator-impl` | E0207 on an iterator impl |
| `rust-event-loop-state` | E0207 and E0119 on a generic `Handler` trait, and E0499 in a dispatch loop |
| `rust-type-erasure` | `dyn Any` and `TypeId` stores, downcasting, and the `'static` bound of `Any` |
| `rust-discipline` | API shapes that avoid E0038 and the borrow errors; the one-field `Drop` guard |
| `rust-crate-architecture` | Ownership and dependency direction across modules and crates |
| `rust-performance` | The cost of the clone that silenced the error |
| `cargo-workflows` | Build, check, feature, and target commands in full |
