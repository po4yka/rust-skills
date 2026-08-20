---
name: rust-security
description: Use when you audit Rust dependencies with cargo-audit, configure or change a cargo-deny policy in deny.toml, triage a RUSTSEC advisory, evaluate a new crate for typosquat and supply-chain risk before you add it to Cargo.toml, respond to a published CVE on a pinned dependency, decide whether an advisory ignore entry is acceptable, or harden a Rust parser that reads untrusted files. Do not use for ordinary authentication, secret storage, cryptographic design, key lifecycle, payments, or network TLS policy. Triggers on "cargo audit", "cargo deny", "deny.toml", "RUSTSEC", "advisory", "supply chain", "typosquat", "malicious crate", "yanked", new-dependency-addition reviews, and archive, backup, or binary-format parser hardening.
license: BSD-3-Clause
---

# Rust Dependency and Parser Security

## Purpose

Use this skill for Rust supply chain security and untrusted-input hardening. It
covers vulnerability scanning with `cargo-audit`, policy enforcement with
`cargo-deny`, RUSTSEC advisory triage, new-crate risk evaluation, and parser
hardening for files that come from outside your trust boundary.

For memory-safety validation, see the `rust-sanitizers-miri` skill. For unsafe
code audits, see the `rust-unsafe` skill. For lockfile and workspace mechanics,
see the `cargo-workflows` skill.

## Scope and routing

| Request | Route |
|---|---|
| Dependency advisories, dependency vetting, registry policy, or supply-chain risk | Use this skill. |
| Untrusted file, archive, backup, or binary-format parsing | Use this skill. |
| Unsafe-code soundness or runtime memory-safety validation | Use `rust-unsafe` or `rust-sanitizers-miri`. |
| Network TLS transport policy | Use `rust-networking`. |
| Ordinary authentication or authorization, secret storage, cryptographic protocol design, key lifecycle, or payments | Do not use this skill. Follow the applicable domain policy and security review process. |

## Triggers

- "How do I check my Rust dependencies for CVEs?"
- "How do I use cargo-audit or cargo-deny?"
- "How do I enforce dependency policy in CI?"
- "What is the RUSTSEC advisory database?"
- "A dependency has a security advisory. What do I do?"
- "Is it safe to add this crate?"
- "Is it safe to parse this file from user input?"
- "How do I validate an archive or backup file before import?"

## Orientation

Before you change anything, collect these facts about the workspace:

1. The workspace manifest path. Every command below takes
   `--manifest-path <workspace>/Cargo.toml` when you do not run it from the
   workspace root.
2. The policy config path. `cargo-deny` reads `deny.toml` next to the manifest
   unless you pass `--config`.
3. The package count and the dependency graph:
   `cargo metadata --locked --no-deps` for workspace members, `cargo tree
   --locked` for the full graph.
4. The CI job that runs the policy check, and the exact tool version it pins.
   Read the pin. Do not assume it.

Use `--locked` in every command that resolves dependencies. `--locked` fails
when `Cargo.lock` does not match the manifests. Without it, an audit can pass
against a lockfile that CI never builds.

## 1. cargo-audit: vulnerability scanning

`cargo-audit` compares your `Cargo.lock` against the RUSTSEC advisory database.
It reports vulnerabilities only. It does not enforce license or source policy.

```bash
# Install
cargo install cargo-audit --locked

# Scan the current project
cargo audit

# Strict mode: treat warnings as errors (use this in CI)
cargo audit --deny warnings

# Audit a specific lockfile
cargo audit --file path/to/Cargo.lock

# JSON output for scripting
cargo audit --json | jq '.vulnerabilities.list[].advisory.id'
```

Output format:

```text
error[RUSTSEC-2023-0052]: Vulnerability in `some-crate`
    Severity: low
       Title: Integer overflow in offset arithmetic
    Solution: upgrade to `>= 1.2.0`
```

## 2. cargo-deny: policy enforcement

`cargo-deny` does more than `cargo-audit`. It enforces license policy, bans
named crates, checks source registries, and reports duplicate dependency
versions. Run it as the blocking gate. Run `cargo-audit` when you want a fast
advisory-only check.

```bash
# Run all checks against the project config
cargo deny --locked --manifest-path path/to/Cargo.toml check

# Run one check at a time
cargo deny --locked --manifest-path path/to/Cargo.toml check advisories
cargo deny --locked --manifest-path path/to/Cargo.toml check licenses
cargo deny --locked --manifest-path path/to/Cargo.toml check bans
cargo deny --locked --manifest-path path/to/Cargo.toml check sources
```

Run the full command locally before you push a change to `deny.toml`. A policy
change that only CI validates costs a full pipeline round trip per typo.

Pin an exact `cargo-deny` version in CI, and read that pin before you reproduce
a failure locally. A newer minor version can add checks that fail a build that
passed the day before.

Name crates and sources explicitly where policy needs it. `[bans]` takes
`allow = [...]` and `deny = [...]` lists of crate names. `[sources]` takes
`allow-registry` and `allow-git` lists of URLs. Do not rely only on
multiple-version detection.

For the annotated `deny.toml` reference, the meaning of each field, and the
policy choices that matter, see [references/deny-policy.md](references/deny-policy.md).

## 3. RUSTSEC advisory database

The RUSTSEC database at <https://rustsec.org/> tracks vulnerabilities,
unmaintained crates, and unsound code.

```bash
# Sync and browse the local advisory DB
cargo audit fetch
ls ~/.cargo/advisory-db/crates/

# View one advisory on the web
# https://rustsec.org/advisories/RUSTSEC-2023-0001.html
```

Advisory categories:

| Category | Meaning | Typical response |
|---|---|---|
| `vulnerability` | Exploitable security bug | Upgrade. Patch or pin if no upgrade exists. |
| `unmaintained` | Upstream no longer maintains the crate | Plan a replacement. Time-box an ignore entry. |
| `unsound` | Documented unsoundness in a safe API | Check whether your code reaches the unsound path. |
| `yanked` | The version was pulled from crates.io | Move off the yanked version. Set `yanked = "deny"`. |

## 4. Respond to a new advisory

```bash
# 1. Identify the affected crate and version
cargo audit 2>&1 | grep -A3 'RUSTSEC-'

# 2. Check whether an upgrade exists
cargo update -p <crate_name> --dry-run

# 3. Apply the upgrade
cargo update -p <crate_name>

# 4. If no fix exists, assess the advisory and consider a deny.toml ignore
#    entry. Add it only with a reason and a tracking issue. Example:
#    ignore = [
#        { id = "RUSTSEC-0000-0000", reason = "proc-macro only, no runtime code path, tracking #42" },
#    ]

# 5. Verify
cargo deny --locked --manifest-path path/to/Cargo.toml check advisories
```

Prefer an upgrade over an ignore entry. Prefer a pin or a vendored patch over a
permanent ignore entry. Add an ignore entry only when no fix exists upstream.

### RUSTSEC triage SLA

An advisory ID in the `[advisories].ignore` list is a time-boxed commitment. It
is not a permanent exemption.

| Severity | SLA before the ignore becomes blocking |
|---|---|
| Low or informational (unmaintained, no runtime exploit) | 90 days |
| Medium (the exploit needs conditions your build does not meet) | 30 days |
| High or critical | 7 days. No ignore should exist. Patch or pin. |

Every `ignore` entry must carry:

- `id`: the RUSTSEC ID.
- `reason`: one sentence that explains why the advisory is safe to ignore in
  this specific workspace. "Not exploitable" alone is not a reason.
- A tracking issue link in a trailing comment.

A proc-macro crate that is flagged as unmaintained is a valid low-severity
ignore. The crate runs at compile time only. It has no runtime code path. It
still needs a tracking issue. Remove the entry in the same change that upgrades
the dependency that pulls it in.

Review the whole ignore list on every dependency bump. An ignore that outlives
its SLA is a policy failure, not a backlog item.

## 5. Evaluate a new crate before you add it

Malicious crates reached crates.io in 2025. The attack class is typosquatting
against popular async, logging, and crypto utility names. Read them before you dismiss a new dependency as low-risk:

- September 2025: `faster_log` and `async_println`, typosquats of popular
  async-logging names. The payload exfiltrated CI tokens and SSH keys. See
  <https://blog.rust-lang.org/2025/09/24/crates.io-malicious-crates-fasterlog-and-asyncprintln/>.
- December 2025: `finch-rust` and `sha-rust`, typosquats of crypto and hash
  utilities. Same attack class. See
  <https://blog.rust-lang.org/2025/12/05/crates.io-malicious-crates-finch-rust-and-sha-rust>.

Async runtime helpers, hashing and crypto helpers, and serialization helpers
are the highest-risk namespaces. Most Rust workspaces depend on all three.

Apply this gate to every new crate in `Cargo.toml`:

1. **Typo check.** Compare the crate name character by character against the
   intended upstream. Check the repository URL, the owner list, the download
   count, and the first-publish date on crates.io. A one-week-old crate with a
   familiar name is a red flag.
2. **Read the code.** Scan the published crate's `build.rs`, `src/lib.rs`, and
   any proc-macro crate it pulls in. Look for network calls, shell-out,
   `std::process::Command`, environment-variable reads, and file writes outside
   `OUT_DIR`. A pure utility crate that opens a socket is a red flag.
3. **Pin exactly on first adoption.** Use `=1.2.3` in the commit that adds the
   crate. Loosen to `^1.2` only after the crate has stayed in the tree for at
   least one release cycle without incident.
4. **Create and inspect the candidate lockfile.** After you edit `Cargo.toml`,
   resolve the exact manifest addition once without `--locked`:

   ```bash
   cargo metadata --format-version 1 > /dev/null
   git diff -- Cargo.lock
   ```

   Inspect every new package in `Cargo.lock`. Do not use `cargo update -p
   <crate>` for a crate that is not in the old lockfile. Cargo cannot select
   that package yet. Do not run `cargo deny --locked` before this step. The old
   lockfile does not contain the proposed dependency graph.
5. **Run policy against the candidate graph.** Run `cargo deny --locked check
   bans advisories sources`. Reject the dependency if the new graph fails.
6. **Justify the dependency.** Check whether the standard library or a crate
   already in the graph does the job. Every new crate widens the attack
   surface and adds a `multiple-versions` risk.

## 6. Supply chain hardening

```bash
# Commit Cargo.lock for every application and binary crate
# Use --locked in CI so the build matches the lockfile
cargo fetch --locked

# Inspect the dependency graph
cargo tree --locked              # full tree
cargo tree --locked -d           # duplicate versions
cargo tree --locked -i <crate>   # why is this crate here

# Find unused dependencies
cargo machete

# Peer-reviewed dependency vetting
cargo install cargo-vet
cargo vet
```

Additional rules:

- Keep `Cargo.lock` in version control for binaries, cdylibs, and staticlibs.
  A library crate that ships a lockfile only fixes its own CI.
- Deny unknown registries. Allow only crates.io unless a git dependency has a
  written reason and a pinned revision.
- Treat a `git` dependency without a `rev = "..."` pin as unpinned code
  execution. Pin the revision, not the branch.
- Run the policy check on a schedule as well as on pull requests. New
  advisories land against unchanged lockfiles.

## 7. Untrusted-input parser hardening

Any Rust code that parses a file, a byte buffer, or a network frame from
outside your process must treat that input as adversarial. This applies to
archives, protobuf, XML, JSON, SQLite files, images, and custom binary
containers.

Core rules:

- **Never trust a length field before you allocate.** Cap the value before you
  call `Vec::with_capacity` or `vec![0u8; n]`.
- **Limit recursion depth** in nested protobuf, XML, and JSON parsers.
- **Validate floating-point input** for `NaN` and infinity before arithmetic.
- **Reject path traversal.** Accept only normal UTF-8 `Path::components`.
  Create entries relative to an open staging-root handle with no-follow
  semantics. Do not canonicalize a destination that does not exist yet.
- **Disable entity expansion** in XML parsers.
- **Authenticate before you mutate.** Verify the digest or MAC of a container
  before you apply any of its content to live state.
- **Reject unknown schema versions and unknown fields.** A parser that silently
  accepts drift is a parser that accepts attacker-chosen fields.

```rust
// Cap the recursion depth of nested structures.
const MAX_NESTING_DEPTH: usize = 8;

// Cap the allocation before you trust a length field from untrusted input.
const MAX_CHUNK_BYTES: u32 = 64 * 1024 * 1024; // 64 MiB

fn read_chunk(declared_len: u32) -> Result<Vec<u8>, ParseError> {
    if declared_len > MAX_CHUNK_BYTES {
        return Err(ParseError::TooLarge {
            declared: declared_len,
            cap: MAX_CHUNK_BYTES,
        });
    }
    Ok(vec![0u8; declared_len as usize])
}
```

For the full checklist, including archive extraction, streamed container
formats, geometry and coordinate validation, and the FFI boundary rules, see
[references/untrusted-input.md](references/untrusted-input.md).

### Untrusted keys in a hash map

std `HashMap` and `HashSet` use SipHash 1-3 with a per-process random seed. std documents
that seed as the HashDoS defence. `FxHasher`, `FnvHasher`, and `nohash` remove it.
Verified across two separate processes: `FxHasher` and `FnvHasher` give byte-identical
output for the same key. The `FxHasher` hash of `42` is 12569757018929961129 in both runs.
SipHash and `ahash` differ. An attacker who controls keys can precompute a collision set
offline.

Get the mechanism right. std `HashMap` is hashbrown. It is open-addressed with SIMD group
probing, not chained, so degradation shows up as long probe sequences and not as O(n)
bucket chains. Measured on rustc 1.97.0 with trivially crafted keys, multiples of 2^20 and
no knowledge of the internals: `FxHashMap` insert took 3.47 ms against 0.35 ms for benign
keys, a factor of 10. A full blowup needs a deliberately built collision set.

The gate is key provenance, not a profile. Keep std `RandomState` for keys an outside
caller controls: HTTP headers, query parameters, JSON object keys, archive entry names,
and protocol field names. Use `ahash::RandomState` when that path is measured hot. It is
randomly seeded per process, because `runtime-rng` and `getrandom` are default features of
`ahash` 0.8.12. The swap is one import and leaves no trace in review, so it needs a rule.
See `rust-hot-path` for the performance side of the same choice.

## 8. CI integration

Run the policy check as its own job so a failure names the cause without a log
hunt. A minimal job does this:

1. Check out the repository.
2. Install the exact pinned `cargo-deny` version. A pre-built installer action
   avoids a source build on every run. On GitHub Actions,
   `taiki-e/install-action@v2` with `tool: cargo-deny@<pinned-version>` does
   this.
3. Run `cargo deny --locked --manifest-path path/to/Cargo.toml check`.

Design rules:

- Pin the tool version. Do not install `latest`.
- Run the job on pull requests and on pushes to the default branch.
- Add a scheduled run. Advisories appear without a code change.
- Cache the advisory database between runs if the job is slow. Do not cache it
  so long that the job checks a stale database.

When the CI job fails:

| Failing check | First action |
|---|---|
| `advisories` | Read the RUSTSEC ID. Try `cargo update -p <crate>`. Only then consider a time-boxed ignore. |
| `licenses` | Find the crate with `cargo tree --locked -i <crate>`. Do not widen the allowlist to clear one crate without a license review. |
| `bans` | Run `cargo tree --locked -d`. Unify the versions. Add a `skip` entry only with a causal reason. |
| `sources` | A dependency came from a registry or git remote that policy does not allow. Check for an accidental `[patch]` or a path override. |

Reproduce the failure locally with the same command and the same pinned tool
version. Fix the root cause. Do not extend an `ignore` or `skip` list to make
the job green.

## Review gate

Block a change that does any of these:

- Adds a crate without a typo check, an upstream check, and an exact version
  pin in the adoption commit.
- Adds an `[advisories].ignore` entry without an `id`, a `reason`, and a
  tracking issue.
- Adds a `[bans].skip` entry without a causal reason for the duplicate.
- Widens the license allowlist to clear one dependency, with no license review
  recorded.
- Allocates from an untrusted length field without a cap.
- Extracts an archive entry without a traversal check.
- Panics on malformed input across an FFI boundary.

## Related skills

- `cargo-workflows`: lockfile management, workspaces, and feature flags.
- `rust-sanitizers-miri`: Miri and sanitizers for memory-safety validation.
- `rust-unsafe`: unsafe code audit patterns and safe abstraction design.
- `rust-panic-safety`: panic containment, including panics at an FFI boundary.
- `rust-hot-path`: the performance side of the hasher choice.
- `rust-lints`: Clippy configuration and lint policy.
- `rust-discipline`: engineering discipline and coding conventions.
- `uniffi-boundary`: input validation and typed errors across a UniFFI boundary.
- `ffi-error-progress-cancel`: error mapping across an FFI boundary.
- `rust-jni`: JNI-level FFI safety.
- `rust-test-tools`: fuzz and property tests for parser hardening.
