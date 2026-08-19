# AGENTS.md

Context for coding agents that work in **this** repository. This repo holds agent skills about
Rust; it contains no Rust crate and no build system. Do not add one.

## Project overview

`rust-skills` is a public catalog of agent skills for Rust work, distributed through skills.sh
and installed with the vercel-labs `skills` CLI. The content is generalized from private
production codebases, so it must stay free of private identifiers.

Layout is flat. One directory per skill:

```
skills/<name>/SKILL.md          the skill itself, always present
skills/<name>/references/*.md   optional deep material, loaded on demand
README.md                       the catalog table
LICENSE                         BSD-3-Clause
```

There is no nesting below `skills/<name>/`, apart from `references/`. Do not add scripts,
assets, or index files unless a task asks for them.

## The SKILL.md contract

Each `SKILL.md` starts with YAML frontmatter that follows the Agent Skills specification.
Three keys, and nothing else by default:

```yaml
---
name: rust-unsafe
description: Use when you add or review any unsafe Rust block ... Triggers on "unsafe", "FFI", "transmute", or any soundness question.
license: BSD-3-Clause
---
```

Rules:

- `name` must equal the directory name. Use lowercase letters, digits, and hyphens.
- `description` is one line, 1024 characters maximum. It must say **what** the skill covers and
  **when** an agent must load it. Start with `Use when ...` and end with the trigger terms that
  a user is likely to type.
- `license` is `BSD-3-Clause` for every skill in this repo.
- Add no other frontmatter key unless a task asks for it.

The body starts at an `# Title` heading directly after the frontmatter.

## Authoring conventions

- Write in ASD-STE100 Simplified Technical English: short sentences, simple present tense,
  active voice, one instruction per sentence.
- Use the imperative for instructions. Write `Run cargo nextest run --no-fail-fast`, not
  `You may want to consider running the tests`.
- Give concrete commands, flags, file names, and thresholds. Generic advice has no value in a
  skill; the agent already knows it.
- Remove every project-specific path, crate name, package name, and internal tool name. The
  skills must apply to any Rust workspace.
- Tag every code block with a language: `rust`, `bash`, `toml`, `yaml`, `kotlin`, `swift`,
  `text`.
- Keep `SKILL.md` near 400 lines. Move tables, long examples, and background to
  `references/<topic>.md`, and link to them from `SKILL.md`.
- Prefer a triage table (symptom, cause, fix) over prose for failure handling.

## How to add a skill

1. Create the directory:

   ```bash
   mkdir -p skills/<name>
   ```

2. Write `skills/<name>/SKILL.md` with the frontmatter above and a body that follows the
   authoring conventions. Add `skills/<name>/references/*.md` only for material that does not
   fit in the 400-line budget.

3. Add one row to the catalog table in `README.md`, in the section that matches the subject.
   Link the name to `skills/<name>/SKILL.md`. Every skill appears exactly once.

## How to verify a change locally

Run the validator from the repository root before you open a pull request. It is the same
script that CI runs, so a green run locally means a green run in CI:

```bash
python3 scripts/validate-skills.py
```

It checks, for every skill:

- frontmatter keys stay inside the Agent Skills spec, and the three required keys are present;
- `name` equals the directory name and uses the allowed character set;
- `description` is one plain line, long enough to state what and when, and under 1024
  characters;
- every `references/*.md` a skill points at exists, whether the pointer is a Markdown link or
  a bare code span;
- no term from the private source codebases survives anywhere in `skills/` or `README.md`;
- the README catalog lists exactly the skills that exist on disk.

Add a term to `FORBIDDEN` in the script the moment one leaks. That is cheaper than finding it
after publication.

Then confirm the CLI still discovers the catalog. This lists the skills and installs nothing:

```bash
npx skills add ./ --list
```

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
