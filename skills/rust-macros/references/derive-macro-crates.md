# Derive macro crates

Everything below was measured on a three-crate workspace (`facade`, `facade_derive`, `user`),
rustc 1.97.0 and cargo 1.97.0, edition 2024. `facade` and `facade_derive` are placeholder
names; use your own.

## The two-crate split

A derive macro cannot live beside the trait it implements. A crate with `proc-macro = true`
exports macro functions only, so the trait needs a second, normal crate.

Ship the pair as **one** dependency. The facade crate holds the trait, depends on the derive
crate, and re-exports the derive. The user then adds one dependency and writes one `use`.

```toml
# facade/Cargo.toml
[package]
name = "facade"
version = "0.1.0"
edition = "2024"

[dependencies]
facade_derive = { path = "../facade_derive", version = "=0.1.0" }
```

```toml
# facade_derive/Cargo.toml
[package]
name = "facade_derive"
version = "0.1.0"
edition = "2024"

[lib]
proc-macro = true

# Legal, and it is how this crate tests itself. See "The back edge" below.
[dev-dependencies]
facade = { path = "../facade" }
```

```rust,ignore
// facade/src/lib.rs
pub trait Named {
    fn name() -> &'static str;
}

// A trait and a macro live in different namespaces, so both may be called `Named`.
pub use facade_derive::Named;
```

One import in user code then enables the derive and the trait method:

```rust,ignore
use facade::Named;

#[derive(Named)]
struct Plain;

fn main() {
    println!("{}", Plain::name());
}
```

Lock the two version numbers with an exact requirement, `version = "=0.1.0"`, and release
them together. A bare `version = "0.1.0"` is the caret range `^0.1.0`, so it accepts every
0.1.x derive. A facade that accepts a range of derive versions ships a derive whose output the
trait no longer matches.

## The reverse edge is fatal

The facade already depends on the derive crate. A normal dependency from the derive crate
back to the facade closes the cycle at once. Cargo resolves the package graph from the
manifests alone, so the refusal does not wait for any source change. `cargo build` and
`cargo tree` both fail as soon as the second edge lands:

```text
error: cyclic package dependency: package `facade v0.1.0 (...)` depends on itself. Cycle:
package `facade v0.1.0 (...)`
    ... which satisfies path dependency `facade` (locked to 0.1.0) of package `facade_derive v0.1.0 (...)`
    ... which satisfies path dependency `facade_derive` (locked to 0.1.0) of package `facade v0.1.0 (...)`
```

The message names no source line and no `.rs` file. It appears on `cargo build -p user`, in a
crate that touched neither manifest.

Deleting the re-export does not break the cycle, because cargo reads the manifests and not
the source. It also pushes two dependencies and two version numbers onto every user. Delete
the derive crate's normal dependency on the facade instead, and emit fully qualified paths
from the macro.

## The back edge as a dev-dependency is legal

A `[dev-dependencies]` edge from the derive crate back to the facade does not form a cycle,
because dev-dependencies are excluded from the build graph of the library itself. This is how a
derive crate tests its own output.

```rust,ignore
// facade_derive/tests/derive_test.rs — a separate crate, so the derive is usable here.
use facade::Named;

#[derive(Named)]
struct Inside;

#[test]
fn emits_the_name() {
    assert_eq!(Inside::name(), "Inside");
}
```

Verified: `cargo test --offline -p facade_derive` reports `test emits_the_name ... ok` and
`test result: ok. 1 passed; 0 failed`.

## Emit absolute paths

A derive expands in a crate you do not control. A relative path such as `facade::Named` is
resolved in the user's module, so any local item named `facade` captures it.

```rust,ignore
// Rejected: the emitted path is relative.
format!("impl facade::Named for {n} {{ ... }}")
```

```rust,ignore
// Correct: the leading `::` forces the extern-prelude crate.
format!("impl ::facade::Named for {n} {{ ... }}")
```

The failure needs only a module with the dependency's name:

```rust,ignore
mod shadow {
    pub mod facade {}          // an unrelated local module

    use ::facade::Named;

    #[derive(Named)]
    pub struct Rel;
}
```

```text
error[E0405]: cannot find trait `Named` in module `facade`
 --> user/src/main.rs:4:14
  |
4 |     #[derive(Named)]
  |              ^^^^^ not found in `facade`
  |
  = note: this error originates in the derive macro `Named`
```

The span points at the `#[derive(...)]` line in the user's file, not at the macro source. The
identical derive that emits `::facade::Named` compiles and runs in the same module.

`::facade::...` is correct only while the dependency keeps that crate name. When a user may
rename it in `Cargo.toml`, read the path from a helper attribute and default to `::facade`:

```rust,ignore
#[derive(Named)]
#[named(crate = "::renamed_facade")]
struct Custom;
```

Declare the attribute, or the user's build fails at the attribute rather than at the derive:

```rust,ignore
#[proc_macro_derive(Named, attributes(named))]
pub fn derive_named(input: TokenStream) -> TokenStream {
    todo!()
}
```

```text
error: cannot find attribute `named` in this scope
```

## Bound only the parameters the body uses

The common `add_trait_bounds` helper pushes the trait bound onto every type parameter of the
input. That is wrong whenever a parameter does not appear in the generated body. The classic
case is `PhantomData`.

```rust,compile_fail
use std::marker::PhantomData;

pub trait Named {
    fn name() -> &'static str;
}

pub struct Tag<T> {
    _m: PhantomData<T>,
}

// The blanket bound a naive derive emits.
impl<T: Named> Named for Tag<T> {
    fn name() -> &'static str {
        "Tag"
    }
}

fn main() {
    println!("{}", <Tag<u32> as Named>::name());
}
```

```text
error[E0277]: the trait bound `u32: Named` is not satisfied
   |
help: the trait `Named` is implemented for `Tag<T>`
note: required for `Tag<u32>` to implement `Named`
```

Drop the bound when the body does not call through the parameter:

```rust
use std::marker::PhantomData;

pub trait Named {
    fn name() -> &'static str;
}

pub struct Tag<T> {
    _m: PhantomData<T>,
}

// No bound on `T`: the body never uses it.
impl<T> Named for Tag<T> {
    fn name() -> &'static str {
        "Tag"
    }
}

fn main() {
    println!("{}", <Tag<u32> as Named>::name());
}
```

Decide the bound per field, not per parameter:

| The generated body | Bound to emit |
| --- | --- |
| Calls the trait on a field of type `T` | `T: Trait` |
| Calls the trait on a field of type `Vec<T>` or `Option<T>` | `T: Trait` |
| Never names `T` at run time (`PhantomData<T>`, a skipped field) | No bound |
| Calls the trait on an associated type `T::Assoc` | `T::Assoc: Trait`, as a where-clause |

Both defects — the relative path and the blanket bound — compile in your own workspace and fail
only in a downstream crate. Add one integration test per shape you support, in the derive
crate's `tests/` directory.

## Checklist

- The facade crate depends on the derive crate. The derive crate has no normal dependency on the facade.
- The facade re-exports the derive, so the user adds one dependency.
- The version requirement between the two crates is exact, and both crates release together.
- The derive crate tests itself from `tests/`, through a `[dev-dependencies]` edge.
- Every path in the emitted tokens starts with `::`.
- A renameable dependency path comes from a helper attribute, and the attribute is declared in `attributes(...)`.
- Bounds are emitted per field, not per type parameter.
- A `PhantomData<T>` case and a generic case both appear in the tests.
