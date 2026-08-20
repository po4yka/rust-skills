---
name: rust-lints
description: Use when you edit workspace lint sections, add a crate, choose a clippy or rustc lint level, review an allow or expect attribute, or debug why clippy, rustfmt, or cargo-deny fails. Covers canonical workspace-level Rust lint configuration in workspace.lints, clippy.toml, rustfmt.toml, and deny.toml, plus safe lint tightening, suppression review, and failure triage.
license: BSD-3-Clause
---

# Rust lints

## Purpose

Lints are the cheapest enforcement layer in a Rust workspace. A lint rejects a
whole class of defect at compile time, for every author, forever. A review
comment rejects one instance, once.

This matters most for machine-generated code. Model-written Rust fails in
repeatable ways: undocumented `unsafe`, `let _ = guard;` that swallows an RAII
handle, unchecked integer arithmetic, `mem::forget` on a resource type, bare
`#[allow(...)]` that hides a violation, oversized stack frames. Every one of
these has a lint. Turn the lint on and the class stops arriving in review.

Use this skill as the reference for the canonical lint set, for how to extend
it, and for how to recover when the gate goes red.

## When to use

- You add a crate to the workspace and must wire lint inheritance.
- You edit `[workspace.lints.*]` or `clippy.toml`.
- You want to promote a lint from `warn` to `deny`, or add a new lint.
- You must decide between fixing a violation and suppressing it.
- Clippy, rustfmt or `cargo deny` fails and you must classify the failure.
- You audit why a defect class reached production without a lint stopping it.

## Lint policy lives at the workspace root

Put every lint level in the workspace root `Cargo.toml`. Every member crate
inherits with two lines:

```toml
[lints]
workspace = true
```

Do not put lint levels in a member crate's `Cargo.toml`. A per-crate override
is invisible to anybody who reads the root policy, and it drifts. When one
crate genuinely needs a weaker level, use a scoped `#![expect(..., reason = "...")]`
in that crate's `lib.rs` instead. See [Suppressions](#suppressions).

### Configuration file map

| File | Owns |
|------|------|
| Workspace root `Cargo.toml` | `[workspace.lints.rust]`, `[workspace.lints.clippy]`, `[workspace.lints.rustdoc]` - lint levels |
| `clippy.toml` (next to the root `Cargo.toml`) | MSRV, thresholds, disallowed methods and types, ident allow-lists |
| `rustfmt.toml` | Formatting rules |
| `deny.toml` | License, advisory, ban and source policy for `cargo deny` |

All four sit beside the workspace root manifest, not inside a member crate.

## The `[workspace.lints]` table

Two templates live in [references/workspace-lints.md](references/workspace-lints.md): the
strict target for a new workspace, and the pragmatic baseline for an existing one with a
backlog. Start from whichever matches the tree you have, and climb with
[Tighten a lint safely](#tighten-a-lint-safely).

Write down the level that is actually deployed. A skill or a README that describes an
aspirational level as if it were enforced is worse than no document: reviewers stop
checking what the compiler is not checking either.

## `clippy.toml` - canonical thresholds and lists

```toml
# Stay on the workspace MSRV. Clippy will not suggest an API above this version.
# Edition 2024 needs at least 1.85.0. Set this to your real MSRV.
msrv = "1.85.0"

# Allow a known duplicate major version rather than let clippy::multiple_crate_versions
# (from the `cargo` group) fail the build. Example: one dependency still pins
# bitflags 1.x while another already uses 2.x. Justify every entry in a comment.
allowed-duplicate-crates = ["bitflags"]

# The default is `true`, which holds back every lint whose fix would change an
# exported signature. Set it to `false` in a workspace with no external
# consumers, so those lints fire. Keep the default `true` when a crate ships a
# stable public API to crates.io, or a stable FFI or binding surface.
avoid-breaking-exported-api = false

# Tests may use unwrap/expect for assertions. Production code may not.
allow-unwrap-in-tests = true
allow-expect-in-tests = true

# The same escape hatch exists for the other test-hostile lints. Add only the
# keys whose lint you actually enabled.
# allow-panic-in-tests           = true
# allow-print-in-tests           = true
# allow-dbg-in-tests             = true
# allow-indexing-slicing-in-tests = true

# Proper nouns that clippy::doc_markdown must not flag as un-backticked code.
# ".." keeps clippy's built-in default list and appends yours.
doc-valid-idents = ["..", "SQLite", "UniFFI", "WebAssembly"]

# Size thresholds. Pair with large_stack_frames / large_futures above.
stack-size-threshold         = 4096   # large_stack_frames fires above 4 KiB
future-size-threshold        = 16384  # large_futures fires above 16 KiB
enum-variant-size-threshold  = 200    # clippy's default; large_enum_variant fires on a DIFFERENCE above it
large-error-threshold        = 128    # clippy's default; result_large_err fires when Err reaches it
# large-error-ignored        = ["your_crate::RareBigError"]  # type allow-list for result_large_err
type-complexity-threshold    = 250    # clippy's own default; treat a higher value as debt
too-many-arguments-threshold = 6      # raise to 8 only for an FFI or JNI bridge layer

# Promote dangerous functions to hard errors through clippy::disallowed_methods.
disallowed-methods = [
  { path = "std::mem::forget",  reason = "use ManuallyDrop and document the Drop semantics" },
  { path = "std::env::set_var", reason = "not thread-safe; set it at process start only" },
  { path = "std::ptr::read",    reason = "use std::ptr::read_unaligned for byte buffers from I/O or FFI" },
]

# Add only in a workspace that runs an async runtime:
# disallowed-types = [
#   { path = "std::sync::Mutex",  reason = "in async modules use the runtime's Mutex" },
#   { path = "std::sync::RwLock", reason = "in async modules use the runtime's RwLock" },
# ]
```

`clippy.toml` owns the checked-in `disallowed-methods` list. Validate every
addition across the whole workspace before you land it.

## `rustfmt.toml`

Use stable options only. A stable toolchain ignores an unstable option and
prints a warning. The file then formats one way on nightly and another way on
stable, so `cargo fmt --check` fails for part of the team and passes for the
rest.

```toml
edition = "2024"
max_width = 120
use_small_heuristics = "Max"
```

## `deny.toml`

`cargo deny` is the supply-chain half of the lint gate. Configure four
sections:

| Section | Policy |
|---------|--------|
| `licenses` | An allow-list, never a deny-list. A typical set: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, 0BSD, Zlib, Unicode-3.0. |
| `advisories` | Deny every advisory. Each exception is an explicit id with a written reason (for example a proc-macro advisory with no runtime exposure). |
| `bans` | `multiple-versions` and `wildcards`. Start at `"warn"`, escalate to `"deny"` after cleanup. |
| `sources` | Allow the crates.io registry only. Add a git source one at a time, with a reason. |

An advisory ignore is a dated decision, not a permanent one. Re-check every
ignore when you bump dependencies.

## Crate-level attributes

Add these to each crate's `lib.rs` or `main.rs`. They raise the floor beyond
what the workspace table can express per crate. The first two blocks are
alternatives. Pick one per crate.

Default for every crate that contains no hand-written `unsafe`. This includes a
crate that reaches a C library through a safe wrapper crate:

```rust
#![forbid(unsafe_code)]
```

Only a crate that owns hand-written `unsafe` (an FFI or binding crate) drops
`forbid(unsafe_code)` and uses this instead:

```rust
#![deny(unsafe_op_in_unsafe_fn)]
#![warn(
    clippy::undocumented_unsafe_blocks,
    clippy::multiple_unsafe_ops_per_block,
)]
```

Rustdoc hygiene, in every crate:

```rust
#![deny(rustdoc::broken_intra_doc_links)]
#![warn(missing_docs)]
```

Keep the count of crates that drop `#![forbid(unsafe_code)]` as small as
possible. That count is the size of your audit surface. See `rust-unsafe`.

### Binding and FFI crates

A binding generator expands in the crate, but rustc and clippy suppress almost
every lint on tokens that another crate's macro produced. On rustc 1.97.0 a
proc macro can emit an unused variable, an unused `mut` and a non-snake-case
function name. A crate that carries `#![warn(unused_variables, unused_mut,
non_snake_case)]` gets zero warnings from that expansion. The identical source
hand-written in the same file gets four. `#![deny(unsafe_op_in_unsafe_fn)]` is
silent the same way on a macro-emitted `pub unsafe fn f(p: *const u8) -> u8
{ *p }`, which hard-errors E0133 when you write it yourself. A `macro_rules!`
defined in the same crate is not exempt. Two consequences:

1. Only a lint that reads an item signature crosses the crate boundary.
   `clippy::ptr_arg` and `clippy::exhaustive_structs` do fire on generated
   items, and report `this warning originates in the macro`. Handle those with
   a narrow crate-level `#![expect(..., reason = "...")]`. Do not turn the lint
   off for the workspace.
2. `#![forbid(unsafe_code)]` is a soundness gate, not a tidiness lint, so the
   silence removes a guarantee rather than some noise. A crate that carries it
   builds, links and runs the `unsafe` a dependency's proc macro injected, and
   `cargo clippy -- -D unsafe_code -D clippy::undocumented_unsafe_blocks`
   reports nothing on it. Audit the proc-macro dependencies of a binding crate.
   `rust-unsafe` owns that procedure.

A JNI layer needs two documented relaxations, because the JNI function
signatures force them: `missing_safety_doc` and `not_unsafe_ptr_arg_deref`.
Scope them to the JNI crate and state the reason. The attribute to copy is in
`references/lint-catalog.md`. See `rust-jni` and `ffi-error-progress-cancel`.

## Suppressions

Order of preference, best first:

1. **Fix the code.** A lint that fires is usually right.
2. **`#[expect(lint, reason = "...")]` on the smallest item that covers the
   violation.** Use the inner form `#![expect(...)]` only when the violation is
   inside macro-expanded code and no item encloses it. `expect` is better than
   `allow`: when the violation is gone, the stale `expect` itself warns, so the
   suppression cleans itself up.
3. **`#[allow(lint, reason = "...")]`**, only where `expect` does not work (a
   conditional or generated site where the lint may not fire in every build).
4. **Never suppress workspace-wide.** If a lint produces false positives across
   the whole workspace, the lint does not belong in the config. Remove it and
   say why. Lowering a global level to silence one site is always wrong.

```rust
// Narrow, scoped, justified.
#![expect(
    clippy::exhaustive_structs,
    reason = "the binding macro expands to a pub tag struct that cannot carry #[non_exhaustive]; our own records carry it explicitly"
)]
```

`allow_attributes` and `allow_attributes_without_reason` enforce this policy
mechanically. They push every author from `allow` towards `expect`, and reject
a suppression with no reason.

Grandfathering an existing backlog is legitimate. Mark each site with a
per-site suppression and a `// TODO(<owner>): fix` comment, then track the
cleanup. Never grandfather by weakening the workspace level.

## Add a new crate

1. Add the crate path to the `members` array under `[workspace]` in the root
   `Cargo.toml`.
2. Add `[lints] workspace = true` to the crate's `Cargo.toml`.
3. Add the crate-level attributes above to `lib.rs` or `main.rs`. Default to
   `#![forbid(unsafe_code)]`.
4. Add no lint levels to the crate manifest.
5. Run the single-crate gate:

   ```bash
   cargo clippy --locked -p <crate> --all-targets -- -D warnings
   ```

6. Run the workspace gate before you push.

## Add a new lint

1. Add the lint to `[workspace.lints.clippy]` or `[workspace.lints.rust]`.
2. Run `cargo clippy --locked --workspace --all-targets` to enumerate every
   violation. Do not write a baseline file.
3. Fix the violations. If there are too many for one patch, add a per-site
   suppression with a `// TODO(<owner>): fix` comment and track the cleanup.
4. Run `cargo nextest run --locked --workspace` to prove the fixes changed no
   behavior.
5. Never suppress the lint workspace-wide to avoid the work.

### Add a disallowed method

```toml
disallowed-methods = [
    { path = "std::iter::Iterator::for_each", reason = "use a `for` loop for side effects" },
    { path = "your::new::method",             reason = "state why it is banned and what to use" },
]
```

The `reason` string is printed in the diagnostic. Write it for the person who
hits the error, not for yourself.

## Tighten a lint safely

Use this loop for every promotion: `allow` to `warn`, `warn` to `deny`, or a
threshold step.

1. Run the proposed level at workspace scope. Do not edit a baseline and do not
   commit anything yet.
2. Classify every finding. Split them into "real defect", "noise", and "needs
   refactor". Estimate the remediation slice.
3. Land the source remediation before or with the policy change. Never weaken
   an unrelated lint to pay for this one.
4. Update the documented policy in the same commit as the actual change, so the
   two never disagree.
5. Run the full gate and the test suite.

### Escalation ladder

| Step | Precondition | Move |
|------|--------------|------|
| `bans.multiple-versions` `warn` to `deny` | `cargo tree --locked --duplicates` is clean. Unify the versions in workspace dependencies or add `[patch.crates-io]` entries. | Flip the level. Flipping first makes the next CI run explode. |
| Add `unwrap_used` and `expect_used` at `warn` | Existing sites are grandfathered per site, not workspace-wide. Tests are exempt through `allow-unwrap-in-tests` or a test-module attribute. | Add both at `warn`. This forces every new call site to justify itself. See `rust-panic-safety`. |
| `unwrap_used` `warn` to `deny` in one crate | That crate has zero remaining sites. | Promote per crate with a scoped attribute; leave the workspace at `warn` until every crate is clean. |
| Lower `type-complexity-threshold` | The workspace is clean at the current value. | Step down. `250` is clippy's default; a higher value is debt. Each step exposes a different tier of smell. |
| Lower `too-many-arguments-threshold` | Same. | Step towards `6`. Keep the higher value only in a bridge layer whose signatures are fixed by the foreign ABI. |
| Unsafe-documentation lints `allow` to `warn` to `deny` | Every existing `unsafe` block carries a `// SAFETY:` comment. | Promote `undocumented_unsafe_blocks` and `multiple_unsafe_ops_per_block`. |

Exempt test code from the panic lints with either the `clippy.toml` keys above
or an attribute on the test module:

```rust
#[cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used, reason = "tests assert with unwrap"))]
mod tests { /* ... */ }
```

## Verification

Run all of it locally before you push. Warnings must be errors in CI.

```bash
# Full clippy gate. --all-targets covers tests, benches and examples.
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings

# From outside the workspace directory, point at the manifest.
cargo clippy --manifest-path <workspace>/Cargo.toml --workspace --all-targets --locked -- -D warnings

# Single crate, fast iteration.
cargo clippy --locked -p <crate> --all-targets -- -D warnings

# Formatting.
cargo fmt --all -- --check

# Supply chain, licenses, advisories.
cargo deny --locked check

# Behavior did not change.
cargo nextest run --locked --workspace

# Audit every existing suppression. Any hit without `reason = "..."` is a violation.
rg '#!?\[(allow|expect)\(' --type rust -n

# The pattern above misses a suppression wrapped in cfg_attr. Check those too.
rg 'cfg_attr\([^)]*(allow|expect)\(' --type rust -n

# Find duplicate dependency versions before you tighten the bans section.
cargo tree --locked --duplicates

# One-off audit: the index sites where an assert! would let the compiler drop a
# bounds check. missing_asserts_for_indexing is in the restriction group, so no
# default and no config in this skill turns it on.
cargo clippy --locked --workspace -- -W clippy::missing_asserts_for_indexing
```

Chain the three gates when you want one exit code:

```bash
cargo clippy --locked --workspace --all-targets -- -D warnings \
  && cargo fmt --all -- --check \
  && cargo deny --locked check
```

## References

- `references/lint-catalog.md` - what defect class each lint catches, plus the
  optional pointer/FFI and async lint blocks.
- `references/triage.md` - symptom-to-cause table for a red lint gate, and the
  configuration mistakes that cause most of them.

## Related skills

- `rust-discipline` - the coding conventions these lints enforce mechanically.
- `rust-unsafe` - `unsafe_op_in_unsafe_fn`, SAFETY comment patterns, audit surface.
- `rust-panic-safety` - the policy behind `unwrap_used`, `expect_used`, `panic`.
- `cargo-workflows` - workspace membership, lint inheritance, edition migration.
- `rust-sanitizers-miri` - lints are static; Miri catches the runtime tail.
- `rust-hot-path` - the fixes the performance lints ask for: `clone_from`,
  boxing a large variant, `impl Iterator` returns, bounds-check removal.
- `rust-async-internals` - how to read the `await_holding_*` lints.
- `rust-security` - the advisory and license policy behind `deny.toml`.
- `rust-code-style` - rustfmt settings and their effect on review diffs.
- `rust-jni`, `uniffi-boundary`, `ffi-error-progress-cancel` - lint relaxations
  a binding layer needs, and their justification.
