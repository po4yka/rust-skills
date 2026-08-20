---
name: rust-code-style
description: Use when you create a module or crate, move a source file, choose visibility, clean up imports, or review structure and readability. Covers Rust source layout and readability rules, module file layout, lib.rs re-export policy, visibility levels, item order, import grouping, function structure, error-handling crate choice, and naming.
license: BSD-3-Clause
---

# Rust Code Style

## Purpose

Code is technical writing for future readers. Lead with the most important details. Keep
related things close together.

Use this skill when you:

- Create a new crate or a new module.
- Add, split, or move a source file.
- Decide the visibility of an item.
- Order items inside a file, or clean up imports.
- Review a diff for structure and readability.

This skill covers the decisions `rustfmt` cannot make for you. `rustfmt` owns line width,
brace placement, and wrapping. Lint tables, `clippy.toml`, and `rustfmt.toml` live in
`rust-lints`. Crate boundaries and dependency direction live in `rust-crate-architecture`.

---

## Module layout

Use `name.rs` next to a `name/` directory for every module that has children. Use `mod.rs` only
three levels deep or more, and never mix the two patterns at one directory level.

`lib.rs` declares the modules first, then re-exports the public API item by item, with no glob.
A `pub mod prelude` is the one module a caller may glob-import. Keep it short. Avoid `#[path]`.

The file tree, the `lib.rs` example, the prelude collision (E0659), and the `build.rs`
exception are in [references/module-layout.md](references/module-layout.md).

---

## Visibility

Use three levels only. Nothing else.

| Level | When to use |
|-------|-------------|
| private (default) | An implementation detail inside one module |
| `pub(crate)` | An item shared between modules of the same crate |
| `pub` | The crate public API, re-exported from `lib.rs` |

Start private. Widen one step only when a concrete caller in another module needs the
item. Delete the widening when the caller goes away.

Never use `pub(super)` or `pub(in path)`. Both couple the item to the current module
hierarchy. A move of the module silently changes the set of callers of a `pub(super)`
item, and it breaks the build for a `pub(in path)` item.

Do not widen visibility for a test. A child `mod tests` inside the same file already reads
the private items of its parent module. If a test needs an item from another module, the
item is either part of `pub(crate)` API, or the test belongs in the module that owns it.

---

## File structure order

Inside any `.rs` file, place the items in this order:

1. Crate and module attributes (`#![forbid(unsafe_code)]`, `#![allow(...)]`).
2. `mod` declarations: private first, then `pub mod`. The `#[cfg(test)] mod tests`
   declaration is the exception; it goes at the bottom with the other test items.
3. `use` imports (see [Import style](#import-style)).
4. `pub use` re-exports.
5. Constants and statics.
6. Type definitions: structs, enums, type aliases.
7. Trait definitions.
8. `impl` blocks: inherent first, then trait impls.
9. Free functions: public first, then private helpers.
10. `#[cfg(test)] mod tests` at the very bottom.

### Public before private

Inside each group, public items come before private items. The file then reads as a table
of contents: the reader sees the API surface before the internals.

### Types before implementations

Show the struct or enum definition before its `impl` block. The reader must understand the
data shape before the methods make sense.

### Inherent impls before trait impls

Associated functions are the core API. Trait implementations add to it. Show the core
first.

---

## Import style

### Group order

Separate the imports into groups. Put one blank line between the groups:

```rust
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;

use protocol_types::FrameKind;
use telemetry_core::SpanId;

use crate::types::SharedState;
use crate::util::format_duration;
```

The order is: `std` → external crates → workspace crates → `crate::`, `self::`, `super::`.

A stable-toolchain `rustfmt` sorts imports inside a group, but it does not move an import
between groups. Keep the groups by hand.

### Compound braces for two or more items

```rust
// Good. One compound import for several items of the same module.
use std::sync::{Arc, Mutex};

// Good. A single item needs no braces.
use std::collections::HashMap;
```

### Limit the imports

Import the items and traits you use often. For a rarely used item, write the fully
qualified path at the call site instead:

```rust
// Used once in the file. No import.
let elapsed = std::time::Instant::now().duration_since(start);
```

Fewer imports means less import churn and fewer merge conflicts.

---

## Function rules

### Caller before callee

Place a calling function before the functions it calls. The reader then follows the code
top-down:

```rust
pub fn process_request(req: &Request) -> Response {
    let validated = validate(req);
    build_response(validated)
}

fn validate(req: &Request) -> ValidatedRequest {
    // ...
}

fn build_response(data: ValidatedRequest) -> Response {
    // ...
}
```

### Group related statements

Use blank lines to build paragraphs of related statements inside a function:

```rust
fn connect(config: &Config) -> Result<Connection> {
    let addr = config.resolve_address()?;
    let timeout = config.connect_timeout();

    let stream = TcpStream::connect_timeout(&addr, timeout)?;
    stream.set_nodelay(true)?;

    let tls = setup_tls(config)?;
    tls.connect(stream)
}
```

Each paragraph does one thing. A function that needs more than four or five paragraphs is
a candidate for a split.

### Iterator chains and collectors

Never mix a side effect and a pure expression in one statement. Keep every closure in a
`.map()`, `.filter()`, or `.collect()` chain pure. Write a side effect as a `for` loop, and ban
`Iterator::for_each` through `disallowed-methods` in `clippy.toml`. See `rust-lints`.

Never `flat_map` over a `Result`. `Err` yields zero items, so the failure disappears with no
diagnostic. Use `collect` into a `Result` to stop at the first error, `partition` to keep both
halves, and `filter_map` with `.ok()` when the drop is the intent.

The examples and the collector rules are in
[references/iterator-style.md](references/iterator-style.md).

### Business logic uses `if`/`else` and `match`

Keep an early return for bookkeeping only: a null check, a handle check, a permission
guard. Use `if`/`else` and `match` for mutually exclusive business paths, so the control
flow shows the shape of the domain:

```rust
// Good. Every business path is visible in one place.
match backend {
    Backend::Memory => load_from_memory(key),
    Backend::Disk => load_from_disk(key),
    Backend::Remote => load_from_remote(key, endpoint),
}

// Good. An early return for bookkeeping.
if handle == 0 {
    return Err(Error::InvalidHandle);
}
```

A chain of early returns for business paths hides the alternatives. The reader must hold
every previous condition in memory to know when the last line runs.

---

## Error handling

| Context | Crate | Pattern |
|---------|-------|---------|
| Library error types | `thiserror` | `#[derive(thiserror::Error)]` |
| Binary and CLI errors | `anyhow` | `anyhow::Result`, `.context()` |
| Test assertions | `anyhow` | `#[test] fn foo() -> anyhow::Result<()>` |
| Propagation | `?` operator | Never `.unwrap()` in non-test code |
| Crates that need no `unsafe` | `#![forbid(unsafe_code)]` | The default for every such crate |

### Library crates use `thiserror`

A library returns a typed error, so the caller can match on the variant:

```rust
#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    #[error("the request timed out after {0:?}")]
    Timeout(std::time::Duration),

    #[error("the handle is not valid")]
    InvalidHandle,

    #[error("transport failure")]
    Transport(#[from] std::io::Error),
}
```

Never put `anyhow::Error` in the public signature of a library crate. It erases the
variants, so the caller can only print the message.

### Binaries use `anyhow`

A binary or a CLI reports the error to a human. Add context at each layer:

```rust
use anyhow::Context as _;

fn load(path: &std::path::Path) -> anyhow::Result<Config> {
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read the config file {}", path.display()))?;
    let config = toml::from_str(&text).context("failed to parse the config file")?;
    Ok(config)
}
```

### Propagate with `?`

`.unwrap()` and `.expect()` belong in tests only. In non-test code, return the error with
`?` and let the caller decide. For panic policy at a boundary, and for the rules on
`catch_unwind`, see `rust-panic-safety`. For error mapping across an FFI boundary, see
`ffi-error-progress-cancel`.

---

## Rustdoc contract

A doc comment on a public item is part of the API. Three sections carry information the
signature cannot, and `cargo doc` gives each one a heading, so a reader finds them in the same
place every time.

| Section | Required on | States |
| --- | --- | --- |
| `# Errors` | Every public `fn` returning `Result` | Which variants occur, and what causes each |
| `# Panics` | Every public `fn` that can panic | The exact condition. "Never panics" is worth writing when a reader would assume otherwise |
| `# Safety` | Every public `unsafe fn` | What the caller must guarantee. See the `rust-unsafe` skill |

```rust
use std::path::Path;

pub enum ConfigError { NotFound, PermissionDenied, InvalidUtf8 }

/// Reads a configuration file and parses it as UTF-8.
///
/// # Errors
///
/// - [`ConfigError::NotFound`] if `path` does not exist.
/// - [`ConfigError::PermissionDenied`] if the process cannot read it.
/// - [`ConfigError::InvalidUtf8`] if the bytes are not valid UTF-8.
///
/// # Panics
///
/// Never. Every failure is reported through the returned `Result`.
pub fn read_config(path: &Path) -> Result<String, ConfigError> {
    todo!()
}
```

`clippy::missing_errors_doc` and `clippy::missing_panics_doc` enforce the first two. Turn both
on for a published crate; see the `rust-lints` skill.

### Link with intra-doc links, not URLs

Write `[`ConfigError::NotFound`]` and let rustdoc resolve it. The link then follows a rename, and
`cargo doc` reports it when the target disappears. A hand-written URL to docs.rs pins a version
and rots silently.

Add `--document-private-items -D warnings` to catch a broken link in CI:

```bash
RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --locked
```

### Doc examples are tests

Every example in a doc comment is compiled and run by `cargo test`. That makes them the one kind
of documentation that cannot drift. Use `?` in them by returning a `Result`, and hide the
scaffolding with a leading `#`:

```text
/// ```
/// # fn main() -> Result<(), Box<dyn std::error::Error>> {
/// let config = mycrate::read_config("app.toml".as_ref())?;
/// assert!(!config.is_empty());
/// # Ok(())
/// # }
/// ```
```

Lines starting with `# ` are compiled but not shown. Use `no_run` for an example that must
compile but must not execute, and `ignore` only when it cannot compile at all — `ignore` hides
the example from the test run entirely, so it is where stale examples accumulate.

## Naming

| Item | Case |
|------|------|
| Functions, variables, modules | `snake_case` |
| Types, traits, enum variants | `PascalCase` |
| Constants and statics | `SCREAMING_SNAKE_CASE` |

- Name a test function after the behavior it proves:
  `fn decoder_rejects_truncated_frame()`. The failure output then reads as a sentence.
- Use no abbreviation in a public API name. An abbreviation in a local binding is fine
  when the context is clear.
- Write a crate name with hyphens in `Cargo.toml` (`protocol-types`), because that is the
  Cargo convention. The module path then uses underscores (`protocol_types`).
- Give the crates of one workspace a single shared prefix, so an import shows at a glance
  whether the item comes from the workspace or from a third party.

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `pub(super)` or `pub(in path)` | Use `pub(crate)`, or restructure the modules |
| Glob re-export from `lib.rs` (`pub use types::*`) | List the items: `pub use types::{Foo, Bar}` |
| `.for_each()` with a side effect | Use a `for` loop |
| `.unwrap()` in non-test code | Use `?` with a proper error type |
| Mutation and computation in one expression | Split into separate statements |
| `mod.rs` for a new top-level module | Use `name.rs` plus a `name/` directory |
| A rarely used item imported at the top of the file | Write the fully qualified path inline |
| A private helper before the public function | Public items first, then private ones |
| `anyhow` in the error type of a library crate | Use `thiserror` for a library error |
| No blank line between import groups | Separate std, external, workspace, and crate |
| `#[path]` on a hand-written module | Use the standard module lookup rules |
| Visibility widened so a test can call the item | Move the test, or keep it in the same file |

---

## Review checklist

Run this list against every file a diff touches.

- [ ] A new module uses `name.rs` plus `name/`, not `mod.rs`.
- [ ] `lib.rs` declares the modules first, then re-exports item by item, with no glob.
- [ ] Every new `pub` item is reachable from `lib.rs` and belongs in the public API.
- [ ] No `pub(super)` and no `pub(in path)`.
- [ ] The items in each file follow the ten-step order.
- [ ] Public items come before private ones inside each group.
- [ ] A type definition comes before its `impl` blocks, and inherent impls come first.
- [ ] The imports are in four groups, separated by blank lines.
- [ ] A caller function is placed before the function it calls.
- [ ] No closure in an iterator chain has a side effect.
- [ ] Business branches use `if`/`else` or `match`, not a chain of early returns.
- [ ] Library errors use `thiserror`; `anyhow` stays out of the library public API.
- [ ] No `.unwrap()` and no `.expect()` outside a test.
- [ ] A crate that needs no `unsafe` carries `#![forbid(unsafe_code)]`.

---

## Related skills

| Skill | Use it for |
|-------|------------|
| `rust-lints` | `clippy.toml`, `rustfmt.toml`, workspace lint tables, `disallowed-methods` |
| `rust-crate-architecture` | Crate splits, dependency direction, and public API surface |
| `rust-discipline` | Signature review, API anti-patterns, and error propagation depth |
| `rust-panic-safety` | Panic policy, unwind safety, and `catch_unwind` |
| `cargo-workflows` | Workspace manifests, features, and build commands |
| `rust-unsafe` | The rules for a crate that cannot use `#![forbid(unsafe_code)]` |
| `ffi-error-progress-cancel` | Error translation across an FFI boundary |
| `rust-tdd` | Test placement and the test-first loop |
