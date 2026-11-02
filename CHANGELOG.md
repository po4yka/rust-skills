# Changelog

All notable changes to the catalog are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The catalog has no API, so a version
names a catalog actualization: a tagged `main` commit whose skills were checked against one
toolchain and one set of crate versions. `docs/releasing.md` says when to tag.

## [Unreleased]

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
- Tokio 1.53.3 in the harness, and `AsyncFd` registration safety in `rust-async-internals` (#2).
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
