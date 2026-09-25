---
name: rust-crate-release
description: Use when preparing to publish a Rust crate or a Rust binary release, or recovering from a bad one - deciding a SemVer bump or MSRV change, checking cargo package and cargo publish output, ordering a workspace publish, setting up crates.io trusted publishing, deciding whether to yank a crate version, building a release archive with a release checksum, release SBOM, and attestation, or using cosign to sign release artifact files.
license: BSD-3-Clause
---

# Rust Crate Release

A release has two independent modes. The registry mode publishes a source `.crate`. The binary
mode distributes built assets. They fail in different ways and need different permissions.
An authorization for one mode does not authorize the other.

## Safety rules

Published versions and uploaded assets are permanent, so these rules have no exception:

- Get explicit authorization before each external write. Name the exact package, version,
  registry, tag, asset, or account. External writes are: `cargo publish`, a commit or tag push,
  creating, editing, or finalizing a hosted release, an asset upload, signing or attestation,
  `cargo yank` and `--undo`, `cargo owner` changes, crate deletion, and crate settings such as a
  trusted publisher.
- Never add `--allow-dirty` or `--no-verify` to make a release pass. Both publish bytes that no
  check saw.
- Never put a registry token on the command line or in a log. Shell history and CI logs keep it.
  If a token leaks, revoke it at once (crates.io: https://crates.io/settings/tokens), then create
  a new scoped token.
- Never reuse a version after a partial or timed-out publish. The upload can have completed.
- Never release a different commit under an existing version, and never replace a named asset
  with different bytes. Users and caches already trust the first bytes.

Local inspection, tests, `cargo package`, and `cargo publish --dry-run` write nothing external.
Run them before you ask for authorization.

## Failure triage

| Symptom | Likely cause | Fix |
|---|---|---|
| `cargo info` output says `(from ./...)` | No `--registry`; Cargo 1.94+ describes the local member | Pass `--registry <registry>` and read the result again |
| `cargo package --list` misses a file | `include`, `exclude`, or a VCS ignore rule removes it | Fix the manifest and list again |
| Archive tests fail with E0432 or E0433 on a test helper crate | A path-only dev-dependency is removed from the published manifest | Give it a published `version`, or keep those tests out of the archive and document it |
| Package verifies in the workspace but not from the archive | Hidden path, generated file, or undeclared build input | Include the input or generate it in `OUT_DIR` |
| Dry run selects the wrong package | Workspace defaults or the current directory select another member | Pass `-p <package>` and `--registry` |
| `--all-features` fails | Features conflict or one combination lacks coverage | Test the documented valid sets and fix accidental conflicts |
| docs.rs build fails or lacks a platform API | Feature, target, native dependency, or sandbox difference | Fix `[package.metadata.docs.rs]` or the build behavior, then release a new version if required |
| Two clean binary builds have different digests | Path, timestamp, linker, toolchain component, or archive metadata differs | Find the variation or remove the reproducibility claim |
| Binary upload times out | The host can have accepted the asset | Download and hash the remote bytes; follow the retry table in the binary reference |
| Signature verifies for an unexpected identity | The signature is valid but the trust policy is wrong | Stop and pin the expected identity and issuer |

## Completion report

Report these facts:

- published or prepared status for each mode;
- package, version, registry, commit, and tag;
- SemVer and MSRV decision with evidence;
- exact checks and observed results;
- package contents and archive size;
- binary target matrix, asset names, checksums, SBOM, provenance, and signature status, and the
  consumer verification of every downloaded asset;
- registry and docs.rs result;
- every external action performed;
- remaining risks and blocked checks.

Do not report a release as complete when only a dry run passed. Do not report a publish as failed
only because the client timed out.

## Release inputs

Collect these values first:

| Input | Required evidence |
|---|---|
| Package | Exact Cargo package name and manifest path |
| Registry | `crates-io` or one configured registry name |
| Base | Previous published version and its source tag, or `none` for a first release |
| Candidate | Exact commit to release |
| Version | Proposed new version |
| MSRV | Effective `package.rust-version` and the project support policy |
| Features | Default set and every supported non-default combination |
| Targets | Supported target and operating-system policy |
| Mode | Registry package, binary distribution, or both |
| Channel | Local `cargo publish`, or a CI workflow that a tag or dispatch starts |
| Authority | Who can approve publish, tags, releases, uploads, signing, yanks, and owner changes |

Run these read-only checks:

```bash
git status --short
git rev-parse HEAD
git tag --list --sort=-version:refname
cargo metadata --locked --no-deps --format-version 1
```

Stop if the candidate worktree is dirty. Use a clean worktree at the candidate commit when other
work must stay in place.
`--locked` needs a committed `Cargo.lock`. Libraries commit it too; the `cargo-workflows` skill,
when it is installed, owns that rule.
Read `target_directory` from the `cargo metadata` output. `cargo package` writes the archive to
`<target_directory>/package/`, which is not `./target` when `CARGO_TARGET_DIR` or
`build.target-dir` is set.

Read the repository release policy, CI config, `Cargo.toml`, README, changelog, and recent tags.
Do not invent a tag prefix or changelog format.

## 1. Compare the published base with the candidate

Use the previous release tag as the fixed base, not the previous commit:

```bash
git diff --stat <previous-release-tag>..HEAD
git log --oneline <previous-release-tag>..HEAD
```

For a first release, confirm that the name has no published version in the target registry
(section 5). Review the complete public surface as the initial contract.

Inspect every change that can alter the user contract: public items and re-exports, trait
implementations and auto traits, macros, features and optional dependencies, `rust-version`,
edition, dependency requirements, targets and native requirements, documented errors, panics,
and safety requirements, and the files in the archive.
A dependency is public when its type appears in a public signature or a macro expansion.
Review the expanded user-facing surface, not only lines that contain `pub`.

## 2. Classify the version change

Apply the repository policy first. Use the Cargo SemVer guide when the policy is silent.
Read [references/compatibility.md](references/compatibility.md) when the diff changes a public
item, trait impl, macro, feature, MSRV, or platform requirement. It holds the classification
table and the review checklist.

For `1.0.0` and later, use patch for compatible fixes, minor for compatible additions, and major
for incompatible changes. For `0.y.z`, `y` is the breaking position. Each `0.0.z` release is
incompatible with every other `0.0` release.
Choose the larger bump for a possibly breaking change unless policy and downstream evidence
support a smaller one. Record the classification and its evidence in the release notes.

Run an API diff with `cargo-semver-checks`. Install it with
`cargo install --locked cargo-semver-checks` when it is missing. If it cannot be installed, report
the API diff as not run.

```bash
cargo semver-checks -p <package> --baseline-version <previous-version>
```

It is a CLI, not a manifest dependency. Treat a reported break as real. A clean result does not
prove compatibility: it does not check behavior, documented panics, or every macro change.
`--baseline-version` looks up only crates.io. For another registry, pass
`--baseline-rev <previous-release-tag>`.
Each release of the tool reads the rustdoc JSON of at least the stable and beta Rust of its
release date. Update the tool when you update the stable toolchain.

## 3. Verify MSRV, features, and targets

Read `rust-version` from the package or its inherited workspace value. Keep the documented MSRV
equal to the value that CI verifies.

```bash
rustup toolchain install <msrv> --profile minimal
cargo +<msrv> test --locked -p <package> --all-targets
cargo +<msrv> test --locked -p <package> --doc
```

When the package fetches from a third-party registry or over SSH git and the MSRV is below
1.96.1, do not let the MSRV Cargo download. Older Cargo has credential-leak and libssh2 CVEs.
Vendor with a toolchain at 1.96.1 or later, and add `--offline` to each MSRV command. The
`cargo-workflows` skill, when it is installed, has the steps.

When the MSRV build fails, find the cause before you raise the MSRV. Never run a full
`cargo update` as the fix: it moves every dependency just before publish. Re-resolve only the one
dependency, vet each new package name, and commit the lockfile before you build or test again.
Read [references/compatibility.md](references/compatibility.md) when the MSRV build fails or a
workspace has several MSRVs; it has the cause and fix table.

Run the smallest feature matrix that covers each supported state:

```bash
cargo test --locked -p <package> --all-targets
cargo test --locked -p <package> --all-targets --no-default-features
cargo test --locked -p <package> --all-targets --no-default-features --features <feature-set>
```

Add `--all-features` only when the features are additive. Otherwise test each documented set, or
run `cargo hack test --each-feature` when `cargo-hack` is installed.
Test every supported target in CI or with the repository's target command. A host-only build does
not prove target support.

## 4. Check manifest and documentation metadata

Verify these `[package]` values for the package that ships:

```toml
[package]
name = "<package>"
version = "<version>"
rust-version = "<msrv>"
description = "<one-line description>"
license = "<SPDX expression>"
repository = "<source URL>"
readme = "README.md"
```

Use `license-file` instead of `license` only for a nonstandard license, and confirm the file
enters the archive. Check every README link as it renders on the registry page. Do not set
`homepage` to the `repository` or documentation URL.

docs.rs announced that from 2026-05-01 it builds only the default target (`default-target`, else
`x86_64-unknown-linux-gnu`) unless `targets` lists more. Set `targets` explicitly when the public
API differs by target, or users see no documentation for the other targets:

```toml
[package.metadata.docs.rs]
features = ["<documented-feature>"]
targets = ["x86_64-unknown-linux-gnu", "<other-supported-target>"]
```

Use `all-features = true` only when the features are additive.

## 5. Prepare the version and changelog

Update only the authoritative version field and respect workspace inheritance.
Write the changelog from the release diff: additions, fixes, deprecations, breaking changes, MSRV,
feature, and platform changes, and migration steps. Do not call a possibly breaking change
compatible without evidence.

The archive must come from a clean release commit. Create that commit locally. Stage only the
version, lockfile, changelog, and other required release files. Do not push yet; section 11 gates
the push.

```bash
git diff --cached --check
git diff --cached
```

Confirm that the version is free in the registry. Always pass `--registry`, also for crates.io:

```bash
cargo info <package>@<version> --registry <registry>
```

Since Cargo 1.94, `cargo info` in a workspace describes the local member when no registry is
explicit. Its version line then says `(from ./<member-path>)`, which is false evidence. A free
version gives:

```text
error: could not find `<package>@<version>` in registry `<index-url>`
```

A timeout or an authentication error is not evidence that the version is free.

## 6. Run repository gates

Run the repository's canonical format, lint, test, and build commands. Without them, run:

```bash
cargo fmt --all --check
cargo clippy --locked -p <package> --all-targets --all-features -- -D warnings
cargo test --locked -p <package> --all-targets --all-features
cargo test --locked -p <package> --doc --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked -p <package> --all-features --no-deps
```

Replace `--all-features` with the supported sets when features conflict. `--all-targets` does not
run doctests, so keep the `--doc` line. The `rust-lints` skill, when it is installed, owns the
`cargo doc` gate. This per-package form leaves out `--document-private-items`: it checks the
public docs that docs.rs renders.
Run the advisory gate that the repository uses,
`cargo deny --config deny.toml --locked check advisories` or `cargo audit`. If the repository has
no advisory gate, run `cargo audit`. Install it with `cargo install --locked cargo-audit` when it
is missing. If it cannot be installed, report the advisory check as not run.
Every `.crate` contains `Cargo.lock` unless `--exclude-lockfile` is passed, and
`cargo install --locked` builds with it, so a vulnerable locked dependency reaches the users of a
binary crate. The `rust-security` skill, when it is installed, owns the advisory policy.
Run the MSRV and target checks after the final version change. A green CI run for a different
commit is not release evidence.

## 7. Inspect the exact package

List the files before you create the archive:

```bash
cargo package --locked -p <package> --registry <registry> --list
```

Review the complete list. Look for missing source, generated files, README, license, and build
inputs. Look for secrets, credentials, private keys, internal notes, large fixtures, and
repository-only files. Use `include` or `exclude` only when the default set is wrong; `include`
overrides `exclude`.

Create and verify the archive:

```bash
cargo package --locked -p <package> --registry <registry>
cargo publish --locked -p <package> --registry <registry> --dry-run
```

Both must pass as written (see Safety rules). Inspect the `.crate` under
`<target_directory>/package/`; `cargo publish` does not keep one since Cargo 1.93.
crates.io rejects a compressed `.crate` over 10 MB.

`cargo package` verifies only that the library and binaries build. Test the packaged source when
tests, examples, build scripts, or generated files can differ from the workspace:

```bash
release_tmp="$(mktemp -d)"
tar -xzf "<target_directory>/package/<package>-<version>.crate" -C "$release_tmp"
(
  cd "$release_tmp/<package>-<version>"
  cargo test --locked --all-targets
  RUSTDOCFLAGS="-D warnings" cargo doc --locked --no-deps
)
```

Cargo removes a path dev-dependency that has no `version` from the published manifest. Tests that
use it pass in the workspace and fail from the archive with E0432 (a `use` import) or E0433 (a
path such as `helper::f()`). Keep the directory until diagnosis ends.

## 8. Distribute binary artifacts

Use this mode only when users download prebuilt executables, libraries, installers, or firmware.
Read [references/binary-distribution.md](references/binary-distribution.md) when you build,
sign, or upload these artifacts.
A registry publish does not prove a binary release, and the reverse is also true. Report each
mode separately.

## 9. Handle workspace release order

Read [references/workspace-publish.md](references/workspace-publish.md) when the release
publishes more than one workspace package. Publish dependencies before dependents, and verify the
whole ordered set in one dry run before the first upload. Multi-package `cargo publish` is not
atomic: request authorization with the complete ordered list, and stop after the first failed or
uncertain publish.

## 10. Request authorization and publish

Choose exactly one release channel for each version:

- **Direct:** run the approved local `cargo publish`. Tag the commit only after the registry
  shows the version.
- **CI:** a tag push or manual dispatch starts the repository workflow. Do not run a local
  `cargo publish` for that version.

Read the workflow to learn which event uploads the crate. For crates.io from GitHub Actions or
GitLab.com, prefer Trusted Publishing to a stored token. Read
[references/trusted-publishing.md](references/trusted-publishing.md) when you write or review a
publish workflow or change the crate's publisher settings.

With the authorization request, present the completion-report facts that exist so far, the
changelog summary, and the exact command. For a direct release that is
`cargo publish --locked -p <package> --registry <registry>`; for a CI release it is the exact tag
push that starts the workflow.

After approval, run `git status --short` and `git rev-parse HEAD` again. Stop if either differs
from the approved candidate. Run the approved command once.
If it times out, never publish that version again. Check the registry until the result is known,
then stop the release chain. An immediate negative `cargo info` does not prove that the upload
failed.

## 11. Verify the registry and tag the source

```bash
cargo info <package>@<version> --registry <registry>
```

Confirm that the version line names no local `(from ./...)` path. Check the registry page and the
docs.rs build. A docs.rs failure is a release defect even when the archive is available.

For a direct release, tag the exact published commit. For a CI release, confirm that the pushed
tag points to the approved candidate, and create no second tag. Use the repository's prefix and
annotated-tag convention:

```bash
git tag -a <tag> -m "Release <package> <version>"
git show --no-patch --decorate <tag>
```

Get authorization before you push the commit or tag. Never move an existing tag. If the remote
tag exists at another commit, stop and report the conflict.
The release is complete only when the registry version and the remote tag both match the
approved source.

## 12. Recover from a bad release or change owners

When possible, publish a compatible fixed version before any yank; a yank is not the normal fix.
If a secret entered the archive, revoke the secret first: a yank or a deletion does not remove it.
Each yank, `--undo`, crate deletion, owner change, and advisory filing needs its own authorization.
Read [references/recovery.md](references/recovery.md) when you consider a yank, a crate deletion,
an owner change, or a RustSec advisory for your own release.

## Related skills

Use these skills when they are installed:

- `cargo-workflows` for workspace layout, lockfile policy, profiles, CI caching, and edition
  migration.
- `rust-discipline` to design or review the public Rust API.
- `rust-security` for dependency advisories, `deny.toml`, vetting a new or updated dependency,
  and the response to a vulnerable or malicious dependency.
- `rust-test-tools` and `rust-tdd` for the test strategy behind the release gates.
- `uniffi-packaging-versioning` for mobile FFI artifacts and bindings.

## Official references

- [Cargo publishing](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [cargo-semver-checks](https://github.com/obi1kenobi/cargo-semver-checks)
- [`cargo package`](https://doc.rust-lang.org/cargo/commands/cargo-package.html)
- [`cargo info`](https://doc.rust-lang.org/cargo/commands/cargo-info.html)
- [Cargo changelog](https://doc.rust-lang.org/nightly/cargo/CHANGELOG.html)
- [docs.rs build metadata](https://docs.rs/about/metadata)
- [docs.rs default target change](https://blog.rust-lang.org/2026/04/04/docsrs-only-default-targets/)
