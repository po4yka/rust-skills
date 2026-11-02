# Changelog

All notable changes to the catalog are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The catalog has no API, so a version
names a catalog actualization: a tagged `main` commit whose skills were checked against one
toolchain and one set of crate versions. `docs/releasing.md` says when to tag.

## [Unreleased]

### Added

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

### Changed

- For consumers who track `main`: `.claude-plugin/plugin.json` is gone, and each marketplace
  entry is its whole manifest. Codex installs no bundle while a root manifest names another
  plugin. In Claude Code a skill is now namespaced by its plugin (`rust-skills-testing:rust-tdd`),
  not by `rust-skills:`.
- The toolchain pin moves to Rust 1.99.1, with an audit pass over 32 skills: corrected API
  claims, `compile_fail` tags on drop-check examples, and new triage rows (#6). The harness
  checks examples against criterion 0.8 and parking_lot 0.13, and the skills CLI pin is 1.7.4.
- Tokio 1.53.3 in the harness, and `AsyncFd` registration safety in `rust-async-internals` (#2).
- The README install section leads with a bundle and states what each install path pins.
- The trailing sections of the twelve largest skill bodies move to `references/`.
- Twelve skills state the rule behind a cross-bundle reference in one sentence.

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

[Unreleased]: https://github.com/po4yka/rust-skills/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/po4yka/rust-skills/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/po4yka/rust-skills/releases/tag/v0.1.0
