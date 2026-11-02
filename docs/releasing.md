# Releasing

A release is a git tag on `main`. Consumers who pin, pin to it: `gh skill install --pin <tag>`
and `/plugin marketplace add po4yka/rust-skills#<tag>` both resolve the tag. `npx skills add`
ignores tags and always installs `main` HEAD, so a tag protects only the pinned paths.

## When to tag

- Tag every catalog actualization: a pass that re-checks the skills against a new toolchain pin
  or new crate versions, and records its findings in `research/`.
- Tag a security fix as soon as it is on `main`.
- Tag only a commit on `main` whose `CI` run is green for both `Validate catalog` and
  `Compile-check examples`. A tag on a red commit is a release that no gate checked.
- Never move or delete a published tag. A consumer pinned to it would silently receive other
  content. Publish a new patch tag instead.

## Release commit

Make one commit on `main`, `chore: release vX.Y.Z`, that does all of the following:

1. Rename `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`, add an empty
   `## [Unreleased]` above it, and update the compare links at the bottom.
2. Replace the previous tag with `vX.Y.Z` in every pinned install line of `README.md`: the
   `--pin` arguments and the `#vX.Y.Z` marketplace suffix. Run
   `grep -n 'v[0-9]\+\.[0-9]\+\.[0-9]\+' README.md` to find them.
3. Run `bash checks/check.sh`. Push, wait for green CI, then tag that commit:

```bash
git tag -s vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The marketplace entries in `.claude-plugin/marketplace.json` carry no `ref` and no `sha`. Their
source is `"./"`, the repository root, because only a root-relative entry loads the subset of
skill directories that its `skills` list names; a `github` or `url` source with a `ref` loads
every skill under `skills/` for every bundle (measured with Claude Code 2.1.316). The pin is the
marketplace ref that the consumer adds, so the release commit has no manifest field to change.

Codex reads the same file as a legacy-compatible marketplace. There is no
`.claude-plugin/plugin.json`, and each marketplace entry is the whole plugin manifest. Codex
installs an entry only when no root `plugin.json` names a different plugin, so a root manifest
would block all six bundles (measured with Codex 0.166.0). `scripts/validate-skills.py` fails
when the file exists.

## Plugin versioning

Claude Code supports two versioning styles for a plugin, and they exclude each other:

- **Bump `version` on every release.** Consumers stay on their cached copy until the string
  changes. A commit pushed without a bump never reaches them.
- **Never set `version`.** The version is the commit SHA of the installed directory, so every
  commit is a new version, and a consumer who added the marketplace at a tag stays on that tag's
  commit.

This repository uses the second style. No marketplace entry has a `version` field. Do not add
one: a `version` that is set once and not bumped freezes every consumer on that release.

Codex does not use the commit SHA. It installs every entry with the version `local`. For a Git
marketplace, `codex plugin marketplace upgrade` fetches the ref again and updates the installed
plugins in the cache; a marketplace on `--ref <tag>` stays on that tag (measured with Codex
0.166.0 on 2026-11-02). Codex documents no background update, so a consumer on `main` gets a
commit only when they run `upgrade`. A local-path marketplace is different: `upgrade` skips it,
and only a new `codex plugin add` copies the changed files.

A consumer who tracks `main` gets every merged commit, not only tags: in Claude Code with
auto-update on, in the background; in Codex at the next `upgrade`. The tag is the line for
consumers who pin.

## Evaluations before a tag

Run the plugin evaluation before every tag, and again after any change to the default model of
Claude Code or of the evaluation workflow:

```bash
claude plugin eval . --eval-dir evals/plugin --trust-plugin --threshold 0.8 \
  --max-cost-usd 20 --json eval-results.json
```

The `Plugin eval` workflow (`.github/workflows/plugin-eval.yml`) runs the same command on
`workflow_dispatch` with pinned model IDs. Run `evals/routing/run.py` for each provider you can.

Run the outcome evaluation before a tag that changes a skill with an outcome case, and after a
change to a case. It measures the delta between the plugin arm and the no-plugin arm; it has no
pass mark:

```bash
claude plugin eval . --eval-dir evals/outcome --trust-plugin --scaffold \
  --allow-tools Bash Write Edit --concurrency 4 --max-cost-usd 40 --no-publish \
  --json eval-results.json
```

The same workflow runs it when you choose the `outcome` suite.

Record each result in `research/` with the date, the catalog commit, the client version, and the
exact model IDs of the agent and of the judge. `evals/README.md` says what each suite proves.

## Repository settings

The settings that make `main` trustworthy are not in any file, so a pull request cannot change
them. The intended state:

- Branch protection on `main` requires the `Validate catalog` and `Compile-check examples`
  checks, requires a pull request with a review from Code Owners, and allows no direct push,
  force-push, or deletion.
- Commits on `main` must be signed.
- A tag ruleset on `v*` blocks update and deletion, so a published tag cannot move.
- Dependabot opens updates for GitHub Actions and for `checks/Cargo.lock`.
- Private vulnerability reporting is on (see `SECURITY.md`).
