# Changelog

All notable changes to the catalog are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The catalog has no API, so a version
names a catalog actualization: a tagged `main` commit whose skills were checked against one
toolchain and one set of crate versions. `docs/releasing.md` says when to tag.

## [Unreleased]

## [0.5.0] - 2026-11-13

Update the catalog to Rust 1.100.0 and keep edition 2024. The catalog now contains
51 skills in seven bundles. This release includes the toolchain migration,
practical workflows, and final audit fixes from
[#34](https://github.com/po4yka/rust-skills/pull/34),
[#35](https://github.com/po4yka/rust-skills/pull/35), and
[#36](https://github.com/po4yka/rust-skills/pull/36).

### Added

- `rust-allocators`: per-collection allocator selection, implementation contracts,
  allocation and resize failures, alignment, zero-size allocations, and foreign ownership.
- Permanent regression fixtures for compiler transitions from Rust 1.99.1 to
  1.100.0, Cargo dependency policies and artifact paths, and isolated `cfg(loom)` checks.
- Executable smart-pointer mapping, cancellation rollback, cleanup, lifetime,
  stale-handle, and FFI output probes. The harness now runs 97 behavior probes.
- WASIp3 async clock and file-capability checks, plus recorded sample-PGO replay.
- A Linux container with the Rust toolchains, Node, Python, and C/C++ cross tools
  needed to run the complete checks from macOS and Linux ARM64.

### Changed

- Pin the compile harness to Rust 1.100.0. Update mutants to 0.0.4, loom to 0.7.3,
  and syn to 3.0.10 from [#33](https://github.com/po4yka/rust-skills/issues/33).
- Update Cargo guidance for dependency lints, publish-age policy, install lockfiles,
  and intermediate artifact paths. Document loom's MSRV, atomic methods,
  notification limit, and checkpoint feature.
- Update language and library guidance for never-type fallback, the `Infallible`
  alias, precise `if let` captures, `DropGuard`, allocator APIs, smart-pointer
  mapping, layout, target ABI, and WASIp3 Tier 2 support.
- Require permanent evidence for version-sensitive behavior and Cargo policies.
  Keep historical measurements at the toolchain versions that produced them.
- Export tracked and unignored files for both plugin install gates, so ignored
  build output does not enter temporary plugin caches.
- Update pinned install examples to `v0.5.0`; this tag includes `rust-allocators`.

### Fixed

- Use a scoped callback for borrowed Swift input, require a valid borrowed file
  descriptor at safe API boundaries, and distinguish a `SendZc` result from its
  buffer-release notification.
- Create temporary output files exclusively, keep their handles open, and preserve
  existing final files on cancellation or failure.
- Remove unsupported generic cleanup guarantees. Put fallible flushes in explicit
  close operations and state the limits of the wrapped writer's destructor.
- Correct rules for `try_join!`, reused slot indices, union reads, `Vec` drop order,
  owning builders in loops, cache lifetimes, `non_exhaustive`, and boxed string errors.
- Use `Arc<JavaVM>` for owned handles on jni 0.21. Put each library XCFramework's
  headers and modulemap in a separate module directory.
- Check target coverage independently in both compile passes. Reject absent,
  malformed, or empty evaluation results, execution errors, and empty license values.
- Set offline Cargo in the evaluation runner environment. Remove case-level
  environment overrides that the pinned evaluation client rejects. Run outcome
  tasks in the native macOS sandbox with the complete pinned toolchain. Check
  compilation and test execution first. Reject sandbox and compiler-library
  access failures found inside agent traces.
- Accept equivalent Miri command forms in the plugin grader while retaining
  the required Stacked Borrows merge gate.
- Remove the incomplete clang-only cross-compilation fallback. Correct stale
  catalog counts and the documented state of GitHub protections and private reporting.

The final audit covers 22 findings: 20 code and content fixes, plus corrected
instructions for two live GitHub settings gaps. Enabling branch/tag protections
and private vulnerability reporting remains a separate owner-approved action;
this release does not claim that those settings are enabled. No compile-baseline,
fragment, ignore, or size-ceiling allowance was added.

## [0.4.0] - 2026-11-12

A full audit of the catalog and of the gates that check it. Every skill and every harness script
was read against its claims, and each finding was re-checked on Rust 1.99.1, Miri
nightly-2026-11-09, the crate sources, or a probe before it was fixed: 17 factual errors, about
70 rule and instruction defects, and the smaller corrections. Four new skills bring the catalog
to 50. The `language` bundle splits into `language` and `design`, so every bundle fits the
always-on skill listing. Every SKILL.md body is at or under 4,500 estimated tokens, and
`scripts/catalog-ceilings.toml` is empty: nothing in the catalog is over a limit. The toolchain
pin stays at Rust 1.99.1.

**Plugin users:** `rust-skills-language` now holds 8 skills. Install `rust-skills-design` as well
to keep rust-discipline, rust-code-style, rust-crate-architecture, rust-lints, and rust-cli,
which moved there with the new rust-error-handling.

### Added

- `rust-error-handling` (design): error types in libraries and applications, thiserror enums
  with `#[from]` and `#[source]`, the `Error::source` chain, `anyhow::Context`, dependency
  errors as SemVer, chain printing, stable error codes, and `ExitCode`.
- `rust-pyo3` (ffi): PyO3 0.30 modules on the `Bound` API, attach and detach, `PyErr` and
  `PanicException`, abi3 and free-threaded wheels, and maturin builds.
- `rust-cxx` (ffi): C++ interop with `cxx::bridge`, `UniquePtr`, `CxxString`, `Pin<&mut T>`
  methods, exceptions as `Result`, and cxx-build.
- `rust-cross-compilation` (build): other Linux targets, per-target linkers and `CC_<target>`,
  static musl binaries, cross, cargo-zigbuild glibc floors, Docker builds, and qemu-user tests.
- The `design` bundle and its `rust-skills-design` plugin.
- Gates:
  - a second compile of the examples with `--profile test`, so `#[test]`, `#[cfg(test)]`, and
    `#[tokio::test]` code is type-checked (seven test blocks did not compile and now do);
  - `checks/ignored.txt`, which lists every `rust,ignore` block with its reason;
  - `--ceilings-base`: CI compares `scripts/catalog-ceilings.toml` with the merge base, so an
    added or raised ceiling fails;
  - a fallback check for every code span that names a skill of another bundle, not only the
    "the `x` skill" form;
  - README install commands and the router row order checked against `bundles.toml`, and the
    skills-CLI gate fails on an extra skill as well as a missing one;
  - the validator rejects files other than `SKILL.md` and `references/*.md` in a skill, a
    reference `SKILL.md` does not link, a link to its own file, reference-style and HTML links
    that leave the skill, unknown fence languages and every Rust fence spelling `gen.py` skips,
    and routing rows it cannot parse, shorter than three characters, or claimed by another skill.
- `.github/workflows/client-compat.yml`: every week the plugin install gate runs on the newest
  Claude Code and Codex and opens an issue when a plugin stops loading exactly its skills.
- `bash checks/check.sh --no-clients`, which skips the three `npx` gates.
- An outcome case for the design bundle (`design-error-source-chain`), and routing-eval prompts
  for the four new skills.
- pyo3 0.30, cxx 1, tokio `test-util`, `mutants`, and `hyper` in the compile harness.

### Changed

- Bundles: `language` (8 skills: semantics and compiler errors) and `design` (6 skills: API
  design, error handling, lints, architecture, CLI) replace the 13-skill `language`, which was
  the one bundle over the 5,000-character listing budget. The catalog description total is
  reported, no longer capped; each bundle stays capped.
- Every SKILL.md body is at or under 4,500 estimated tokens, down from up to 7,900. Long
  examples, transcripts, measurements, and platform procedures moved to references with a "Read
  `references/x.md` when" pointer; triage tables, hard rules, and verifiers stayed.
- 251 cross-bundle references now carry the owner's rule with its command or API, or were
  removed where they only repeated a rule stated nearby.
- One home per rule: golden files, fixtures, proptest, and loom in rust-test-tools; Miri in
  rust-sanitizers-miri; temporaries in rust-borrow-semantics; Drop and E0509 split between
  rust-discipline and rust-compiler-errors; Swift isolation in rust-swift-ffi; the
  thiserror-versus-anyhow choice in rust-error-handling; the general cross-compile workflow in
  rust-cross-compilation.
- Toolchain labels move to Rust 1.99.1 only where the claim was re-run on 1.99.1; macOS, device,
  and uninstalled-crate measurements keep their labels. Miri messages are re-measured on
  nightly-2026-11-09.
- `analyze.py` excuses nothing without a listing: the "artifact" and "low" buckets are gone, a
  `compile_fail` fence that names a code fails on any other coded error, and an uncoded
  `compile_fail` block that fails only on an undefined name fails the gate.
- The edit hook reports a validator crash instead of staying silent.
- Client pins: skills 1.8.1, Claude Code 2.1.322, Codex 0.167.2.
- CI: each client gate runs once (`Validate catalog` runs `--fast`, `Compile-check examples` runs
  `--no-clients`); a push to `main` no longer cancels an earlier run; both jobs fetch full
  history for the ceilings comparison; `plugin-eval.yml` reads `CLAUDE_CODE_VERSION` from
  `checks/check.sh` and gives the outcome suite 270 minutes.
- `AGENTS.snippet.md` groups its rows by bundle, so a consumer can delete the rows of a bundle
  they did not install.
- AGENTS.md, README.md, SECURITY.md, `checks/README.md`, and `evals/README.md` state what the
  gates prove, including that the chars/2.5 token estimate has no tokenizer count behind it and
  that branch protection is a repository setting no gate proves.

### Removed

- `rust-panic-safety/references/hosts-hooks-and-tasks.md`,
  `rust-event-loop-state/references/generic-and-dynamic-state.md`, and
  `rust-networking/references/diagnostics.md`; their rules moved to the owning reference or
  SKILL.md.
- Every entry of `scripts/catalog-ceilings.toml`.

### Fixed

- Seventeen factual errors, among them:
  - the hyper-util accept loop in rust-networking left a client that sends nothing connected;
    it now bounds protocol detection;
  - `RUSTFLAGS="--cfg loom"` stops tokio from compiling (rust-test-tools);
  - the strict lint template in rust-lints could never pass (`unreachable_pub` against
    `clippy::redundant_pub_crate`);
  - method lookup: the receiver shape outranks "inherent first" (rust-discipline);
  - the Swift header check rejected `#pragma once` and missed nullability (rust-swift-ffi);
  - `catch (e: Exception)` swallowed `CancellationException` around a `suspend` export
    (ffi-error-progress-cancel);
  - GDB slice conditions, the panic breakpoint, and the LLDB formatter check (rust-debugging);
  - the rpds write cost, the `recursion_limit` crate, `*mut T` variance, `cargo info`,
    `--print target-spec-json`, `cargo rustc --lib`, and runtime-symbol lint levels.
- About seventy rule and instruction defects, among them: publishing from a commit not on the
  remote (rust-crate-release); `Task.detached` for long blocking FFI calls; a refcount pattern
  with no overflow guard (memory-model); dropping `pub` to silence `not_unsafe_ptr_arg_deref`
  instead of `pub unsafe extern fn` with `# Safety`; `buf.slice()` in place of `flip()`
  (uniffi-boundary); `strip = "symbols"` dropping the wasm `target_features` section; the
  XCFramework modulemap collision; blocking `adb logcat`; gates in rust-observability that only
  printed; the unknown-field policy of rust-security against rust-serde.
- Smaller corrections across the catalog: search regexes, grep fallbacks for rg commands,
  version labels, contents lists, and stale pointers.

### Security

- The validator rejects the optional frontmatter keys, so `allowed-tools` cannot pre-approve
  tools for every consumer; invisible and control characters in skill files; marketplace keys
  outside an allowlist; and plugin components (`hooks/`, `.mcp.json`, `commands/`, `agents/`)
  at the repository root, which every plugin with source `"./"` would install.
- Every workflow checkout sets `persist-credentials: false`, and CODEOWNERS covers `tests/`,
  `evals/`, `docs/`, `research/`, the root documents, and the plugin component paths.

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

[Unreleased]: https://github.com/po4yka/rust-skills/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/po4yka/rust-skills/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/po4yka/rust-skills/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/po4yka/rust-skills/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/po4yka/rust-skills/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/po4yka/rust-skills/releases/tag/v0.1.0
