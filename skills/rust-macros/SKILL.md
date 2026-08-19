---
name: rust-macros
description: Use when you write or debug a Rust macro — a macro_rules! declarative macro, a derive macro, an attribute macro, or the crate split that ships one. Covers textual scope, macro_use and macro_export, $crate, macro hygiene, fragment specifiers and follow-set restrictions, the recursion limit, format strings from concat! and stringify!, proc-macro crate rules, compile_error! instead of a panic, helper attributes, the two-crate facade and derive split, absolute paths, and narrow generic bounds. Triggers on "macro_rules", "declarative macro", "write a derive macro", "proc macro", "procedural macro", "attribute macro", "macro hygiene", "fragment specifier", "cannot find macro in this scope", "recursion limit reached while expanding", "proc-macro derive panicked", "cyclic package dependency", "cargo expand", "token stream", "quote!", or "syn".
license: BSD-3-Clause
---

# Rust macros

## Purpose

Write and debug a `macro_rules!` macro, a derive macro, or an attribute macro. Three rules
decide whether a macro compiles at all: textual scope, hygiene, and the follow-set
restrictions on fragment specifiers. This skill covers those three, the crate split a
procedural macro needs, and the paths and bounds its output must emit. It stops at the macro.
Which crates a workspace holds and which way its normal dependencies point belong to
`rust-crate-architecture`.

Every error message and every number below comes from rustc 1.97.0, edition 2024.

## Decide whether you need a macro

| You want | Reach for | Why not a macro |
| --- | --- | --- |
| One body, many types | A generic function, or a blanket impl | Monomorphization already does this |
| A constant computed at build time | `const fn`, or a `const { }` block | You add no syntax |
| Code generated from a schema or a data file | `build.rs` plus `include!` | The input is not Rust tokens |
| Repeated syntax inside one crate | `macro_rules!` | — |
| The same trait impl per type, derived from the type's shape | A derive macro | — |
| An item rewritten or wrapped | An attribute macro | — |

A macro costs compile time, a second crate in the procedural case, diagnostics that point at
the invocation instead of the defect, and an IDE that cannot look inside. Take a non-macro row
when one fits.

## Route the symptom

| Symptom or task | Section |
| --- | --- |
| `error: cannot find macro ... in this scope` | [Scope is textual](#scope-is-textual) |
| `error[E0425]: cannot find value ...`, with a macro-hygiene note | [Hygiene stops at bindings](#hygiene-stops-at-bindings) |
| `error[E0428]: the name ... is defined multiple times` from two invocations | [Hygiene stops at bindings](#hygiene-stops-at-bindings) |
| ``error: `$x:frag` is followed by ..., which is not allowed`` with no invocation | [Fragment specifiers](#fragment-specifiers) |
| `error: no rules expected ...` when one macro forwards to another | [Fragment specifiers](#fragment-specifiers) |
| `error: recursion limit reached while expanding` | [Fragment specifiers](#fragment-specifiers) |
| `error: format argument must be a string literal` | [Build a format string](#build-a-format-string) |
| ``error: `proc-macro` crate types currently cannot export any items other than ...`` | [Procedural macro crates](#procedural-macro-crates) |
| `error: can't use a procedural macro from the same crate that defines it` | [Procedural macro crates](#procedural-macro-crates) |
| `error: proc-macro derive panicked` | [Report errors, do not panic](#report-errors-do-not-panic) |
| `error: cannot find attribute ... in this scope` next to a `#[derive]` | [Report errors, do not panic](#report-errors-do-not-panic) |
| `error: cyclic package dependency` from a derive-crate back edge | [references/derive-macro-crates.md](references/derive-macro-crates.md) |
| `error[E0405]: cannot find trait ... in module ...`, from a derive macro | [references/derive-macro-crates.md](references/derive-macro-crates.md) |
| You must see what the macro produced | [Read the expansion](#read-the-expansion) |

## Scope is textual

A `macro_rules!` macro is the one item in Rust whose definition must appear **before** its use
in source order. A refactor that moves the definition down the file breaks the build, and the
message names no missing import.

```text
error: cannot find macro `hello` in this scope
 --> m1.rs:1:13
  |
1 | fn main() { hello!(); }
  |             ^^^^^ consider moving the definition of `hello` before this call
  |
note: a macro with the same name exists, but it appears later
```

The same rule applies across modules. A macro defined in `mod a` is invisible in `mod b`, even
when `b` comes later:

```text
error: cannot find macro `only_here` in this scope
  = help: have you added the `#[macro_use]` on the module/import?
```

Three ways to widen the scope:

| Goal | Write | Effect |
| --- | --- | --- |
| Use it in later modules of the same crate | `#[macro_use] mod a;` | The macro joins the crate-root macro scope from that point on |
| Import it by path anywhere in the crate | `#[macro_export]` on the definition, then `use crate::name;` | The macro lands at the crate root, whatever module defines it |
| Export it to other crates | `#[macro_export]`, then `use thatcrate::name;` in the caller | Same crate-root placement, now public |

```rust
#[macro_use]
mod defs {
    macro_rules! shared {
        () => {
            2
        };
    }
}

mod uses {
    pub fn value() -> i32 {
        shared!()
    }
}

fn main() {
    println!("{}", uses::value());
}
```

### `#[macro_export]` needs `$crate` on every emitted path

An exported macro expands in the caller's crate, where none of your items are in scope. Write
`$crate::` in front of every path the expansion names. `$crate` resolves to your crate in the
caller and to `crate` at home.

```rust,ignore
// Fails in every other crate: `render` is not in the caller's scope.
#[macro_export]
macro_rules! show_bad {
    ($v:expr) => {
        render($v)
    };
}

// Correct.
#[macro_export]
macro_rules! show_good {
    ($v:expr) => {
        $crate::render($v)
    };
}
```

The missing `$crate` passes in one place only: a module of the defining crate that already has
`render` in scope. It fails in every downstream crate, in your own `#[cfg(test)] mod tests`,
and in your own `tests/*.rs`. Put one invocation in `tests/` to catch it before you publish.

```text
error[E0425]: cannot find function `render` in this scope
  = note: this error originates in the macro `show_bad`
```

## Hygiene stops at bindings

Hygiene is not a general namespace shield. It covers exactly the identifiers rustc can rename.

| Identifier a macro creates | Hygienic | Consequence |
| --- | --- | --- |
| `let` binding, function parameter | Yes | The caller cannot name it, and you cannot hand a name back |
| Lifetime, loop label | Yes | Same |
| `struct`, `enum`, `fn`, `const`, `mod`, `static` | **No** | The caller sees it, and two invocations collide |
| Type name, field name, method name | **No** | Same |
| Macro name | **No** | Same |

A generated local is invisible outside the expansion:

```rust,compile_fail
macro_rules! decl {
    () => {
        let tmp = 7;
    };
}

fn main() {
    decl!();
    println!("{tmp}");
}
```

```text
error[E0425]: cannot find value `tmp` in this scope
help: an identifier with the same name is defined here, but is not accessible due to macro hygiene
```

A generated item is visible, so a fixed item name collides on the second invocation:

```rust,compile_fail
macro_rules! mk_tag {
    ($n:ident) => {
        struct $n;
        struct Inner;
    };
}

mk_tag!(Alpha);
mk_tag!(Beta);

fn main() {}
```

```text
error[E0428]: the name `Inner` is defined multiple times
  = note: `Inner` must be defined only once in the type namespace of this module
```

Two fixes. Derive every generated item name from a metavariable, or wrap the private helpers in
an anonymous `const _: () = { ... };` block. Each expansion of that block gets its own item
namespace, and an `impl` inside it still applies to the outer type.

```rust
macro_rules! mk_tag {
    ($n:ident) => {
        pub struct $n;

        const _: () = {
            struct Guard;
            impl $n {
                pub fn tag() -> &'static str {
                    let _g = Guard;
                    stringify!($n)
                }
            }
        };
    };
}

mk_tag!(Alpha);
mk_tag!(Beta);

fn main() {
    println!("{} {}", Alpha::tag(), Beta::tag());
}
```

## Fragment specifiers

### Follow sets are checked at definition time

rustc rejects an illegal token sequence when it reads the `macro_rules!` item, before anyone
invokes the macro. Design the separators before you write the arms.

Measured on rustc 1.97.0, edition 2024, by probing each fragment with a following `$x:ident`
and a following `+`:

| Fragment | Tokens allowed after it |
| --- | --- |
| `expr`, `stmt` | `=>`, `,`, `;` |
| `pat` | `=>`, `,`, `=`, `if`, `if let`, `in` |
| `pat_param` | The `pat` set, plus `\|` |
| `ty`, `path` | `{`, `[`, `=>`, `,`, `>`, `=`, `:`, `;`, `\|`, `as`, `where` |
| `vis` | `,`, an identifier, or any token that starts a type |
| `ident`, `lifetime`, `literal`, `block`, `meta`, `tt`, `item` | No restriction |

```text
error: `$e:expr` is followed by `$s:stmt`, which is not allowed for `expr` fragments
  = note: allowed there are: `=>`, `,` or `;`
```

`pat` matches a top-level or-pattern since edition 2021, which is why `|` cannot follow it. Use
`pat_param` when `|` must be your separator.

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
tokens compile, 128 fail.

```text
error: recursion limit reached while expanding `count!`
  = help: consider increasing the recursion limit by adding a `#![recursion_limit = "256"]` attribute to your crate
```

Raising the limit is legitimate for a deliberately recursive macro. Prefer a shape that halves
the input per step, because expansion time grows with the count.

## Build a format string

A format string must be a literal. No runtime `String` works, and no variable works.

```text
error: format argument must be a string literal
help: you might be missing a string literal to format with
```

Build one at compile time with `concat!` over `stringify!`. This is the only route from macro
arguments to a format string.

```rust
// `macro_rules!` is textually scoped. Define it before every use in the file.
macro_rules! dump {
    ($($v:ident),* $(,)?) => {
        println!(concat!($(stringify!($v), "={:?} "),*), $($v),*)
    };
}

fn main() {
    let count = 7;
    let name = "x";
    dump!(count, name);
}
```

The `$(,)?` tail accepts an optional trailing comma. Add it to every repetition that a caller
writes across several lines.

## Procedural macro crates

A procedural macro lives in its own crate, marked in `Cargo.toml`:

```toml
[lib]
proc-macro = true
```

Two restrictions follow, and neither error carries an `error[Ennnn]` code or an `--explain`
page. Neither message names the `proc-macro = true` key that caused it.

**It exports macro functions and nothing else.** A `pub struct`, a `pub fn`, or a `pub use` is
rejected. Private items are fine, so keep helpers private inside the crate.

```text
error: `proc-macro` crate types currently cannot export any items other than functions tagged
with `#[proc_macro]`, `#[proc_macro_derive]`, or `#[proc_macro_attribute]`
```

**It cannot invoke its own macros.** A `#[cfg(test)] mod tests` inside `src/lib.rs` cannot
expand them, so put every macro test in the crate's `tests/` directory, which compiles as a
separate crate.

```text
error: can't use a procedural macro from the same crate that defines it
  = help: you can define integration tests in a directory named `tests`
```

A shared helper type must move to a plain support crate that the procedural macro crate depends
on. Do not use the facade crate — the normal crate that holds the trait and re-exports the
derive — for that. See [references/derive-macro-crates.md](references/derive-macro-crates.md)
for the dependency direction and the cycle that edge creates.

### Report errors, do not panic

A panic inside a macro reaches the user as a message with no span on the offending field:

```text
error: proc-macro derive panicked
 --> user/src/main.rs:1:10
  |
1 | #[derive(::facade::Boom)]
  |          ^^^^^^^^^^^^^^
  |
  = help: message: unsupported shape
```

Return a `compile_error!` invocation in the token stream instead. The message then reads as a
normal diagnostic, and `syn::Error::to_compile_error` attaches it to the exact span.

```rust,ignore
#[proc_macro_derive(Checked, attributes(rename))]
pub fn checked(input: TokenStream) -> TokenStream {
    if is_enum(&input) {
        return r#"compile_error!("Checked supports structs only");"#.parse().unwrap();
    }
    emit_impl(&input)
}
```

```text
error: Checked supports structs only
 --> user/src/main.rs:5:10
  = note: this error originates in the derive macro `::facade::Checked`
```

### Declare every helper attribute

A derive macro that reads `#[rename(to = "z")]` must list the attribute in
`#[proc_macro_derive(Checked, attributes(rename))]`. Without the list the user's build fails at
the attribute, not at the derive:

```text
error: cannot find attribute `rename` in this scope
```

Deep material on the two-crate split, absolute paths, and generic bounds is in
[references/derive-macro-crates.md](references/derive-macro-crates.md).

## Read the expansion

Never reason about an expansion you have not read.

```bash
# No install needed. Nightly only. Prints the whole crate after expansion.
cargo +nightly rustc -p <crate> --profile=check -- -Zunpretty=expanded

# One file, no cargo.
rustc +nightly --edition 2024 -Zunpretty=expanded src/main.rs

# Nicer output, and it works on stable through a nightly shim.
cargo install cargo-expand
cargo expand --package <crate> <path::to::item>
```

Test a procedural macro on three axes:

| Test | Where | Runs |
| --- | --- | --- |
| The expansion compiles and behaves | `tests/*.rs` in the macro crate | `cargo test -p <macro-crate>` |
| A rejected input produces the intended message | `trybuild` compile-fail cases | Same command |
| The macro is usable through the facade | A test in the facade crate | `cargo test -p <facade-crate>` |

## Review checklist

- Every `macro_rules!` definition appears above every use in its file.
- A macro used from a later module carries `#[macro_use]` on its module, or `#[macro_export]`.
- Every path an exported macro emits starts with `$crate::`.
- Every generated item name comes from a metavariable, or sits in an anonymous `const _: () = { ... };`.
- Every repetition that spans lines ends with `$(,)?`.
- Separators respect the follow set of the fragment before them.
- A format string comes from `concat!` and `stringify!`, never from a variable.
- The procedural macro crate exports only `#[proc_macro*]` functions, and its tests live in `tests/`.
- A rejected input returns `compile_error!`, and no code path panics.
- Every helper attribute appears in `attributes(...)`.
- The author reads the expansion once with `-Zunpretty=expanded` or `cargo expand`.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-crate-architecture` | Which crates exist and which way normal dependencies point. This skill covers only the extra crate a procedural macro forces and the cycle a back edge to the facade creates |
| `rust-lints` | Lints on the code you write. Expanded code is still linted, so a macro that emits a denied pattern fails a downstream build |
| `rust-compiler-errors` | Reading a diagnostic in general. This skill covers the macro-specific messages that name no import and carry no error code |
| `rust-discipline` | API design of the trait a derive implements, including the delegation macro pattern |
| `rust-serde` | `#[derive(Serialize, Deserialize)]` and its container and field attributes as a contract |
| `rust-test-tools` | Golden tests, cargo-nextest, and CI wiring. It does not cover `trybuild`; this skill holds the compile-fail guidance |
| `rust-code-style` | General item naming and the rustdoc contract. It states nothing macro-specific; an exported macro follows the same item rules |
