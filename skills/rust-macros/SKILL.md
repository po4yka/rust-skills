---
name: rust-macros
description: Use when writing, debugging, or reviewing a Rust macro_rules! declarative macro, a procedural macro (derive, attribute, or function-like) built on syn and quote, or the facade and derive crate pair that ships one. Triggers on "cannot find macro in this scope", "recursion limit reached while expanding", "proc-macro derive panicked", "trailing semicolon in macro used in expression position", "cyclic package dependency", "macro_rules", "write a derive macro", "proc macro", "macro hygiene", "fragment specifier", "syn 3", "cargo expand".
license: BSD-3-Clause
---

# Rust macros

Every quoted message and number below comes from rustc, cargo, and Clippy 1.98.1,
edition 2024.

## Decide whether you need a macro

| You want | Reach for | Why not a macro |
| --- | --- | --- |
| One body, many types | A generic function, or a blanket impl | Monomorphization already does this |
| A constant computed at build time | `const fn`, or a `const { }` block | You add no syntax |
| Code generated from a schema or a data file | `build.rs` plus `include!` | The input is not Rust tokens |
| Items or an expression chosen per target or feature | `cfg_select!` (std, Rust 1.95+) | No hand-written macro and no `cfg-if` dependency |
| Repeated syntax inside one crate | `macro_rules!` | — |
| The same trait impl per type, derived from the type's shape | A derive macro | — |
| An item rewritten or wrapped | An attribute macro (procedural) | — |

A macro costs compile time, a second crate in the procedural case, diagnostics that point at
the invocation instead of the defect, and an IDE that cannot look inside. Take a non-macro row
when one fits.

Do not copy nightly macro syntax. As of Rust 1.98.1, a `macro_rules!` arm written
`attr() (...) => ...` fails with ``error[E0658]: `macro_rules!` attributes are unstable``, an arm
written `derive() (...) => ...` fails with ``error[E0658]: `macro_rules!` derives are unstable``,
and `${count($x)}` fails with `error[E0658]: meta-variable expressions are unstable`.

## Route the symptom

| Symptom or task | Section |
| --- | --- |
| `error: cannot find macro ... in this scope` | [Scope is textual](#scope-is-textual) |
| `error[E0425]: cannot find function ...` or `error[E0433]: cannot find ... in the crate root` in another crate, from an exported macro | [Emit absolute paths](#emit-absolute-paths) |
| An error on a caller's type or alias that says `this error originates in the macro` | [Emit absolute paths](#emit-absolute-paths) |
| `error[E0425]: cannot find value ...`, with a macro-hygiene note | [Hygiene stops at bindings](#hygiene-stops-at-bindings) |
| `error[E0428]: the name ... is defined multiple times` from two invocations | [Hygiene stops at bindings](#hygiene-stops-at-bindings) |
| ``error: `$x:frag` is followed by ..., which is not allowed``, or `missing fragment specifier` | [Fragment specifiers](#fragment-specifiers) |
| `error: no rules expected ...` when one macro forwards to another | [Fragment specifiers](#fragment-specifiers) |
| `error: recursion limit reached while expanding` | [Fragment specifiers](#fragment-specifiers) |
| `error: trailing semicolon in macro used in expression position` | [Trailing semicolons](#a-trailing-semicolon-breaks-expression-position) |
| `format argument must be a string literal`, or `there is no argument named ...` | [Build a format string](#build-a-format-string) |
| A proc-macro crate error, `proc-macro derive panicked`, or an undeclared helper attribute | [Procedural macro crates](#procedural-macro-crates) |
| Choosing a `syn` version, or E0599/E0609 on `BareFn`, `unsafety`, or `guard` | [Pick the syn major](#pick-the-syn-major) |
| `error: cyclic package dependency` from a derive-crate back edge | [references/derive-macro-crates.md](references/derive-macro-crates.md) |
| `error[E0405]: cannot find trait ... in module ...`, from a derive macro | [references/derive-macro-crates.md](references/derive-macro-crates.md) |
| You must see what the macro produced, or prove it works | [Read the expansion and verify](#read-the-expansion-and-verify) |

## Read the expansion and verify

Read the expansion before you reason about why a macro fails.

```bash
# Nightly toolchain. Prints the whole crate after expansion.
cargo +nightly rustc --locked -p <crate> --profile=check -- -Zunpretty=expanded

# One file, no cargo.
rustc +nightly --edition 2024 -Zunpretty=expanded src/main.rs

# Works on the stable toolchain: it sets RUSTC_BOOTSTRAP=1 for the -Zunpretty call.
cargo install --locked cargo-expand
cargo expand --locked --package <crate> <path::to::item>
```

Expansion to text is lossy: it prints hygienic identifiers as plain names. Do not paste the
output back as source. It can fail to compile, or compile and behave differently.

| Claim | Check |
| --- | --- |
| The expansion compiles and behaves in another crate | An invocation in `tests/*.rs` of the macro crate: `cargo test --locked -p <macro-crate>` |
| Emitted paths survive the caller's names | A test module that defines `mod facade {}` and `type Result<T> = ...;`, then invokes the macro |
| A rejected input produces the intended message | `trybuild` compile-fail cases, same command |
| No `crate::` path and no metavariable inside `unsafe` | `cargo clippy --locked --all-targets -- -D warnings` reports no `crate_in_macro_def` or `macro_metavars_in_unsafe`. The second lint has [preconditions](#keep-caller-expressions-out-of-unsafe-blocks) |
| No trailing `;` in an expression-position arm | One invocation in expression position inside the defining crate, for example in a `#[cfg(test)] mod tests` |
| The macro is usable through the facade | A test in the facade crate: `cargo test --locked -p <facade-crate>` |

rustc does not report most lints, for example `unused_variables` and `unsafe_code`, in the
expansion of another crate's macro. Lint the expansion through an invocation inside the defining
crate.

Set up `trybuild` with `trybuild = "1"` under `[dev-dependencies]` and a `#[test]` that calls
`trybuild::TestCases::new().compile_fail("tests/ui/*.rs")`. Run
`TRYBUILD=overwrite cargo test --locked` to write the `.stderr` files, and review each one before
you commit it.

A green run proves only the input shapes you tested. Add one case per supported shape: a
generic type, a `PhantomData<T>` field, a unit struct, and each rejected shape. Read
[references/review-checklist.md](references/review-checklist.md) when you review a finished
macro change.

## Emit absolute paths

A macro expands in the caller's module. Every path in its output resolves there, against the
caller's imports and local items.

| The path names | Emit | Because |
| --- | --- | --- |
| An item of the macro's own crate | `$crate::render(...)` | A bare `render` fails in every other crate with E0425. `crate::render` names the caller's crate, and `clippy::crate_in_macro_def` flags it |
| A standard-library item | `::core::result::Result`. Use `::std::` or `::alloc::` only for an item that `core` does not have | A bare `Result` resolves to the caller's `type Result<T> = ...` alias. `::std::` and `::alloc::` fail with E0433 in a `#![no_std]` caller; to serve one, re-export the item through `$crate::__private` |
| An item of a dependency of the macro crate | Re-export it (`#[doc(hidden)] pub mod __private { pub use dep_name; }`) and emit `$crate::__private::dep_name::Item`. From a derive, re-export it from the facade and emit `::facade::__private::dep_name::Item` | `::dep_name` resolves in the caller's crate, and the caller may not depend on `dep_name` |
| The derive attribute | `#[::core::derive(...)]` when the macro crate's `rust-version` is 1.96 or later, else `#[::core::prelude::v1::derive(...)]` | `derive` also resolves at the call site. Rust 1.95 rejects `::core::derive` with E0433 |

Emit `::dep_name::` only for a crate that the caller must depend on directly, such as the facade.
A `tests/*.rs` invocation does not catch a `::dep_name::` path, because an integration test
sees every dependency of its package. Do not put `$crate::` in front of a path the caller passed
in as a metavariable. That path names an item in the caller's crate.

A missing `$crate` passes in one place only: a module of the defining crate that already has
the item in scope. It fails in every downstream crate, in a `#[cfg(test)] mod tests` that does
not `use super::*`, and in your own `tests/*.rs`. A bare standard-library name fails only in a
caller that shadows it, for example E0107 on a bare `Result<T, E>` under a caller's
`type Result<T>` alias. Read [references/declarative-macros.md](references/declarative-macros.md)
when you need that reproduction as a test. A derive macro follows the same rule with `::facade::Trait` paths; see
[references/derive-macro-crates.md](references/derive-macro-crates.md).

## Keep caller expressions out of `unsafe` blocks

`unsafe { f($e) }` evaluates the caller's expression `$e` inside your `unsafe` block, so the
caller can write unsafe operations with no `unsafe` keyword at the call site. Evaluate each
metavariable into a local before the block: `let v = $e;`, then `unsafe { f(v) }`.
`clippy::macro_metavars_in_unsafe` flags the unbound form. It fires only on an invocation in
the defining crate, such as a `#[cfg(test)] mod tests`; an invocation in `tests/*.rs` does not
trigger it. By default the lint checks only `#[macro_export]` macros. For a private macro, set
`warn-unsafe-macro-metavars-in-private-macros = true` in `clippy.toml`.

A local does not help when the block's soundness depends on the value the caller passes. Then
emit a call to an `unsafe fn` outside any `unsafe` block, so the caller must write `unsafe`.

A downstream `#![forbid(unsafe_code)]` does not reject an `unsafe` block that another crate's
macro emits. The macro crate owns the soundness of every `unsafe` block in its expansion.

## Scope is textual

A `macro_rules!` macro is the one item in Rust whose definition must appear **before** its use
in source order. A refactor that moves the definition down the file breaks the build, and the
message names no missing import.

```text
error: cannot find macro `hello` in this scope
  |             ^^^^^ consider moving the definition of `hello` before this call
note: a macro with the same name exists, but it appears later
```

The same rule applies across modules. A macro defined in `mod a` is invisible in `mod b`, even
when `b` comes later:

```text
error: cannot find macro `only_here` in this scope
  = help: have you added the `#[macro_use]` on the module/import?
```

Four ways to widen the scope. Prefer the first: it keeps the macro private and needs no
crate-root placement.

| Goal | Write | Effect |
| --- | --- | --- |
| Use it in another module, crate-private | `pub(crate) use name;` after the definition | The macro becomes an ordinary item of that module, reachable by path |
| Use it in later modules of the same crate | `#[macro_use] mod a;` | The macro joins the crate-root macro scope from that point on |
| Import it by path anywhere in the crate | `#[macro_export]` on the definition, then `use crate::name;` | The macro lands at the crate root, whatever module defines it |
| Export it to other crates | `#[macro_export]`, then `use thatcrate::name;` in the caller | Same crate-root placement, now public |

`#[macro_export]` puts the macro in the public API of the crate and at its root. Do not reach
for it to cross a module boundary inside one crate.

## Hygiene stops at bindings

Hygiene is not a general namespace shield. It covers exactly the identifiers rustc can rename.

| Identifier a macro creates | Hygienic | Consequence |
| --- | --- | --- |
| `let` binding, function parameter | Yes | The caller cannot name it, and you cannot hand a name back |
| Loop label, block label | Yes | Same as a `let` binding |
| Lifetime | **No** | A generated `<'a>` and a caller's `'a` are the same name. Take the lifetime name from a metavariable, or pick one no caller uses |
| `struct`, `enum`, `fn`, `const`, `mod`, `static` | **No** | The caller sees it, and two invocations collide |
| Type name, field name, method name | **No** | Same |
| Macro name | **No** | Same |

A generated local is invisible to the caller: E0425 with `help: an identifier with the same name
is defined here, but is not accessible due to macro hygiene`. A fixed item name collides on the
second invocation with ``error[E0428]: the name `Inner` is defined multiple times``.

Two fixes. Derive every generated item name from a metavariable, or wrap the private helpers in
an anonymous `const _: () = { ... };` block. Each expansion of that block gets its own item
namespace, and an `impl` inside it still applies to the outer type. Read
[references/declarative-macros.md](references/declarative-macros.md) when you need the
reproductions or a working `const _` example.

## Fragment specifiers

### Follow sets are checked at definition time

rustc rejects an illegal token sequence when it reads the `macro_rules!` item, before anyone
invokes the macro. Design the separators before you write the arms. Only `=>`, `,`, or `;` may
follow an `expr` or `stmt` fragment, and `|` cannot follow `pat`; use `pat_param` when `|` must
be your separator. Read [references/declarative-macros.md](references/declarative-macros.md)
when you pick a separator after `pat`, `ty`, `path`, or `vis`; it has the full follow-set table.

```text
error: `$e:expr` is followed by `$s:stmt`, which is not allowed for `expr` fragments
  = note: allowed there are: `=>`, `,` or `;`
```

Every metavariable in a matcher needs a fragment specifier. `($x) =>` fails with
`error: missing fragment specifier` in every edition since Rust 1.89.

### A parsed fragment is opaque to the next matcher

Once a matcher captures `$e:expr`, the capture is a single AST node, not tokens. Forwarding it
to a macro that expects `$i:ident` fails even when the caller wrote a bare identifier.

```text
error: no rules expected `expr` metavariable
note: while trying to match meta-variable `$i:ident`
```

Capture as `tt` in the outer macro when you must forward to an inner matcher, and parse only at
the last step that needs the fragment.

### Edition 2024 widened `expr`

In edition 2024 `$e:expr` also matches `const { 1 + 1 }` and the underscore expression `_`.
Edition 2021 rejects the const block with ``error: no rules expected keyword `const` `` and
the underscore with ``error: no rules expected reserved identifier `_` ``. An arm that
assumes the capture is a value expression can now receive `_`, which is not one. Use
`expr_2021` to keep the edition 2021 match set.

### The recursion limit is 128 expansions

A `tt`-muncher costs one expansion per token. Measured with a counting muncher: 127 input
tokens compile, 128 fail with ``error: recursion limit reached while expanding `count!` ``.
A crate-root `#![recursion_limit = "256"]` is legitimate for a deliberately recursive macro.
Prefer a shape that halves the input per step, because expansion time grows with the count.

### A trailing semicolon breaks expression position

The braces around an arm body are delimiters, not a block. `() => { 42; }` expands to the
statement `42;`, and `let x = val!();` needs an expression. The
`semicolon_in_expressions_from_macros` lint rejects it, deny-by-default since Rust 1.91.
On Rust 1.98.1 the lint fires only when the macro is defined in the crate that invokes it. An
invocation from `tests/*.rs` or a downstream crate compiles without a warning. The 1.99 beta
adds a separate lint that also covers macros from other crates, so downstream builds can
report the defect once 1.99 is stable.

Remove the `;` after the last expression. When the body needs statements, add an inner block
with double braces: `() => {{ let base = 40; base + 2 }}`.

## Build a format string

A format string must be a literal token: forward the caller's literal with `$fmt:literal`, or
build one with `concat!`. A format string from `concat!` cannot capture variables inline. The
`$(,)?` tail accepts an optional trailing comma; add it to every repetition that a caller writes
across several lines. Read [references/declarative-macros.md](references/declarative-macros.md)
when a macro builds or forwards a format string.

## Procedural macro crates

A procedural macro lives in its own crate:

```toml
[lib]
proc-macro = true

[dependencies]
proc-macro2 = "1"
quote = "1"
syn = "3"
```

The crate exports macro functions and nothing else, and it cannot invoke its own macros.
Neither error carries an `error[Ennnn]` code or names the `proc-macro = true` key.

| Symptom | Cause | Fix |
| --- | --- | --- |
| ``error: `proc-macro` crate types currently cannot export any items other than functions tagged with `#[proc_macro]`, ...`` | A `pub struct`, `pub fn`, or `pub use` in the macro crate | Keep helpers private. Move a shared type to a plain support crate that the macro crate depends on, never to the facade |
| `error: can't use a procedural macro from the same crate that defines it`; a test build adds ``help: you can define integration tests in a directory named `tests` `` | A `#[cfg(test)] mod tests` in `src/lib.rs` invokes the macro | Put macro tests in `tests/`, which compiles as a separate crate |
| `error: proc-macro derive panicked` with `help: message: ...` and a span on the whole derive | A `panic!`, `unwrap`, or `expect` in the macro | Return a `syn::Error` at the offending span; see below |
| `error: cannot find attribute ... in this scope` on a field | The derive reads a helper attribute it did not declare | List it: `#[proc_macro_derive(Checked, attributes(checked))]` |
| ``error[E0659]: `inline` is ambiguous`` on a field; `ambiguous_derive_helpers` warning in the macro crate | A helper attribute shares a built-in attribute's name | Name the helper after the derive, for example `checked` |

Keep the `#[proc_macro_derive]` function thin. Parse with `syn::parse_macro_input!`, put the
logic in `fn expand(input: DeriveInput) -> syn::Result<proc_macro2::TokenStream>`, and map an
error with `.unwrap_or_else(syn::Error::into_compile_error)`. The user then sees a normal
diagnostic on the span you chose.

Read [references/derive-macro-crates.md](references/derive-macro-crates.md) when you write a
derive or set up the facade and derive pair: skeleton, dependency direction, generic bounds,
and the missing-derive error.

### Pick the syn major

syn 3 is current (3.0.0 on 2026-07-18). As of 2026-09, `serde_derive`, `thiserror-impl`,
`tokio-macros`, and `clap_derive` require `syn ^3`, while other popular macro crates still use
syn 2. Each major in the tree is a separate build of a large crate.

```bash
cargo tree --locked -e normal,build -i syn
```

One version prints its dependents. Two majors print ``error: specification `syn` is ambiguous``
and list both. Run `cargo tree --locked -e normal,build -i syn@2` to list the dependencies
that still build syn 2. Use the major the tree already builds. When the tree has both or none, use
`syn = "3"`. syn-2 code fails on syn 3 with E0599, E0609, or E0432 on renamed items such as
`Type::BareFn`, `Signature::unsafety`, and `Arm::guard`. Read
[references/syn-3.md](references/syn-3.md) when you port a macro crate or fix those errors.

## Related skills

Use these skills by name when they are installed.

| Skill | Boundary |
| --- | --- |
| `rust-crate-architecture` | Which crates exist and which way normal dependencies point, apart from the macro crate pair |
| `rust-lints` | Lint policy for the code you write |
| `rust-compiler-errors` | Diagnostics that do not come from a macro |
| `rust-unsafe` | Soundness of the `unsafe` code a macro emits |
| `rust-discipline` | API design of the trait a derive implements, including the delegation macro pattern |
| `rust-serde` | `#[derive(Serialize, Deserialize)]` and its container and field attributes as a contract |
| `rust-test-tools` | Golden tests and CI wiring. `trybuild` guidance stays in this skill |
