---
name: rust-lints
description: Use when editing workspace.lints, clippy.toml, or rustfmt.toml, choosing a rustc, clippy, or rustdoc lint level, rolling out a stricter lint, reviewing an allow or expect suppression, or triaging a red clippy, cargo fmt, or cargo doc gate. Triggers on [lints] workspace = true, -D warnings, CARGO_BUILD_WARNINGS, unfulfilled_lint_expectations, allow_attributes, disallowed-methods, and the clippy msrv. Not for deny.toml license, advisory, or ban policy; use rust-security.
license: BSD-3-Clause
---

# Rust lints

A lint rejects a whole class of defect for every author. A written rule ("no unsafe", "no
bare allow") is not enforcement until a lint level or a CI check carries it. Write down only
the level that is actually deployed: a document that shows a target level as the current one
makes reviewers stop checking what the compiler does not check either. Read
[references/triage.md](references/triage.md) when a clippy, `cargo fmt`, or `cargo doc` gate is
red.

## Where lint policy lives

Put every lint level in the workspace root `Cargo.toml`. Every member inherits it:

```toml
[lints]
workspace = true
```

Put no lint levels in a member manifest. A per-crate override is invisible to a reader of the
root policy, and it drifts.

| File | Owns |
|------|------|
| Root `Cargo.toml` | `[workspace.lints.rust]`, `[workspace.lints.clippy]`, `[workspace.lints.rustdoc]`; `rust-version` in `[workspace.package]`, which clippy reads as the MSRV |
| `clippy.toml` (beside the root manifest) | Thresholds, disallowed methods and types, ident allow-lists, test exemptions |
| `rustfmt.toml` | Formatting options |
| `deny.toml` | `cargo deny` policy. The `rust-security` skill owns it. |

A crate attribute overrides the inherited level in both directions. A `#![warn(lint)]` in
`lib.rs` lowers a workspace `deny` to `warn` for that crate (verified on 1.98.1). Only
`forbid` cannot be lowered. Restate an inherited lint in source only at the same or a stricter
level. To relax a lint in one crate, follow the order in [Suppressions](#suppressions).

## Verification

While you iterate, run the crate gate from [Add a crate](#add-a-crate). Before a commit or a
merge, run the workspace gate:

```bash
# --all-features only when the features are additive; see the first bullet below.
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo fmt --all -- --check
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --no-deps --document-private-items --all-features
cargo nextest run --locked --workspace --all-features  # without cargo-nextest: cargo test
cargo test --locked --workspace --all-features --doc   # nextest does not run doctests
cargo deny --config deny.toml --locked check  # when dependencies, Cargo.lock, or deny.toml change
```

What each check proves, and what it does not:

- `--all-features` is correct only when the features are additive. With mutually exclusive
  features, run clippy once per supported feature set, or run
  `cargo hack clippy --each-feature --workspace --all-targets --locked -- -D warnings` when
  cargo-hack is installed. Give `cargo doc` and the tests the same feature sets as clippy. The
  `cargo-workflows` skill owns the feature matrix.
- Clippy does not run rustdoc lints. `[workspace.lints.rustdoc]` and
  `#![deny(rustdoc::broken_intra_doc_links)]` act only under `cargo doc`. On 1.98.1 a broken
  intra-doc link passes clippy and `cargo test --doc`, and fails only `cargo doc`. Without
  `--document-private-items`, rustdoc does not resolve the links in the docs of private items
  (verified on 1.98.1). Without `-D warnings`, `cargo doc` also passes warn-level rustdoc lints
  such as `private_intra_doc_links`.
- A host run does not lint code behind `#[cfg(target_os = "android")]` or another target cfg.
  Run `cargo clippy --locked --workspace --target <triple> --all-targets -- -D warnings` for
  each shipped target after `rustup target add <triple>`. A build script that compiles C also
  needs that target's C toolchain.
- `-- -D warnings` does not deny `linker_messages` (warn by default since 1.97, outside the
  `warnings` group). Clippy does not link, so only `cargo build` or `cargo test` prints linker
  output. The default policy keeps `linker_messages` at `warn`, because linker output changes
  with the host linker. To fail CI on linker output, run the build or test step with
  `CARGO_BUILD_WARNINGS=deny` (1.97+). `linker_messages = "deny"` in `[workspace.lints.rust]`
  also works (verified on 1.98.1), but it fails every local build too. Leave `linker_info` at
  its default `allow`, and pass `-W linker-info` only while you diagnose a link (the
  `rust-native-linking` skill).
- A green gate on one toolchain can go red on the next: a clippy release adds lints to
  `pedantic` and `nursery`. Pin the toolchain, and re-run the gate after each bump.

`CARGO_BUILD_WARNINGS=deny` (or `build.warnings = "deny"` in `.cargo/config.toml`) fails a
local crate that has lint warnings. It does not change `RUSTFLAGS`, so the build cache
survives; add `--keep-going` to see the warnings of every crate. It also fails on
`linker_messages` and on `cargo doc` warnings (both verified on 1.98.1). Cargo older than 1.97
ignores it, and the gate passes silently. Use it only when the pinned toolchain is 1.97 or newer; keep `-- -D warnings` otherwise. Set
`CARGO_BUILD_WARNINGS=deny` in the CI job environment, not in a checked-in `.cargo/config.toml`:
the config key also turns every local warning into an error while a developer iterates. Do not
use `RUSTFLAGS=-Dwarnings`: it rebuilds every dependency and replaces the rustflags from config
files. `RUSTDOCFLAGS` also replaces `build.rustdocflags` from config (verified on 1.98.1); when
the config sets `rustdocflags`, use `CARGO_BUILD_WARNINGS=deny` for the `cargo doc` line
instead.

Audit suppressions after a lint change. Every hit needs `reason = "..."`, and every
`// TODO(<owner>)` needs a tracked follow-up:

```bash
rg '#!?\[(allow|expect)\(' --type rust -n
rg 'cfg_attr\([^)]*(allow|expect)\(' --type rust -n
```

## The `[workspace.lints]` table

Read [references/workspace-lints.md](references/workspace-lints.md) when you create or change
the table. It holds the strict template for a new workspace and the pragmatic baseline for an
existing one with a backlog. Climb from the baseline with
[Add or tighten a lint](#add-or-tighten-a-lint).

Read [references/lint-catalog.md](references/lint-catalog.md) when you must justify a level,
pick lints from `restriction`, add the optional pointer/FFI or async block, or read the
binding-layer rules.

## `clippy.toml`

```toml
# No msrv key. Clippy reads `rust-version` from each member's Cargo.toml; members inherit it
# with `rust-version.workspace = true`. Without it, clippy suggests APIs newer than the MSRV.
# Delete an existing msrv key: when it differs from `rust-version`, clippy warns and uses the
# clippy.toml value (verified on 1.98.1).

# Allow a known duplicate major version instead of letting clippy::multiple_crate_versions
# (the `cargo` group) fail the build. Name both consumers in a comment.
allowed-duplicate-crates = ["bitflags"]

# The default `true` holds back every lint whose fix changes an exported signature. Set
# `false` when no external crate consumes the API. Keep `true` for a crate on crates.io or a
# stable FFI or binding surface.
avoid-breaking-exported-api = false

# Test code may unwrap. Non-test code uses `?`, or `.expect("<invariant>")` for a real
# invariant (the `rust-discipline` skill owns that rule).
allow-unwrap-in-tests = true
allow-expect-in-tests = true
# Add the matching key only for a lint you enabled:
# allow-panic-in-tests            = true
# allow-print-in-tests            = true
# allow-dbg-in-tests              = true
# allow-indexing-slicing-in-tests = true

# Words clippy::doc_markdown must not ask you to backtick. ".." keeps clippy's default list
# (it already has SQLite, WebAssembly, GitHub, iOS, macOS) and appends yours.
doc-valid-idents = ["..", "UniFFI"]

stack-size-threshold         = 4096   # large_stack_frames fires above 4 KiB (default 512000)
future-size-threshold        = 16384  # default; large_futures fires above 16 KiB
enum-variant-size-threshold  = 200    # default; large_enum_variant compares the two largest variants
large-error-threshold        = 128    # default; result_large_err fires when Err reaches it
# large-error-ignored        = ["your_crate::RareBigError"]
type-complexity-threshold    = 250    # default; a higher value is debt
too-many-arguments-threshold = 6      # default 7; skips extern fns, see references/triage.md

# clippy::disallowed_methods turns each entry into a lint. The reason is printed in the
# diagnostic: write it for the person who hits the error.
disallowed-methods = [
  { path = "std::mem::forget",  reason = "use ManuallyDrop and document the Drop semantics" },
  { path = "std::env::set_var", reason = "not thread-safe; set it before threads start" },
  # Does not catch the `<*const T>::read` method.
  # `cast_ptr_alignment` catches the misaligned cast.
  { path = "std::ptr::read",    reason = "use ptr::read_unaligned for byte buffers from I/O or FFI" },
  # Catalog default, not a Rust rule (the `rust-code-style` skill): a `for` loop shows the effect.
  { path = "std::iter::Iterator::for_each", reason = "use a `for` loop for side effects" },
]
```

Run `cargo clippy --locked --workspace --all-targets` after you add a `disallowed-methods` or
`disallowed-types` entry. Clippy matches the resolved function, not a same-named method on
another type. It can ignore a path that it cannot resolve without a warning (`<*const T>::read`
on 1.98.1). Check that the entry fires where you expect.

Keep one `clippy.toml`, beside the root manifest. Clippy reads only the nearest file: a member's
own `clippy.toml` replaces the root file, and every root key, `disallowed-methods` included,
stops applying to that member (verified on 1.98.1).

With `allow-unwrap-in-tests = true`, an `#[expect(clippy::unwrap_used)]` on test code is
unfulfilled, and `-D warnings` fails on it (verified on 1.98.1). Do not add a per-test
suppression that the key already covers. The keys cover only `#[test]` functions and
`#[cfg(test)]` items: not a shared helper module under `tests/`, and not an `examples/` file (see
[Suppressions](#suppressions)).

## `rustfmt.toml`

Use stable options only. A stable toolchain ignores an unstable option with a warning, so the
file formats one way on nightly and another on stable, and `cargo fmt --check` splits the team.

```toml
edition = "2024"
style_edition = "2024"
max_width = 120
use_small_heuristics = "Max"
```

`cargo fmt` takes each crate's edition from `Cargo.toml` and ignores `edition` here. A direct
`rustfmt` call (an editor, a pre-commit hook) reads it. Set `edition` and `style_edition` to the
workspace steady-state edition, so that `cargo fmt` and a direct `rustfmt` sort imports the same
way. Without either key, a direct `rustfmt` call uses style edition 2015. It then sorts
`use a::{u8x, U8}` differently from `cargo fmt` on an edition-2024 crate, and CI fails on files
that look formatted. `edition` alone also sets the style edition; set both so the intent is
explicit. During a staged edition migration, keep both keys at the old edition until the last
crate moves; the `cargo-workflows` skill owns that sequence. Verified on 1.98.1:
stable rustfmt accepts `style_edition` without the unstable-option warning.

## `deny.toml`

`cargo deny --config deny.toml --locked check` is the supply-chain part of the gate. The
`rust-security` skill owns the `deny.toml` policy (licenses, advisories, bans, sources, ignore
review) and the failure triage.

## Crate-level attributes

Put `#![forbid(unsafe_code)]` in every crate that has no hand-written `unsafe`, including a
crate that calls C through a safe wrapper crate. Set it per crate, never in
`[workspace.lints.rust]`: a workspace `forbid` cannot be lowered by the one crate that owns
`unsafe`.

```rust
#![forbid(unsafe_code)]
```

An export attribute is unsafe code. `#[unsafe(no_mangle)]`, `#[unsafe(export_name)]`, and
`#[unsafe(link_section)]` fail `forbid(unsafe_code)` (1.98.1: ``usage of the unsafe
`#[no_mangle]` attribute``). A crate that hand-writes an export therefore owns `unsafe`. An
export that a proc macro generates, such as jni 0.22's `#[jni_mangle]`, passes the lint (verified
on 1.98.1); see [Binding and FFI crates](#binding-and-ffi-crates).

A crate that owns hand-written `unsafe` drops `forbid(unsafe_code)` and restates the unsafe lint
floor at its crate root, so the reader of that crate sees it. The `rust-unsafe` skill owns that
lint list and the SAFETY-comment rules. Keep the number of crates without `forbid(unsafe_code)`
small. That number is your audit surface.

### Binding and FFI crates

rustc and clippy suppress almost every lint on tokens that another crate's proc macro emitted.
Verified on rustc 1.98.1: a proc macro emits an unused variable, an unused `mut`, and a
non-snake-case function into a crate with `#![warn(unused_variables, unused_mut,
non_snake_case)]`, and the build reports nothing. The same source written by hand reports four
warnings. `#![deny(unsafe_op_in_unsafe_fn)]` is silent on a macro-emitted `pub unsafe fn f(p:
*const u8) -> u8 { *p }`, which fails with E0133 when you write it yourself. A `macro_rules!`
defined in the same crate is not exempt.

1. Lints that read an item signature still fire. `clippy::ptr_arg` and
   `clippy::exhaustive_structs` report `this warning originates in the macro`. Handle them with
   a narrow crate-level `#![expect(..., reason = "...")]`, not a workspace change.
2. `#![forbid(unsafe_code)]` is a soundness gate, and the silence removes the guarantee. A crate
   that carries it builds and runs the `unsafe` that a dependency's proc macro injected, and
   `cargo clippy -- -D unsafe_code -D clippy::undocumented_unsafe_blocks` reports nothing.
   Audit the proc-macro dependencies of a binding crate with the `rust-unsafe` skill.

A raw JNI layer can trip `missing_safety_doc` and `not_unsafe_ptr_arg_deref`. Make a raw entry
point non-`pub`: the `no_mangle` export does not need `pub`, and neither lint then fires. Never
suppress `not_unsafe_ptr_arg_deref`: a safe `pub fn` that dereferences a caller's raw pointer lets
safe code cause undefined behavior. Remove `pub` instead. The binding-layer section of
[references/lint-catalog.md](references/lint-catalog.md#binding-layer-lints)
has the details. The `rust-jni` skill owns the entry-point signatures.

## Suppressions

Order of preference:

1. **Fix the code.** A lint that fires is usually right.
2. **`#[expect(lint, reason = "...")]` on the smallest item that covers the violation.** When
   the violation goes away, the stale `expect` warns (`unfulfilled_lint_expectations`), so the
   suppression removes itself. Use the inner form `#![expect(...)]` only for macro-expanded
   code that no item encloses, and for a test-helper module such as `tests/common/mod.rs` or an
   `examples/` file that calls `.unwrap()` (the `rust-discipline` skill owns that policy).
3. **`#[cfg_attr(<cfg>, expect(lint, reason = "..."))]`** when the lint fires only on some
   targets or feature sets. A plain `expect` is unfulfilled on the other builds.
4. **`#[allow(lint, reason = "...")]`** only when no cfg describes where the lint fires.
5. **Never suppress workspace-wide.** A lint that is noise across the whole workspace does not
   belong in the config. Remove it and record why. Do not lower a global level to silence one
   site.

```rust
// Narrow, scoped, justified.
#![expect(
    clippy::exhaustive_structs,
    reason = "the binding macro expands to a pub tag struct that cannot carry #[non_exhaustive]; our own records carry it explicitly"
)]
```

`clippy::allow_attributes` and `clippy::allow_attributes_without_reason` enforce this order.
Verified on 1.98.1: `allow_attributes` fires on an outer `#[allow]` and on
`#[cfg_attr(test, allow(..))]`, but not on an inner `#![allow]`.
`allow_attributes_without_reason` also fires on an `#[expect]` without a reason. Find inner
allows with the audit commands in [Verification](#verification).

To grandfather a backlog, put a per-site `expect` with a `// TODO(<owner>): fix` comment on
each site, and track the cleanup.

## Add a crate

1. Add the crate path to `members` in the root `Cargo.toml`.
2. Add `[lints] workspace = true` and `rust-version.workspace = true` to the crate manifest.
   Add no lint levels there.
3. Add `#![forbid(unsafe_code)]` to `lib.rs` or `main.rs`, unless the crate owns `unsafe`.
4. Run the crate gate: `cargo clippy --locked -p <crate> --all-targets -- -D warnings`.

## Add or tighten a lint

Use this loop for a new lint, a level promotion (`allow` to `warn`, `warn` to `deny`), and a
threshold step.

1. Set the proposed level and run `cargo clippy --locked --workspace --all-targets` to list
   every violation. Do not write a baseline file.
2. Sort the findings by lint name. Put each one in a bucket: real defect, refactor, or noise.
3. Fix the defects. For a refactor too large for one change, add a per-site `expect` with a
   `// TODO(<owner>): fix` comment. For noise, see [Suppressions](#suppressions).
4. Land the source fixes with the policy change or before it. Never weaken an unrelated lint to
   pay for this one.
5. Update the documented policy in the same commit.
6. Run the workspace gate and the tests. A lint fix that changes behavior is a regression with a
   clean build.

### Escalation ladder

| Step | Precondition | Move |
|------|--------------|------|
| Add `unwrap_used` at `warn` | Existing sites carry a per-site `expect`. `allow-unwrap-in-tests` exempts tests. | Every new call site then needs a reason. The `rust-discipline` skill owns the policy. |
| `unwrap_used` `warn` to `deny` in one crate | That crate has zero remaining sites | Add `#![deny(clippy::unwrap_used)]` to that crate. Keep the workspace at `warn` until every crate is clean. |
| Add `expect_used` to one crate | No panic may leave that crate, for example an FFI adapter | Add it per crate, not to the workspace table: a documented `.expect("<invariant>")` is allowed elsewhere. |
| Lower `type-complexity-threshold` or `too-many-arguments-threshold` | The workspace is clean at the current value | Step down. Do not raise it for a bridge layer; [triage](references/triage.md) has the `extern` and `native_method!` cases. |
| Unsafe-documentation lints to `deny` | Every `unsafe` block has a `// SAFETY:` comment | Promote `undocumented_unsafe_blocks` and `multiple_unsafe_ops_per_block`. |

## Related skills

Each applies when it is installed.

- `rust-security`: `deny.toml` policy and `cargo deny` failures.
- `rust-unsafe`: SAFETY comments, unsafe audit surface, proc-macro audit.
- `rust-discipline`: the `unwrap` and `expect` policy behind `unwrap_used`.
- `rust-panic-safety`: the panic lints for a crate on an FFI path (`expect_used`, `panic`).
- `rust-code-style`: the style rules that `rustfmt.toml` and `disallowed-methods` enforce.
- `cargo-workflows`: workspace membership, feature matrix, `Cargo.lock`, CI.
- `rust-hot-path`: the fixes that the performance lints ask for.
- `rust-jni`: JNI entry-point signatures and their lints.
