# AGENTS.md

Context for coding agents that work in **this** repository. This repo holds agent skills about
Rust; it contains no Rust crate and no build system. Do not add one.

## Project overview

`rust-skills` is a public catalog of agent skills for Rust work, distributed through skills.sh
and installed with the vercel-labs `skills` CLI. The content must stay free of private
identifiers.

Layout is flat. One directory per skill:

```text
skills/<name>/SKILL.md          the skill itself, always present
skills/<name>/references/*.md   optional deep material, loaded on demand
README.md                       the catalog table and the routing graph
scripts/validate-skills.py      catalog structure checks (tests: scripts/test_validate_skills.py)
tests/routing-cases.md          phrase -> skill, checked against every description
checks/                         compile-check harness for the rust examples; check.sh runs CI
research/                       primary-source findings and catalog decisions
```

There is no nesting below `skills/<name>/`, apart from `references/`. Do not add scripts,
assets, or index files unless a task asks for them.

## The SKILL.md contract

Each `SKILL.md` starts with YAML frontmatter that follows the Agent Skills specification.
Three keys, and nothing else by default:

```yaml
---
name: rust-unsafe
description: Use when adding or reviewing an unsafe block, a raw-pointer dereference, or a transmute ... Covers E0133, E0793, and unsafe attributes.
license: BSD-3-Clause
---
```

Rules:

- `name` must equal the directory name. Use lowercase letters, digits, and hyphens.
- `description` is one line, 1024 characters maximum. It is the only text an agent reads before
  it decides to open the skill, and some runtimes keep only its start when many skills are
  installed. Start with `Use when` and the task, then put the strongest trigger terms in the
  first sentence. Say what the skill covers in one clause. Prefer categories of user intent over
  keyword lists; keep exact tokens a user pastes (error codes, lint, tool, crate, and API names).
  Aim for 300 to 600 characters. Do not write "you", a capability inventory, or a catch-all such
  as "any Rust change". Add a "not for X" boundary only where a sibling skill is a likely misroute.
- `license` is `BSD-3-Clause` for every skill in this repo.
- Add no other frontmatter key unless a task asks for it.

The body starts at an `# Title` heading directly after the frontmatter.

## Authoring conventions

- Write in ASD-STE100 Simplified Technical English: short sentences, simple present tense,
  active voice, one instruction per sentence.
- Use the imperative for instructions. Write `Run cargo nextest run --no-fail-fast`, not
  `You may want to consider running the tests`.
- Give concrete commands, flags, file names, and thresholds. Generic advice has no value in a
  skill; the agent already knows it. Keep Rust-specific guardrails that prevent a correctness,
  soundness, security, ABI, release, or tooling error, even when a strong model often knows them.
- Remove every project-specific path, crate name, package name, and internal tool name. The
  skills must apply to any Rust workspace.
- Tag every code block with a language: `rust`, `bash`, `toml`, `yaml`, `kotlin`, `swift`,
  `text`.
- Keep `SKILL.md` under 500 lines (the validator enforces it) and near 5,000 tokens. Put gotchas,
  triage tables, verifier commands, and escalation rules first. Move conditional material, long
  examples, and background to `references/<topic>.md`. Link each reference directly from
  `SKILL.md` at the point of need with the condition to read it ("Read `references/x.md` when
  ..."). A reference over 100 lines starts with a short contents list.
- Do not add a "When to use this skill" section. The description does that job, and the body
  loads only after the agent chose the skill.
- Name another skill by its name only ("the `rust-security` skill, when it is installed"). An
  install of one skill has no sibling directories, so a path into another skill is a dead link.
- Give each rule one home in the catalog. Other skills point to the owner in one line.
- State the verifier: which command proves which claim, when to run it, and what a green result
  does not prove. Scale it to the risk. Do not add "double-check" or "verify again" steps.
- Use "never", "always", "must", and severity labels only for a correctness, safety, data-loss,
  or irreversible-release hazard, and give the reason. Mark a team preference as a default.
- Skills run on many models and agents. Do not describe how a model behaves, and do not require
  a harness feature (subagents, plan mode, nightly, a specific test runner) without a fallback.
- Label a dated fact with its version or date ("as of Rust 1.98.1"). Do not write "at time of
  writing". Re-run a measurement before you change its toolchain label.
- Prefer a triage table (symptom, cause, fix) over prose for failure handling.
- Compile any Rust example that is meant to be complete before you commit it. `bash
  checks/check.sh` does this for the whole catalog. A snippet that does not compile teaches the
  wrong thing with full confidence.
- Never write a function with an empty body under a non-unit return type. `fn f() -> Result<T> {
  // implementation }` does not compile; write `todo!()`. This is the single most common defect
  the compile check finds.
- Never define one name twice in a single code block to show a before and an after. Use two
  blocks. One block cannot hold both, and a reader cannot tell which definition is live.
- Tag a fence that must not compile: ```` ```rust,compile_fail ```` for a deliberate error
  demonstration, and name the code when you know it: ```` ```rust,compile_fail,E0499 ````. The
  gate then requires that code, so the block proves what the prose says it proves.
- Tag a portable behavior probe ```` ```rust,run ```` and define `fn main()`. CI first requires
  clean compilation, then builds and runs it on the native host. Keep it on the standard library.
  A run block cannot contain `TODO`, `FIXME`, `todo!()`, or `unimplemented!()`.
- Tag ```` ```rust,ignore ```` only for code no `cargo check` can judge: a build-script
  `include!`, a nightly-only feature, a failure that arrives at monomorphization, or a crate the
  harness cannot hold (the list is in `checks/Cargo.toml`). It is the one way out of the gate,
  and nothing else removes a block from it. Prefer fixing the example.

## How to add a skill

1. Create `skills/<name>/`.

2. Write `skills/<name>/SKILL.md` with the frontmatter above and a body that follows the
   authoring conventions. Add `skills/<name>/references/*.md` only for material that is
   conditional or does not fit in the size budget.

3. Add one row to the catalog table in `README.md`, in the section that matches the subject.
   Link the name to `skills/<name>/SKILL.md`. Add one node to the routing diagram. Every skill
   appears exactly once in both places.

4. Add at least one row to `tests/routing-cases.md`: a phrase a user is likely to type, and the
   new skill. The phrase must appear in the new `description`. A skill with no routing case
   fails validation. The check is a regression lint, not proof that routing works: do not add a
   keyword to a description only to satisfy it.

## How to verify a change locally

One command runs every gate CI runs, on the toolchain `checks/rust-toolchain.toml` pins:

```bash
bash checks/check.sh
```

A green run locally means a green run in CI. The one gate that can be missing is the skills-CLI
discovery step, which needs `npx`; `check.sh` says so out loud when it has to skip it, and CI
always runs it. `check.sh` writes only under `checks/` and a temporary directory, so run and rerun
it without asking.

### 1. Catalog structure

```bash
python3 scripts/validate-skills.py
```

It checks, for every skill:

- frontmatter keys stay inside the Agent Skills spec, and the three required keys are present;
- `name` equals the directory name and uses the allowed character set;
- `description` is one plain line, long enough to state what and when, and under 1024
  characters;
- every frontmatter value survives a real YAML parser unchanged: no `: `, no ` #`, no leading
  indicator character, because the skills CLI and the agent runtimes read the file with one;
- `SKILL.md` is at most 500 lines;
- every Markdown link resolves from the file that holds it and stays inside the skill directory,
  every `references/*.md` code span exists, and no file names a `skills/<name>/` repository path;
- every phrase in `tests/routing-cases.md` still appears in the description it routes to, and
  every skill has at least one routing case;
- the README catalog lists exactly the skills that exist on disk;
- the README Mermaid routing graph names every skill exactly once.

### 2. Compile and behavior-check the examples

`checks/README.md` lists the commands for each phase. Every ` ```rust ` block in `skills/` is
read, and its fence decides what happens to it. An untagged block is type-checked; most are
fragments that name types the prose defines, and the analyzer buckets those and ignores them. A
`rust,run` block must compile cleanly and then run on the native host within ten seconds. The gate
fails on an example that never reached the compiler, a failing run block, a `compile_fail` block
that compiled or missed the code its fence names, or a compile error the analyzer cannot
attribute to an undefined symbol or to the extraction wrapper.

`checks/baseline.txt` is empty and should stay empty. When the gate reports a new suspect, fix
the example. Add a baseline line only for a failure no fence tag can express, with a comment
saying why. Add a crate to `checks/Cargo.toml` when a skill starts using it, or every block that
imports it silently degrades to a fragment. `checks/README.md` has the full description.

`check.sh` then confirms the CLI still discovers the catalog. This lists the skills and installs
nothing:

```bash
npx skills add ./ --list
```

Run it after any frontmatter edit. The CLI and the agent runtimes parse frontmatter with a real
YAML parser: a `: ` in a description once hid a whole skill, and a ` #` cut one in half.
`plain_scalar_problem` in `scripts/validate-skills.py` rejects both, but the CLI is the only
end-to-end proof.

### What `main` enforces

`main` blocks force-pushes and branch deletion, and merged head branches are deleted
automatically. Status checks are not required, so a direct push still lands: CI reports on it,
it does not gate it. Run `bash checks/check.sh` before you push, because nothing else will.

### Do not run `skills remove` inside this repository

`npx skills remove --skill <name>` treats this repository's own `skills/` directory as an
install location and **deletes the source directory**. It does this even when you never ran
`skills add`. The deletion is silent and it is not staged in git, so an uncommitted skill is
lost outright.

Use `npx skills add ./ --list` to inspect the catalog, and `npx skills use ./ --skill <name>`
to read one skill. Neither writes to `skills/`. If you need to test an install and a removal,
do it in a scratch directory, never in a checkout of this repository.

## Pull request conventions

- One skill per pull request where practical. A catalog-wide edit, such as a rename of a shared
  term, may touch many files in one pull request.
- Commit subject: `skill(<name>): <what changed>`, for example
  `skill(rust-unsafe): add Tree Borrows review checklist`. For repository-level files use
  `docs: <what changed>` or `chore: <what changed>`.
- Do not mention Claude, Claude Code, or Anthropic in commit messages or pull request text.
- Do not add `Co-Authored-By` trailers.
- Update the `README.md` catalog row in the same pull request that adds or renames a skill.
