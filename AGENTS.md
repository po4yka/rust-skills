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

Run all three checks from the repository root before you open a pull request.

1. Local install check — confirms that the CLI can read and install the catalog:

   ```bash
   npx skills add ./ --agent claude-code
   ```

2. Leaked-token grep — the private source codebases must leave no trace:

   ```bash
   grep -rniE 'ripdpi|cartory|native/rust|engine/rust' skills/ && echo 'LEAK: fix the hits above' || echo 'clean'
   ```

3. Frontmatter check — name matches the directory, keys are exactly the three allowed ones,
   and the description fits in 1024 characters:

   ```bash
   for f in skills/*/SKILL.md; do
     dir=$(basename "$(dirname "$f")")
     name=$(awk -F': ' '/^name: /{print $2; exit}' "$f")
     keys=$(awk '/^---$/{n++; next} n==1 && /^[a-z_]+:/{sub(/:.*/, ""); print} n==2{exit}' "$f" | sort | tr '\n' ' ')
     len=$(awk '/^description: /{print length($0) - 13; exit}' "$f")
     [ "$name" = "$dir" ] || echo "$f: name '$name' does not match directory '$dir'"
     [ "$keys" = "description license name " ] || echo "$f: unexpected keys: $keys"
     [ "$len" -le 1024 ] || echo "$f: description is $len characters, limit is 1024"
   done
   ```

   The loop prints nothing when the catalog is correct.

## Pull request conventions

- One skill per pull request where practical. A catalog-wide edit, such as a rename of a shared
  term, may touch many files in one pull request.
- Commit subject: `skill(<name>): <what changed>`, for example
  `skill(rust-unsafe): add Tree Borrows review checklist`. For repository-level files use
  `docs: <what changed>` or `chore: <what changed>`.
- Do not mention Claude, Claude Code, or Anthropic in commit messages or pull request text.
- Do not add `Co-Authored-By` trailers.
- Update the `README.md` catalog row in the same pull request that adds or renames a skill.
