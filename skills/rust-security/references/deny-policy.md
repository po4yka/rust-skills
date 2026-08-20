# cargo-deny Policy Reference

This reference explains the `deny.toml` sections that matter for supply chain
policy, and the choices you must make in each. Place `deny.toml` next to the
workspace `Cargo.toml`, or pass `--config` explicitly.

Validate every edit locally before you push:

```bash
cargo deny --locked --manifest-path path/to/Cargo.toml check
```

## `[advisories]`

Controls RUSTSEC advisory enforcement.

| Field | Recommended value | Why |
|---|---|---|
| `yanked` | `"deny"` | A yanked version is a version the publisher withdrew. Treat it as broken. |
| `unsound` | `"all"` | Fail on unsoundness in direct and transitive dependencies. The default `"workspace"` scope checks direct dependencies only. |
| `ignore` | Empty by default | Every entry is a time-boxed exemption, not a policy. |

Vulnerability advisories are errors. Set `unsound = "all"` explicitly. The
default scope is `"workspace"`, which does not fail on an unsound advisory that
reaches the workspace only through a transitive dependency. See the current
[cargo-deny advisory configuration](https://embarkstudios.github.io/cargo-deny/checks/advisories/cfg.html).

```toml
[advisories]
yanked = "deny"
unsound = "all"
ignore = [
    # Tracking: https://example.invalid/issues/42 - re-evaluate by 2026-06-01
    { id = "RUSTSEC-0000-0000", reason = "proc-macro only, compile-time, no runtime code path; no upstream fix published" },
]
```

Rules for an `ignore` entry:

- Give the `id` and a `reason`. The reason must explain why the advisory is
  safe to ignore in *this* workspace, not why the advisory is low severity in
  general.
- Add a tracking issue link and a re-evaluation date in a trailing comment.
- Apply the SLA from the main skill: 90 days for low or informational, 30 days
  for medium, 7 days for high or critical. A high-severity ignore should not
  exist.
- Remove the entry in the same change that upgrades the dependency which pulls
  the advisory in.
- Re-read the whole list on every dependency bump.

An advisory that reaches only a compile-time path, such as a proc-macro crate
flagged as `unmaintained`, is the standard valid case for a low-severity
ignore. An advisory in a crate that touches untrusted input at runtime is not.

## `[licenses]`

Controls which SPDX licenses may appear in the dependency graph.

```toml
[licenses]
confidence-threshold = 0.8
allow = [
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "0BSD",
    "Zlib",
    "Unicode-3.0",
    "CDLA-Permissive-2.0",
]

[licenses.private]
ignore = true
```

Field notes:

- `confidence-threshold = 0.8` is the working default. A lower value accepts
  weaker license-text matches. A higher value produces more manual review.
- `allow` is a graph-minimal allowlist. List only the licenses your current
  graph actually needs. An allowlist that lists licenses no dependency uses
  hides the moment a new license enters the tree.
- `licenses.private.ignore = true` skips workspace packages whose manifests
  declare `publish = false`. Third-party dependencies stay subject to the
  allowlist. This is the correct setting for a workspace of unpublished
  internal crates.

Licenses that need an explicit decision before you add them:

| License | Consideration |
|---|---|
| `Apache-2.0 WITH LLVM-exception` | Common in compiler-adjacent and codegen crates. Add when the graph needs it. |
| `MPL-2.0` | Weak, file-level copyleft. Acceptable in many products, but record the decision. Some binding-generator crate families require it. |
| `OpenSSL` | Add only when a TLS or crypto dependency needs it, and only after a license review. |

Never widen the allowlist to clear one failing crate without a recorded license
review. Find the crate first:

```bash
cargo tree --locked -i <crate>
```

## `[bans]`

Controls duplicate versions, wildcard requirements, and named crate bans.

```toml
[bans]
multiple-versions = "deny"
wildcards = "deny"
highlight = "all"
skip = [
    # Tracking: https://example.invalid/issues/57
    # <crate-a> 1.x pins this; <crate-b> 2.x has moved on. Unifiable after the
    # <crate-a> 2.0 release.
    { name = "some-transitive-crate", version = "=0.4.9" },
]
```

Policy choice, `multiple-versions`:

| Value | Effect | Choose when |
|---|---|---|
| `"warn"` | Duplicates are reported, not blocking | The graph is large and duplicate churn is not yet under control. Accept that duplicates accumulate. |
| `"deny"` with exact-version `skip` entries | Every duplicate is either fixed or explicitly justified | You want any *new* duplicate to block. This is the stronger position. |

Prefer `"deny"` plus reviewed `skip` entries. With `"warn"`, a new duplicate
looks exactly like the twenty existing ones and nobody sees it. With `"deny"`,
each `skip` entry records which crates disagree and when the split can be
resolved.

Pin `skip` entries to an exact version (`version = "=0.4.9"`). A range-based
skip silently covers future versions you never reviewed.

`wildcards = "deny"` blocks `version = "*"` requirements. A wildcard requirement
means any future release, including a compromised one, satisfies your manifest.

`highlight = "all"` makes the duplicate report show every path in the graph, so
you can see which dependency causes the split.

Use `allow` and `deny` lists to name crates explicitly when you must forbid a
specific crate or restrict a category to a known set. Explicit lists express
policy more precisely than duplicate detection alone.

## `[sources]`

Controls where crates may come from.

```toml
[sources]
unknown-registry = "deny"
unknown-git = "warn"
allow-registry = ["https://github.com/rust-lang/crates.io-index"]
```

- `unknown-registry = "deny"` blocks any registry that `allow-registry` does not
  list. Keep this at `"deny"`.
- `unknown-git = "warn"` reports git dependencies from unlisted remotes. Raise
  it to `"deny"` and use `allow-git` once the graph has no unreviewed git
  sources.
- Pin every git dependency to a `rev`, not a branch or a tag. A branch pin is
  unpinned code execution. A tag can be moved.

A `sources` failure often means an accidental `[patch]` section, a local `path`
override that leaked into a commit, or a git dependency that a transitive crate
introduced. Check the manifests before you change policy.

## Policy change checklist

Before you commit a `deny.toml` change:

1. Run `cargo deny --locked --manifest-path path/to/Cargo.toml check` and read
   the full output, not only the exit code.
2. Confirm every new `ignore` entry has an `id`, a `reason`, a tracking link,
   and a re-evaluation date.
3. Confirm every new `skip` entry has an exact version and a causal reason.
4. Confirm no allowlist got wider without a recorded review.
5. Confirm the CI job pins the same `cargo-deny` version you ran locally. A
   version mismatch between local and CI produces failures you cannot
   reproduce.
