# Security policy

## Scope

This repository ships Markdown only: `skills/<name>/SKILL.md` and `skills/<name>/references/*.md`.
An install copies or symlinks those files into an agent's skill directory (`.claude/`, `.codex/`,
`.cursor/`, and others). No script, binary, test file, or build step ships with a skill. The
harness under `checks/`, `scripts/`, `evals/`, and `.github/` runs only in this repository's CI.

The content is still in scope, because an agent executes it. A skill contains shell commands
(`cargo install`, `cargo`, `rustup`, build and release commands) and Rust examples that an agent
can copy into a workspace and run. Report any of these:

- a command that installs, downloads, or runs something other than what the prose says;
- a crate, tool, or URL that is typosquatted, abandoned, or compromised;
- an instruction that disables a security control (TLS verification, signature or checksum
  checks, `--locked`, sandboxing) without a stated reason and a bound;
- a code example that is unsound or teaches undefined behavior as correct;
- text that tries to direct an agent away from the task it was given (prompt injection);
- a change to `.claude-plugin/` or the install instructions that would install content other
  than this catalog.

Out of scope: a factual Rust error with no security effect (open a normal issue), and the
behavior of the `skills` CLI, `gh skill`, or Claude Code themselves (report those upstream).

## Supported versions

Only the newest tag and `main` receive fixes. Pin a tag to avoid unreviewed changes; the README
install section says which install paths pin and which track `main`.

## Reporting

Use GitHub private vulnerability reporting: the **Report a vulnerability** button on this
repository's **Security** tab. Do not open a public issue for a report in scope. Include the
skill, the file and line, the command or text, and what an agent does when it follows it.

Expect an acknowledgement within 7 days. A confirmed problem is fixed on `main`, released in a
new tag, and recorded in `CHANGELOG.md` with credit unless you ask otherwise.
