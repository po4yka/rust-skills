# Lint failure triage

Use this file when the gate is red and you must decide what to change. The
default answer is "fix the code". Reach for a config change only when the table
says the config is the defect.

## Triage order

1. Reproduce with the exact CI command, including `--locked`, `--all-targets`
   and `-- -D warnings`. A different command is a different gate.
2. Count the findings and sort them by lint name, not by file.
3. Put every finding in one of three buckets:
   - **Real defect** - fix it now.
   - **Refactor** - the lint is right but the fix is large; slice it, mark each
     site with a scoped suppression plus a `// TODO(<owner>): fix` comment, and
     track the cleanup.
   - **Noise** - the lint cannot be satisfied at this site. Justify a scoped
     `#![expect(..., reason = "...")]`. If a lint is noise across the whole
     workspace, remove the lint from the config and say why.
4. Never weaken an unrelated lint to pay for the one that fired.

## Symptom table

| Symptom | Cause | Fix |
|---------|-------|-----|
| Clippy passes locally, fails in CI | The local command omits `--all-targets`, `-D warnings` or `--locked` | Run the CI command verbatim. Tests, benches and examples are code too. |
| Clippy fires lints you never enabled | The CI toolchain is newer; a clippy release added lints or moved one between groups | Pin the toolchain, then adopt the new lints deliberately through the tightening loop |
| One crate produces no lint output | Its `Cargo.toml` has no `[lints] workspace = true`, or the directory is not a workspace member | Add the inheritance stanza. A directory with no `Cargo.toml` is not a member and no workspace lint reaches it. |
| A crate has its own lint levels | Somebody added per-crate overrides | Move the levels to the workspace root; leave only `[lints] workspace = true` |
| `clippy::multiple_crate_versions` fails (the `cargo` group) | Two major versions of one dependency coexist in the graph | Run `cargo tree --locked --duplicates`. Unify the versions in workspace dependencies, or add a `[patch.crates-io]` entry. Only if neither works, add the crate to `allowed-duplicate-crates` with a comment naming both consumers. |
| Clippy suggests an API newer than your MSRV | `msrv` is not set in `clippy.toml`, or it is stale | Set `msrv` to the real workspace MSRV. Clippy then suppresses suggestions above it. |
| `clippy::doc_markdown` flags a product or proper noun | The noun is not in the ident allow-list | Add it to `doc-valid-idents`. Keep `".."` as the first entry so clippy's own default list survives. |
| `unwrap_used` or `expect_used` fires in test code | The test exemption is missing | Set `allow-unwrap-in-tests` and `allow-expect-in-tests` in `clippy.toml`, or put `#[cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used, reason = "tests assert with unwrap"))]` on the test module. Never relax the workspace level. |
| A lint fires inside macro-expanded code | A proc-macro on the in-crate expansion path produced code you do not control | Add a crate-level `#![expect(lint, reason = "<macro> expands to ...")]` in that crate only. Do not disable the lint for the workspace. |
| `missing_docs` floods a new crate | The crate is new and undocumented | Document the public items. If the crate must land first, add per-item suppressions with a TODO and track them. Do not set `missing_docs = "allow"`. |
| `arithmetic_side_effects` floods numeric code | Unchecked arithmetic everywhere | Convert to `checked_*`, `saturating_*` or `wrapping_*` and make the intent explicit. Where wrapping is genuinely correct, `wrapping_add` documents it and satisfies the lint. |
| `too_many_arguments` fires | A function grew past the threshold | Group the parameters into a struct. Raise `too-many-arguments-threshold` only for a bridge layer whose signature the foreign ABI fixes. |
| `type_complexity` fires | A nested generic type is unreadable, for example `HashMap<K, Arc<Mutex<HashMap<K, V>>>>` | Introduce a type alias or a named struct. Do not raise `type-complexity-threshold`. |
| `unsafe_op_in_unsafe_fn` errors in an FFI crate | The body of an `unsafe fn` relies on the implicit unsafe scope | Wrap each unsafe operation in its own `unsafe { .. }` block with its own `// SAFETY:` comment |
| `undocumented_unsafe_blocks` fires after you split a block | Each new block needs its own comment | Write one `// SAFETY:` per block, stating the invariant that block relies on |
| `improper_ctypes_definitions` fires | A parameter or return type in an `extern "C"` function is not FFI-safe | Use a `#[repr(C)]` type, a raw pointer, or an FFI-safe integer. See `rust-jni` and `uniffi-boundary`. |
| "this lint expectation is unfulfilled" | An `#![expect(...)]` is stale; the violation is gone | Delete the `expect`. This warning is the feature - it is why `expect` beats `allow`. |
| A lint fires only in one feature build | Feature-gated code is not covered by the default build | Run the gate with `--all-features`, and also with default features. Both must pass. |
| `cargo deny check` fails on an advisory | A dependency has a `RUSTSEC-*` advisory | Upgrade the dependency first. If no fixed version exists, add an explicit ignore with a written reason that states why the risk does not apply (for example a build-time-only proc-macro with no runtime exposure). Re-check every ignore on the next dependency bump. |
| `cargo deny check` fails on a license | The license is not in the allow-list | Verify the real license, then either add it to the allow-list deliberately or drop the dependency. Do not switch the allow-list to a deny-list. |
| `cargo deny check` fails on a source | A dependency comes from git or an alternate registry | Prefer a crates.io release. If the git source is required, add that single source with a reason. |
| `cargo fmt --check` fails on a machine that formats fine | `rustfmt.toml` uses an unstable option, and the toolchains differ | Use stable options only |
| The documented lint policy and the manifest disagree | The document was updated ahead of the code, or the code was changed without the document | Make the document describe what is enforced today. Put the target in the escalation ladder, not in the "current" section. |

## Common configuration mistakes

| Mistake | Fix |
|---------|-----|
| Suppressing a lint workspace-wide to avoid fixing code | Fix the violations, or add a per-site `#[expect]` with a reason and a TODO |
| Adding a dependency without running `cargo deny check` | A new dependency can violate license or advisory policy; run the check in the same commit |
| A bare `#[allow(...)]` with no reason | `allow_attributes_without_reason` rejects it; use `#[expect(..., reason = "...")]` |
| Raising a `clippy.toml` threshold to avoid a refactor | Thresholds go down over time, never up |
| `unsafe_code = "forbid"` in the workspace lint table | Set it per crate, so the one crate that owns unsafe can opt out |

## After any config change

Re-run the full gate, then the tests. A lint fix that changes behavior is a
regression with a clean build.

```bash
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo fmt --all -- --check
cargo deny --locked check
cargo nextest run --locked --workspace
```

Then audit what the change left behind:

```bash
rg '#!?\[(allow|expect)\(' --type rust -n
```

Every hit must carry a `reason = "..."`. A hit with a `// TODO(<owner>)` comment
must have a tracked follow-up. A hit with neither is the next thing to fix.
