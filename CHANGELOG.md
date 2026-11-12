# Changelog

All notable changes to the catalog are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The catalog has no API, so a version
names a catalog actualization: a tagged `main` commit whose skills were checked against one
toolchain and one set of crate versions. `docs/releasing.md` says when to tag.

## [Unreleased]

### Changed (audit P3)

- Bodies moved conditional material to references: 30 skills are smaller, and `memory-model` is
  under the 4,800-token target. New references hold, among others, fuzzing and golden files
  (`rust-test-tools`), FFI stubs (`rust-sanitizers-miri`), vetting steps (`rust-security`), CI and
  nextest config (`cargo-workflows`), global state (`memory-model`), rustc transcripts
  (`rust-send-sync`), and consumer tests (`rust-swift-ffi`).
- Toolchain labels move to Rust 1.99.1 only where the claim was re-run on 1.99.1; macOS, device,
  and uninstalled-crate measurements keep their labels. Version labels for cargo-flamegraph,
  smallvec, wild-linker, proptest, hyper, and serde_json are current as of 2026-11.
- Small corrections across the catalog: the `&Vec` search regex, `extern fn` with no ABI string,
  `nm --demangle` checks, `CARGO_BUILD_WARNINGS=deny` (ignored before Cargo 1.97),
  `avoid-breaking-exported-api = true`, one ban for `mem::forget`, a jq-free crate-edge check,
  the AsyncFn diagnostics, new rustc triage rows (E0310, E0369, E0015, E0599 bounds), a foldhash
  row, and grep fallbacks for rg commands.
- Harness: `gen.py` skips `##` lines inside non-Rust fences; the validator checks the README
  install commands and the router row order against `bundles.toml`; the skills-CLI gate also
  fails on extra skills; an uncoded `compile_fail` block that fails only on an undefined name now
  fails the gate. Client pins: skills 1.8.1, Claude Code 2.1.322, Codex 0.167.2.

### Fixed (audit P2)

About seventy P2 findings across 43 skills, each re-checked before the fix (rustc and clippy
1.99.1, Miri nightly-2026-11-09, crate sources, or a probe). The larger ones:

- Wrong or contradictory rules: the HRTB rule in `rust-discipline` (elided `Fn(&T)` is already
  higher-ranked), a sealed blanket impl that implemented the trait for no type, removing `pub`
  to silence `not_unsafe_ptr_arg_deref` (now `pub unsafe extern fn` with `# Safety`, in
  `rust-lints`, `rust-jni`, `cargo-workflows`), the unknown-field policy of `rust-security`
  against `rust-serde`, `buf.slice()` as a substitute for `flip()` in `uniffi-boundary`, and the
  MSan line in `rust-sanitizers-miri`.
- Unsafe instructions: publishing from a commit not on the remote (`rust-crate-release`),
  `Task.detached` for long blocking FFI calls (now a dedicated `Thread`), a predictable temp
  directory in a `rust-cli` probe, a fake that swallowed unmodelled faults (`rust-tdd`), and a
  refcount pattern with no overflow guard (`memory-model`).
- Commands that failed or proved nothing: blocking `adb logcat`, a `cargo tree` provider check
  that passed without rustls, gates in `rust-observability` that only printed, `sqlx prepare
  --check` without its preconditions, and greps that missed the `.cast::<T>()` form.
- Build and platform: `strip = "debuginfo"` keeps the `target_features` section for wasm-opt,
  the modulemap moves under a module directory, the Android release smoke test sets
  `testBuildType`, and `rust-embedded-no-std` triages `#[panic_handler]`, E0463, and E0152.
- One home per rule: golden files, fixtures, proptest, and loom in `rust-test-tools`; Miri in
  `rust-sanitizers-miri`; temporaries in `rust-borrow-semantics`; Drop and E0509 split between
  `rust-discipline` and `rust-compiler-errors`; Swift isolation in `rust-swift-ffi`; rustflags
  precedence in one `rust-performance` reference. `rust-panic-safety` loses
  `references/hosts-hooks-and-tasks.md`, and `rust-event-loop-state` loses
  `references/generic-and-dynamic-state.md`; their rules moved to the owners.
- Routing: `trybuild`, `E0133`, and SQL injection now route to `rust-macros`, `rust-unsafe`, and
  `rust-database`.
- Harness: the edit hook reports a validator crash, and a `compile_fail` fence that names a code
  fails when the block carries another coded error.

### Fixed

Seventeen factual errors from the catalog audit, each reproduced before the fix:

- `rust-copy-on-write`: the 585x `rpds` write cost is 8x for the `&self -> Self` API (against
  `push_back_mut`) and about 72x for the crate design, not the API shape alone.
- `rust-crate-release`: `cargo info` describes the local member on Cargo 1.92 already; the
  "1.94" floor is gone.
- `rust-swift-ffi`: the header check compiles an `#include` of the header, because the
  main-file form rejects `#pragma once` and skips `-Wnullability-completeness`; the reference
  states what cbindgen 0.29.4 emits.
- `ffi-error-progress-cancel`: rethrow `CancellationException` before `catch (e: Exception)`
  around a `suspend` export.
- `rust-macros`: the recursion limit of the invoking crate applies.
- `rust-iterator-impl`: the `into_iter` search uses `rg -U`, or it misses rustfmt output.
- `rust-variance`: `*mut T` does not make a struct invariant over `'a`; `Box<dyn Fn(&'a T)>`
  breaks the lengthening, not the shortening.
- `rust-test-tools`: `RUSTFLAGS="--cfg loom"` stops tokio from compiling; two fixes.
- `rust-port`, `rust-review`: create or report the missing `Cargo.lock` before `--locked`.
- `rust-networking`: the hyper-util accept loop bounds protocol detection, so a client that
  sends nothing is closed; the test seam covers it.
- `rust-debugging`: GDB 15 needs `set language c` for a slice condition and the full
  `__rustc::rust_panic` name; `type category list` does not prove the LLDB formatters work.
- `rust-lints`: the strict template allows `clippy::redundant_pub_crate`, which contradicts
  `unreachable_pub`; the lint gate skips `allow` entries.
- `rust-discipline`: the receiver shape outranks "inherent first" in method lookup.
- `memory-model`: `--print target-spec-json` needs nightly; stable reads the assembly.
- `rust-unsafe`: `cargo rustc` needs `--lib` on a multi-target package; a wrong runtime-symbol
  type is only a warning (`suspicious_runtime_symbol_definitions`).

### Added

- `.github/workflows/client-compat.yml`: every week, the plugin install gate runs on the newest
  Claude Code and Codex and opens a `client-compat` issue when a plugin stops loading exactly its
  skills. The required gate stays on the versions that `checks/check.sh` pins.
- `bash checks/check.sh --no-clients` skips the three gates that run a client through `npx`.
- `check.sh` compiles the examples a second time with `--profile test`. The first run never
  type-checked a `#[test]` function, a `#[cfg(test)]` module, or a `#[tokio::test]` body; seven
  such blocks in `rust-tdd` and `rust-test-tools` did not compile and now have preludes. The
  harness gains tokio `test-util` and `mutants`.
- `checks/ignored.txt` lists every `rust,ignore` block with its reason; an unlisted one fails.
  Five `rust-unsafe` blocks that `cargo check` can judge lost the tag and are checked.
- `check.sh` compares `scripts/catalog-ceilings.toml` with the merge base of `origin/main`
  (`validate-skills.py --ceilings-base`), so an added or raised ceiling fails CI. A body may
  rise by one fallback sentence per resolved cross-bundle reference.
- The validator rejects: the optional frontmatter keys (`allowed-tools`, `metadata`,
  `compatibility`); invisible and control characters in skill files; an untagged fence, a fence
  language outside the list, and every Rust fence spelling `gen.py` skips; a file in a skill
  other than `SKILL.md` and `references/*.md`; a reference `SKILL.md` does not link; a link to
  its own file; a reference-style or HTML link that leaves the skill; a routing row it cannot
  parse, shorter than three characters, or claimed by another description; a marketplace key
  outside the allowlist; and a plugin component (`hooks/`, `.mcp.json`, `commands/`, `agents/`,
  and others) at the repository root.

### Changed

- `analyze.py` has no "artifact" or "low" bucket. A block that failed only on E0282, a `...`
  placeholder, or a doc comment with no item passed with no listing; it is now a suspect.
- Fourteen leftover "Read [this file](this file) when ..." pointers inside references are
  removed or turned into in-page anchors; four references reachable only through another
  reference are linked from their `SKILL.md`.
- `tests/routing-cases.md`: three rows that another description also claimed now use a phrase
  only the owner claims (`NDK linker setup`, `a lending iterator and E0207`), the `E0499` row is
  gone (`rust-event-loop-state` claims it for dispatch loops), and `rust-crate-architecture`
  states its proc-macro boundary as a `Not for` clause.
- CI: every checkout sets `persist-credentials: false`; a push to `main` no longer cancels an
  earlier run; both CI jobs fetch full history for the ceilings comparison. CODEOWNERS covers
  `tests/`, `evals/`, `docs/`, `research/`, the root documents, and the plugin component paths.
- AGENTS.md, SECURITY.md, README.md, `checks/README.md`, and `evals/README.md` now say what the
  gates prove: the token limit is a target for 43 of 46 bodies, the chars/2.5 ratio is not
  backed by a tokenizer count, branch protection is a repository setting no gate proves, the
  plugin root is the whole repository, the outcome suite has eight cases, and the recorded
  evaluations show no measurable effect on Claude for the plugin suite.

- CI runs each client gate once. `Validate catalog` runs `check.sh --fast` in place of its own
  copy of the client steps, and `Compile-check examples` runs `check.sh --no-clients`. The
  validate job caches `~/.npm`. In CI, `check.sh` fails when `npx` is missing, where a local run
  skips the client gates.
- `plugin-eval.yml` reads `CLAUDE_CODE_VERSION` from `checks/check.sh`, so one line pins
  Claude Code for the install gate and the evaluations.
- README: the `testing` bundle shows 6 skills, and the `0.3.0` entry below names Tokio 1.54.1.
  The validator now fails when a bundle count in the README Install table differs from
  `bundles.toml` (#23).

## [0.3.0] - 2026-11-02

The first catalog that installs as a plugin. One plugin marketplace serves Claude Code and Codex,
with one plugin per install bundle and one for the full catalog, and CI installs every plugin in
both clients. The toolchain pin moves to Rust 1.99.1 after an audit pass, and the new
`rust-port` and `rust-review` skills bring the catalog to 46 skills. `evals/outcome/` now measures what an agent
produces with the catalog and without it, in both clients; the first baseline is in
`research/outcome-baseline-2026-11.md`. The plugin evaluation of this release loaded the owning
skill in 12 of 12 runs (`research/plugin-eval-2026-11.md`).

### Added

- README: how to keep the plugins up to date. Claude Code: a marketplace with no ref and
  **Enable auto-update**. Codex: `codex plugin marketplace upgrade`. Both: committed team
  settings (`.claude/settings.json` with `extraKnownMarketplaces` and `autoUpdate`,
  `.codex/config.toml` with `[marketplaces]` and `[plugins]`).
- Fast feedback for agents that edit this repository: `bash checks/check.sh --fast` skips the
  cargo gates, and a post-edit hook for Claude Code (`.claude/settings.json`) and Codex
  (`.codex/hooks.json`) runs `scripts/validate-skills.py` after an edit to a catalog file and
  gives its problems to the agent.
- Install bundles in `bundles.toml`: six subject groups that each install as one unit. Five fit
  the always-on skill listing of a 200K-context client; `language` is over that budget and is
  held by the ratchet.
- A Claude Code plugin marketplace with one plugin per bundle plus the full catalog, pinned by
  adding the marketplace at a release tag.
- `AGENTS.snippet.md`, a 60-line symptom-to-skill router for a consuming repository's
  always-on instructions.
- Validator rules: bundle membership, a description budget per bundle and in total, a body token
  cap, router coverage, cross-bundle references without a fallback, and negative routing cases.
  Values over a limit are held in `scripts/catalog-ceilings.toml` and may only shrink.
- A reproducible routing evaluation in `evals/routing/` and a `claude plugin eval` suite in
  `evals/plugin/`.
- An outcome evaluation in `evals/outcome/`: six `claude plugin eval` cases, one per bundle, each
  a std-only crate with one planted defect that one skill owns. The suite scores the work and the
  evidence in both arms. `evals/outcome/check.py` builds every fixture offline in `check.sh` and
  requires each probe to fail on the fixture and pass on a reference fix, so a fixture cannot
  lose its defect silently. The `Plugin eval` workflow runs either suite.
- Weekly toolchain-drift and crate-drift workflows that open an issue.
- `SECURITY.md`, `CODEOWNERS`, a pull request template, and a misroute issue form.
- Plugin gates: the validator checks `.claude-plugin/marketplace.json` against `bundles.toml`
  (entries, skill lists, skill counts, root source, license, no `version`, no root
  `plugin.json`), and
  `checks/plugin_install.py` installs every plugin with the pinned Claude Code CLI and compares
  what it loads with its bundle. Both run in `checks/check.sh` and in CI.
- Codex support: Codex 0.166.0 installs the full catalog and every bundle from the same
  marketplace (`codex plugin marketplace add po4yka/rust-skills`). `checks/plugin_install.py
  --codex` checks that each plugin puts exactly its skills in front of the model, in
  `checks/check.sh` and in CI.
- A Codex visibility gate: in a fresh Codex install, every bundle plugin must show every routing
  phrase of `tests/routing-cases.md` after Codex shortens the descriptions to fit its skill-list
  budget. The gate isolates `HOME` as well as `CODEX_HOME`, because Codex also lists the skills
  under `~/.agents/skills`, and it fails when any other skill shares the list.
- `rust-port`, in the testing bundle: port C, C++, Python, Go, or JavaScript to Rust with no
  change in output. It has a triage table of 12 traps that change output, a `rust,run` probe of
  its Rust-side claims, and an outcome case (#18).
- Compile-gate preludes: `checks/preludes/<skill>.toml` supplies the names that the prose
  defines, so rustc checks a fragment block too. `analyze.py --check-fragments` fails on a
  fragment that `checks/fragments.txt` does not list, and that file drops from 80 entries to
  2 (#8).
- A cross-agent outcome runner, `evals/outcome/cross_agent.py`: the outcome cases on Claude Code
  and Codex, each with and without the catalog, from isolated login homes, scored by one blind
  judge (#14). `grade --regrade` judges changed graders again on the recorded runs (#16).
- `rust-review`, in the testing bundle: the method and the report of a code review. It orders
  the areas by risk and names the skill that owns each rule, sorts findings into Must fix,
  Should fix, and Consider, and gives each finding a location, a rule, and a fix. It has an
  outcome case (#20, `research/review-and-routing-2026-11.md`).
- `rust-discipline/references/api-conventions.md`: the naming and trait conventions of the Rust
  API Guidelines (`C-CONV`, `C-GETTER`, `C-CTOR`, and others), each with the clippy lint or the
  search that finds a violation (#20).
- A lint gate, `checks/lint_gate.py`: each of the 54 lints that the strict template of
  `rust-lints` names must fire on its marked line of `checks/lints/violations.rs`, and no name
  may be unknown or removed. `check.sh` runs it (#20).
- Routing without an API key: `evals/routing/run.py --provider claude-cli` and
  `--provider codex-cli` run on a subscription login (#20).
- Issue forms "Propose a rule" and "Review false positive" (#20).

### Changed

- For consumers who track `main`: `.claude-plugin/plugin.json` is gone, and each marketplace
  entry is its whole manifest. Codex installs no bundle while a root manifest names another
  plugin. In Claude Code a skill is now namespaced by its plugin (`rust-skills-testing:rust-tdd`),
  not by `rust-skills:`.
- The toolchain pin moves to Rust 1.99.1, with an audit pass over 32 skills: corrected API
  claims, `compile_fail` tags on drop-check examples, and new triage rows (#3, #4, #6). The harness
  checks examples against criterion 0.8 and parking_lot 0.13, and the skills CLI pin is 1.7.4.
- Tokio 1.54.1 in the harness (#2, #4), and `AsyncFd` registration safety in `rust-async-internals` (#2).
- The README install section leads with a bundle and states what each install path pins.
- The trailing sections of the twelve largest skill bodies move to `references/`.
- Twelve skills state the rule behind a cross-bundle reference in one sentence.
- Four descriptions lead with the symptom a user sees: `rust-swift-ffi`, `rust-copy-on-write`,
  `rust-hot-path`, and `rust-borrow-semantics`. A profiled allocation of input that most calls
  return unchanged now routes to `rust-copy-on-write` (#17, `research/routing-fix-2026-11.md`).
- Three outcome graders now score what their case asks, and the baseline is re-graded on the
  recorded runs (#16).
- `rust-lints`: the strict template drops `inefficient_to_string`, which cannot fire in an
  edition 2024 crate, and notes that `unwrap_in_result` checks a `Result` only. When
  `cargo fmt --check` fails before a change, format only the changed files and run the tests
  again (#20).
- Ten descriptions are shorter, so that `rust-review` fits the description budget. Every routing
  phrase and every rustc code stays (#20).
- README: a "What the skills change" section with the measured results (#20).

### Fixed

- The `Plugin eval` workflow loads the plugin again. After `.claude-plugin/plugin.json` was
  removed for Codex, `claude plugin eval .` found no plugin and scored the model alone. The
  workflow now writes the manifest in its own checkout and fails when a result names no plugin.

## [0.2.0] - 2026-09-25

The 2026-09 catalog actualization, recorded in `research/catalog-actualization-2026-09.md`. Every
skill was re-checked against Rust 1.98.1 (up from 1.97.1) and current primary sources, with one
`skill(<name>)` commit per skill. Descriptions were rewritten to lead with the strongest trigger
terms and shrank from 28,561 to 22,253 characters in total, with a blind routing evaluation
showing no regression. Conditional material moved from `SKILL.md` bodies into `references/`, and
the validator started to enforce the 500-line body limit and links that stay inside the skill
directory. The README symptom table and catalog were aligned with the new boundaries.

## [0.1.0] - 2026-08-20

The first tagged catalog: 44 skills for Rust language semantics, unsafe code, async, FFI,
mobile builds, native linking, releases, and supply chain, compile-checked on Rust 1.97.1 with
edition 2024. It grew from 21 initial skills and added production policy skills for networking,
databases, observability, WebAssembly, embedded `no_std`, command-line tools, Windows linking, and
binary releases. The harness came with it: frontmatter and link validation, the routing corpus in
`tests/routing-cases.md`, and a gate that type-checks every `rust` block, requires
`compile_fail` blocks to fail with their named code, and runs `rust,run` probes.

[Unreleased]: https://github.com/po4yka/rust-skills/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/po4yka/rust-skills/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/po4yka/rust-skills/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/po4yka/rust-skills/releases/tag/v0.1.0
