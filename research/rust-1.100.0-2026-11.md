# Rust 1.100.0 catalog update

Date: 2026-11-13. Base: `c980ed6` (`main`). Previous compile pin: Rust 1.99.1.
New pin: Rust 1.100.0 (`0ef1bc386`, 2026-11-09). Cargo reports 1.100.0
(`3acc79c0c`, 2026-11-05). Edition 2024 stays unchanged.

## Scope and method

Search the complete catalog, references, repository instructions, scripts, CI,
and evaluation fixtures for release-sensitive claims. Compare them with the
[versioned release notes](https://doc.rust-lang.org/1.100.0/releases.html#version-11000-2026-11-12)
and the [release announcement](https://blog.rust-lang.org/2026/11/12/Rust-1.100.0/).
Compile the examples of all 50 skills on the new pin. Add portable behavior
probes for new API guidance. Do not change dependency versions as part of this
compiler update. `Cargo.lock`, the catalog membership, bundles, and plugin
membership stay unchanged.

This is a release-impact pass, not a repeat of every platform experiment or
performance measurement. Keep historical toolchain labels, MSRV boundaries,
stabilization versions, changelog entries, and earlier research intact.
A successful type check does not repeat an allocation benchmark or a device run.

## Release impact and ownership

| Area | Catalog action |
| --- | --- |
| Never type and `Infallible` | Correct the compiler-error fallback guidance on all editions. Add an infallible-result behavior probe in error handling. Warn about overlapping impls in the upgrade guide. |
| Precise `if let` captures | Add a field-capture probe and lifetime, `Send`, and drop-order checks in callback bounds. |
| Allocators and raw ownership | Add `Box` and `Vec` round-trip probes with the original allocator. Keep the unsafe contract in rust-unsafe and point to it from allocation guidance. |
| `DropGuard` | Remove the unstable claim. Put rollback policy and success/error/unwind probes in panic safety. Update discipline and callback references. |
| `conjure_zst` and `UnsafeCell` | Document inhabitedness, token invariants, allocator identity, and reference exclusivity in rust-unsafe. |
| Cargo lints | Document manifest policy and coverage limits in rust-lints. Point dependency review and upgrade guidance to that owner. |
| Cargo cooldowns | Document opt-in configuration, lockfile behavior, missing `pubtime`, tool-install exclusions, and a reviewed one-command exception in rust-security. |
| Cargo artifact layout and install locks | Use JSON artifact messages. Remove the Android test-path assumption. Explain the changed `cargo install` default without removing older-Cargo flags. |
| WASIp3 and native target changes | Update WASIp3 to Tier 2, show its build, and state host/thread limitations. Document Windows host-tool and unwinder changes; add ARM ABI triage. |
| Layout, inference, and diagnostics | Cover repeated repr attributes, packed alignment, stricter dyn checks, and allocator-related Box inference. Preserve explicit ABI boundaries. |
| Sample PGO | Add the stable sample-profile flag beside the existing instrumented PGO procedure. Do not claim a measured speedup. |
| Collection APIs | Add direct `Cow` slice-comparison probes and known-length `Vec::from_fn` guidance. |
| Repository instructions | Update the pin and badge, add a toolchain-update procedure, and remove instructions that allowed a new baseline exemption. Test three-digit minor-version ordering and claim boundaries. |

Other release entries do not require a new catalog rule: specialized
`extern "custom"` assembly, `Box::take` and pointer `map` helpers, trim helpers,
`bool::toggle`, `Once::default`, and Windows process helpers have no matching
obsolete advice here. Do not recommend them unconditionally to packages with
an older MSRV. Existing iterator guidance still requires a valid `Ord` contract.
The release also changes Unicode data, some target defaults, and compiler
validation. These remain inputs to a consumer's target and behavior tests;
the catalog does not claim platform execution coverage for them.

## Primary API sources

- [Never type](https://doc.rust-lang.org/1.100.0/std/primitive.never.html)
- [Closure capture change](https://github.com/rust-lang/rust/pull/154210)
- [Allocator](https://doc.rust-lang.org/1.100.0/std/alloc/trait.Allocator.html)
- [DropGuard](https://doc.rust-lang.org/1.100.0/core/mem/struct.DropGuard.html)
- [conjure_zst](https://doc.rust-lang.org/1.100.0/core/mem/fn.conjure_zst.html)
- [UnsafeCell](https://doc.rust-lang.org/1.100.0/std/cell/struct.UnsafeCell.html)
- [Cargo lints](https://doc.rust-lang.org/1.100.0/cargo/reference/lints.html)
- [Cargo publish age](https://doc.rust-lang.org/1.100.0/cargo/reference/resolver.html#publish-age)
- [Cargo artifact messages](https://doc.rust-lang.org/1.100.0/cargo/reference/external-tools.html#json-messages)
- [WASIp3 target](https://doc.rust-lang.org/1.100.0/rustc/platform-support/wasm32-wasip3.html)
- [Vec APIs](https://doc.rust-lang.org/1.100.0/std/vec/struct.Vec.html)

The upstream Clippy changelog at the `rust-1.100.0` tag still starts its stable
section at Rust 1.98. It is not used as evidence of a complete 1.100 lint list.
The repository lint gate checks the deployed template against the installed
Clippy instead.

## Validation

`bash checks/check.sh` completed with exit 0 and `All checks passed` in an
x86_64 Linux container based on `rust:1.100.0-slim-trixie`. The environment used
Python 3.13.5, G++ 14.2.0, Node 26.13.1, and npm 11.20.0. Node matches the CI
major version. The official Node archive passed its SHA-256 check.

- All 50 skills pass catalog, link, budget, and routing validation. No body
  exceeds 4,500 estimated tokens.
- The two compile passes cover 565 blocks: 381 of 383 compile blocks build;
  82 run blocks compile and execute; 79 expected-failure blocks fail as tagged.
  The two existing fragments and 21 explicit ignores remain unchanged.
  There are 91 prelude-backed blocks and zero baseline entries.
- All 53 named template lints fire on Clippy 1.100.0.
- All nine outcome cases pass structure and planted-defect checks.
- The skills CLI discovers exactly 50 skills. Both pinned clients load all
  eight plugins. Every bundle keeps every routing phrase visible, including
  the new WASIp3 phrase: 342 of 342 across bundles. The full-catalog install
  shows 248 of 342, the documented shared-budget limitation; it is not the
  recommended routing configuration.
- Unit suites pass. Six optional YAML tests initially skip because PyYAML is
  absent. After installing it in the test container,
  `python3 evals/outcome/test_cross_agent.py` passes all 46 tests with no skips.
- `bash checks/check.sh --fast` also passes on macOS with a fresh npm cache.
  The final WASIp3 routing case passes the separate pinned-client gate.
- `python3 scripts/test_drift_report.py` passes eight tests, including
  three-digit minor-version ordering and dated-claim boundaries.
- `git diff --check` passes. Dependencies and exception lists have no diff.

Additional probes on `aarch64-apple-darwin`:

- The new allocator, rollback, infallible-result, and closure examples compile
  and run on Rust 1.100.0.
- The `if let` field-capture probe fails with E0382 on 1.99.1 and passes on
  1.100.0. Discriminant captures of `Result<u32, Infallible>` still produce
  E0506 for `let`, `match`, and `if let` on both versions.
- The unanchored generic `f()?` example reports E0277 on editions 2015, 2018,
  2021, and 2024. `f::<()>()?` compiles and runs on all four.
- A temporary two-binary package with `unused_dependencies = "deny"` passes
  `cargo check --locked --offline --bin one`, fails with the unused-dependency
  diagnostic under `--all-targets`, and passes after the second binary uses
  the dependency. No suppression or external dependency is needed.
- `rustup target add --toolchain 1.100.0 wasm32-wasip3` succeeds. A hello-world
  component builds with `rustc +1.100.0 --target wasm32-wasip3 --edition=2024`.
  No WASI host execution is claimed.
- `rustc +1.100.0 -C help` lists `profile-sample-use`. No profile application or
  performance result is claimed.
- `python3 scripts/drift-report.py toolchain` reports the 1.100.0 pin current.

Initial macOS full-gate attempts stopped before examples reached rustc: PyO3
needed target Python configuration, then `cxx` needed a Linux C++ sysroot.
Setting `PYO3_CROSS_PYTHON_VERSION` alone was insufficient. Move the full gate
to Linux with Python and a C++ compiler; do not disable those dependencies.
The first macOS npm client attempt lacked its native binary. A fresh cache
and the package installer repaired that environment; the normal client gate
then passed. Debian's Node 20 lacks `fs/promises.glob`, which the skills CLI
uses. The successful full run uses Node 26, as CI does. No check was disabled
to resolve these environment failures.

## Limits and release handoff

A host probe is not Android, iOS, Windows, or WASI runtime acceptance. No new
Miri run, allocation benchmark, cold-build measurement, or production profile
was taken. The package MSRV policy is unchanged. No dependency cooldown is
enabled for consumers by this update.

This change prepares a PR. It does not merge or tag a release. After merge,
follow `docs/releasing.md`: use green `main`, run the required model evaluations,
record their model IDs, and create the release commit and tag separately.
