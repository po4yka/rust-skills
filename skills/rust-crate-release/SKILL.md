---
name: rust-crate-release
description: Use when you prepare, verify, publish, distribute, or recover a public Rust release, including Cargo registry publishing and downloadable binary artifacts. Triggers on "publish a Rust crate", "cargo publish", "cargo package", "crate release", "SemVer bump", "MSRV change", "yank a crate version", "Rust binary release", "release archive", "release checksum", "release SBOM", or "sign release artifact".
license: BSD-3-Clause
---

# Rust Crate Release

## Purpose

Use this skill to release public Rust crates to a Cargo registry or distribute Rust binaries.
Classify compatibility before you change a version.
Verify the exact package that users receive.
Stop before each external write until the user authorizes that exact action.

This skill owns the release decision, registry transaction, and binary artifact transaction.
Treat registry publishing and binary distribution as separate release modes.
An authorization for one mode does not authorize the other mode.
It does not own general workspace layout, lint policy, dependency audits, or API design.
Use the related skills for those concerns.

## Safety rules

- Treat a published crate version as permanent.
- Never assume that a yank deletes a published archive.
- Never run `cargo publish` without explicit authorization for the package, version, and registry.
- Never add `--allow-dirty` or `--no-verify` to make a release pass.
- Never print, copy, or pass a registry token on the command line.
- Never create a replacement release from a different commit without a new version.
- Never reuse a version after a partial or timed-out publish.
- Never change owners without explicit authorization for the exact account or team.
- Never yank or unyank a version without explicit authorization for the exact version and registry.
- Never push a release commit or tag without explicit authorization.
- Never create, finalize, or update a hosted release or upload an asset without explicit
  authorization.
- Never sign an artifact or publish an attestation without explicit authorization.
- Never replace a named release asset with different bytes.

Local inspection, tests, `cargo package`, and `cargo publish --dry-run` do not upload a crate.
Run them before you ask for publish authorization.

## Release inputs

Collect these values first:

| Input | Required evidence |
|---|---|
| Package | Exact Cargo package name and manifest path |
| Registry | `crates-io` or one configured registry name |
| Base | Previous published version and source, or `none` for a first release |
| Candidate | Exact commit to release |
| Version | Proposed new version |
| MSRV | Effective `package.rust-version` and project support policy |
| Features | Default set and every supported non-default combination |
| Targets | Supported target and operating-system policy |
| Mode | Registry package, binary distribution, or both |
| Authority | Who can approve publish, tags, releases, uploads, signing, yanks, and owner changes |

Run these read-only checks:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git tag --list --sort=-version:refname
cargo metadata --locked --no-deps --format-version 1
```

Stop if the candidate worktree is dirty.
Preserve unrelated work instead of hiding it with `--allow-dirty`.
Use a clean worktree at the candidate commit when other work must remain in place.

Read the repository release policy, CI config, `Cargo.toml`, README, changelog, and recent tags.
Do not invent a tag prefix or changelog format.

## 1. Compare the published base with the candidate

Use the previous release source as the fixed base.
Do not compare only with the previous commit.

```bash
git diff --stat <previous-release-tag>..HEAD
git diff --name-status <previous-release-tag>..HEAD
git log --oneline <previous-release-tag>..HEAD
```

For a first release, verify that the package name has no published version in
the target registry. Review the complete public surface, manifest, features,
targets, package contents, and documentation. Classify it as the initial
contract instead of inventing a SemVer comparison base.

Inspect all files that can change the user contract:

- public modules and re-exports;
- public functions, types, constants, statics, traits, and macros;
- public trait implementations and auto-trait behavior;
- feature names, default features, and optional dependencies;
- supported targets, `no_std` support, and native requirements;
- `rust-version`, edition, and dependency requirements;
- errors, panics, safety requirements, and documented behavior;
- library, binary, example, and build-script targets;
- files included in the published archive.

A private-looking dependency can still be public when its type appears in a public signature.
A macro can expose paths and types that do not appear in ordinary function signatures.
Review the expanded user-facing surface, not only lines that contain `pub`.

## 2. Classify the version change

Apply the repository policy first.
Use the Cargo SemVer guide when the policy is silent.
Read [references/compatibility.md](references/compatibility.md) for the classification table and
the public API review checklist.

For `1.0.0` and later, use patch for compatible fixes, minor for compatible additions, and major
for incompatible changes.
For `0.y.z`, use `y` as the breaking-release position.
Treat each `0.0.z` release as incompatible with the other `0.0` releases.

Record the classification and evidence in the release notes.
Choose the safer version for a possibly breaking change unless policy and downstream evidence
support a smaller bump.
Run the repository's existing API compatibility tool when one is configured.
Treat its output as evidence, not as proof that behavior and macros are compatible.

## 3. Verify MSRV, features, and targets

Read `rust-version` from the package or its inherited workspace value.
Keep the documented MSRV equal to the value that CI verifies.
Test all supported functionality on that toolchain.

```bash
rustup toolchain install <msrv> --profile minimal
cargo +<msrv> test --locked -p <package>
cargo +<msrv> test --locked -p <package> --all-targets
```

Run the smallest feature matrix that covers each supported state:

```bash
# Default contract
cargo test --locked -p <package> --all-targets

# No-default contract, when the crate supports it
cargo test --locked -p <package> --no-default-features --all-targets

# Union of features, when features are compatible
cargo test --locked -p <package> --all-features --all-targets

# Each documented independent or mutually exclusive feature set
cargo test --locked -p <package> --no-default-features --features <feature-set>
```

Do not force `--all-features` when the manifest documents incompatible features.
Test each valid combination instead.
Document every intentional invalid combination and keep its compile-time diagnostic stable.

Treat feature names as public API.
Do not remove a feature in a compatible release.
Do not remove a default feature when users can depend on its behavior.
Use `dep:<name>` for a new optional dependency when its crate name is not a user-facing feature.

Test every supported target in CI or with the repository's existing target command.
Do not claim target support from a host-only build.
Classify a new compiler, linker, system-library, or operating-system requirement as a
compatibility change.

## 4. Check manifest and documentation metadata

Verify these `[package]` values for the package that will ship:

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

Use `license-file` instead of `license` only when the package uses a nonstandard license.
Verify that the selected license files enter the archive.
Verify every README link as it renders from the registry page.
Do not set `homepage` to the same URL as `repository` or API documentation.

Document every public item or explicitly allow missing documentation under repository policy.
Build documentation with warnings denied:

```bash
RUSTDOCFLAGS="-D warnings" cargo doc --locked -p <package> --no-deps
cargo test --locked -p <package> --doc
```

Add `[package.metadata.docs.rs]` only when the default docs.rs build is not correct.
Keep its feature and target selection equal to the public documentation contract.

```toml
[package.metadata.docs.rs]
all-features = true
targets = ["<supported-target>"]
```

Do not set `all-features = true` when the crate has incompatible features.
Use `features = [...]` for the one supported documentation set in that case.

## 5. Prepare the version and changelog

Update only the authoritative version field.
Respect workspace inheritance.
Do not duplicate a version in generated files unless the repository requires it.

Write the changelog from the release diff.
Include user-visible additions, fixes, deprecations, breaking changes, MSRV changes, feature
changes, platform changes, and required migration steps.
Do not include changes that are not in the candidate commit.
Do not call a possibly breaking change compatible without evidence.

The release archive must come from a clean release commit.
Request authorization before you create that commit when the workflow does not already include
committing release metadata.
Stage only the version, lockfile, changelog, and other required release files.
Inspect the staged diff and use the repository's release commit convention.
Do not push the commit yet.

```bash
git diff --cached --check
git diff --cached
git status --short
```

Verify that the proposed version does not already exist in the target registry.
Use the configured registry explicitly when it is not crates.io.

```bash
cargo info <package>@<version> --registry <registry>
```

An expected "not found" result is evidence that the version is free.
A timeout or authentication error is not that evidence.

## 6. Run repository gates

Run the repository's canonical format, lint, test, and build commands first.
If the repository has no canonical commands, run this minimum set:

```bash
cargo fmt --all --check
cargo clippy --locked -p <package> --all-targets --all-features -- -D warnings
cargo test --locked -p <package> --all-targets --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked -p <package> --all-features --no-deps
```

Replace `--all-features` with the supported sets when features conflict.
Run the MSRV and target checks from the earlier sections after the final version change.
Do not use a previous green CI run for a different commit as release evidence.

## 7. Inspect the exact package

List the files before you create the archive:

```bash
cargo package --locked -p <package> --registry <registry> --list
```

Review the complete output.
Check for missing source, generated files, README, license, examples, and build inputs.
Check for secrets, credentials, private keys, internal notes, fixtures, large assets, and
repository-only files.
Use `include` or `exclude` only when the default package set is wrong.
Remember that `include` overrides `exclude`.

Create and verify the archive:

```bash
cargo package --locked -p <package> --registry <registry>
cargo publish --locked -p <package> --registry <registry> --dry-run
```

Both commands must succeed without `--allow-dirty` and without `--no-verify`.
Inspect the generated `.crate` file under `target/package/`.
For crates.io, keep the compressed archive below the current 10 MB registry limit.

Test the packaged source when tests, examples, build scripts, or generated files can differ
from the workspace build:

```bash
release_tmp="$(mktemp -d)"
tar -xzf "target/package/<package>-<version>.crate" -C "$release_tmp"
(
  cd "$release_tmp/<package>-<version>"
  cargo test --locked --all-targets
  RUSTDOCFLAGS="-D warnings" cargo doc --locked --no-deps
)
```

Keep the temporary directory until you finish diagnosis.
The operating system can remove it later.

## 8. Distribute binary artifacts

Use this mode only when users download prebuilt executables, libraries, installers, or firmware.
Read [references/binary-distribution.md](references/binary-distribution.md) before you build or
upload these artifacts.

Define the target matrix and immutable asset names before the build.
Build every asset from the approved commit and locked dependency graph.
Create archives from an explicit allowlist.
Generate checksums, an SBOM, and provenance with the repository's existing tools and policy.
Use the existing signing system when one is configured.
Do not add a signing or SBOM dependency only to complete a release.

Verify the final local files before any external write.
Request separate authorization for the tag push, hosted draft creation, asset upload, signing or
attestation, and draft finalization unless the user explicitly authorizes the complete named
sequence.
After upload, download every artifact into a fresh directory and verify it as a consumer.

Registry publication does not prove that a binary release is correct.
A hosted binary release does not prove that a registry package is correct.
Report each mode separately.

## 9. Handle workspace release order

Release one package at a time.
Publish workspace dependencies before their dependents.
Require each publish to appear in the target registry before you publish the next package.

For a dependency that has both `path` and `version`, verify that `version` selects the release
that the dependent package needs.
Do not publish all workspace members because one member changed.
Do not use `cargo publish --workspace` when an explicit order gives clearer failure recovery.

Run package listing and archive checks for every package separately.
Run the dependent package dry run only after each new workspace prerequisite
appears in the registry index. Before that point, its published manifest cannot
resolve the new registry dependency even when the workspace path build passes.
Request publish authorization with the complete ordered list.
Stop after the first failed or uncertain publish.

## 10. Request authorization and publish

Choose exactly one release channel before any external write:

- For a direct release, run the approved local `cargo publish` command. Create
  and push the tag only after registry verification.
- For an existing tag-triggered release workflow, do not run local
  `cargo publish`. Request authorization for the exact tag and push, monitor
  the publishing job, and verify the registry result.

Never combine the two channels for one version. Read the repository workflow
to determine whether a tag, release, or manual CI dispatch performs the upload.

Present this evidence before the authorization request:

- package, version, registry, commit, and proposed tag;
- SemVer classification and any compatibility risk;
- MSRV, feature, target, test, lint, docs, and package results;
- complete package-list review and archive size;
- changelog summary;
- exact direct-publish command or tag-trigger command.

For a direct release, ask for explicit authorization to run this exact
external write:

```bash
cargo publish --locked -p <package> --registry <registry>
```

For a tag-triggered release, ask for authorization to create and push the exact
tag instead. Run no equivalent upload or tag push before approval.
After approval, re-check `git status --short` and `git rev-parse HEAD`.
Stop if either differs from the approved candidate.

Run the approved command once.
If it returns an uncertain timeout, never publish that version again. Recheck
the registry and index until the result is known, then stop the release chain.
An immediate negative `cargo info` result does not prove that the upload failed.

## 11. Verify the registry and tag the source

Verify the exact published version:

```bash
cargo info <package>@<version> --registry <registry>
```

Check the registry page and docs build when those services apply.
Record a docs build failure as a release defect even when the archive is available.

For a direct release, create the release tag on the exact published commit
after registry verification. For a tag-triggered release, verify that the
already-pushed trigger tag points to the approved candidate. Never create a
second tag or run a local publish for that version. Use the repository's
existing prefix and annotated-tag convention.

```bash
git rev-parse HEAD
git tag -a <tag> -m "Release <package> <version>"
git show --no-patch --decorate <tag>
```

Request explicit authorization before you push the release commit or tag.
Do not move an existing tag.
If the remote tag exists at another commit, stop and report the conflict.

Complete the release only after the registry version and remote tag both point to the approved
source state.

## 12. Manage owners separately

List current owners before any change:

```bash
cargo owner --list <package> --registry <registry>
```

Explain that owners can publish and yank versions.
Explain that a non-team owner can also change owners.
Prefer a team owner when the registry supports the required restricted team rights.

Request explicit authorization for one exact command:

```bash
cargo owner --add <account-or-team> <package> --registry <registry>
cargo owner --remove <account-or-team> <package> --registry <registry>
```

Run only the approved add or remove command.
List owners again and report the observed final set.

## 13. Recover from a bad release

Do not treat yank as the normal fix for a defect.
When possible, publish a compatible fixed version before you yank the broken version.
Check exact-version dependents and supported release lines first.

Use yank only for an exceptional release defect, such as an accidental publish, an unintended
SemVer break, or a version that is significantly broken.
Request explicit authorization before the registry change.

```bash
cargo yank <package>@<version> --registry <registry>
cargo yank <package>@<version> --undo --registry <registry>
```

A yank blocks new resolutions by default.
It does not break existing lockfiles, delete downloads, erase leaked secrets, or remediate users
who already fetched the crate.

If a secret entered the archive, revoke it immediately and contact the registry.
Do not wait for a yank.
If the release has a security vulnerability, coordinate an advisory and a fixed release.
Use `rust-security` for that response.

## Failure triage

| Symptom | Likely cause | Fix |
|---|---|---|
| `cargo package --list` misses a file | `include`, `exclude`, or VCS ignore rule removes it | Fix the manifest and list again |
| Package verifies in the workspace but not from the archive | Hidden path, generated file, or undeclared build input | Make the input part of the package or generate it in `OUT_DIR` |
| Dry run selects the wrong package | Workspace defaults or current directory select another member | Pass `-p <package>` and the registry explicitly |
| MSRV build fails | Code, dependency, feature, or manifest syntax exceeds `rust-version` | Restore compatibility or classify and document an MSRV increase |
| `--all-features` fails | Features conflict or one combination lacks coverage | Test documented valid sets and fix accidental conflicts |
| Publish times out | Upload can have completed before client polling ends | Never retry that version; keep checking the registry and stop the release chain |
| Dependent crate cannot publish | Registry does not yet expose its new dependency | Wait for index visibility, then rerun the dry run |
| docs.rs build fails | Feature, target, native dependency, or sandbox assumption differs | Fix metadata or build behavior, then release a new version if required |
| Wrong version contains a defect | Published archives are permanent | Publish a compatible fix, then consider an authorized yank |
| Archive contains a secret | Yank does not remove downloads | Revoke the secret and contact the registry immediately |
| Two clean binary builds have different digests | Build input, path, timestamp, linker, or packaging metadata differs | Find the source of variation or remove the reproducibility claim |
| Release archive contains an unsafe path or link | Packaging copied an uncontrolled tree | Rebuild from an explicit allowlist and do not upload it |
| Binary upload times out | The host can have accepted the asset | Download and hash the remote bytes; follow the bounded retry decision in the binary reference |
| Signature verifies for an unexpected identity | The cryptographic signature is valid but the trust policy is wrong | Stop and verify the expected key or certificate identity and issuer |
| One uploaded asset fails verification | The hosted release is incomplete or inconsistent | Keep it non-final when possible and stop before later release actions |

## Completion report

Report these facts:

- published or prepared status;
- package, version, registry, commit, and tag;
- SemVer and MSRV decision;
- exact checks and observed results;
- package contents and archive size review;
- binary target matrix, asset names, checksums, SBOM, provenance, and signature status;
- downloaded artifact verification for every published binary target;
- registry and docs verification;
- every external action performed;
- any remaining risk or blocked check.

Do not say that the release is complete when only a dry run passed.
Do not say that publish failed only because the client timed out.

## Related skills

- Use `cargo-workflows` for workspace layout, dependency inheritance, lockfiles, profiles,
  cross-compilation, and edition migration.
- Use `rust-discipline` while you design or review the public Rust API.
- Use `rust-security` for dependency policy, RUSTSEC, leaked credentials, and vulnerability
  response.
- Use `rust-test-tools` and `rust-tdd` for the test strategy behind release gates.
- Use `rust-observability` for runtime telemetry changes that affect the public contract.

## Official references

- [Cargo SemVer Compatibility](https://doc.rust-lang.org/cargo/reference/semver.html)
- [Cargo Rust Version](https://doc.rust-lang.org/cargo/reference/rust-version.html)
- [Cargo Features](https://doc.rust-lang.org/cargo/reference/features.html)
- [Cargo Manifest Format](https://doc.rust-lang.org/cargo/reference/manifest.html)
- [Cargo Publishing](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [`cargo package`](https://doc.rust-lang.org/cargo/commands/cargo-package.html)
- [`cargo publish`](https://doc.rust-lang.org/cargo/commands/cargo-publish.html)
- [`cargo owner`](https://doc.rust-lang.org/cargo/commands/cargo-owner.html)
- [`cargo yank`](https://doc.rust-lang.org/cargo/commands/cargo-yank.html)
- [docs.rs build metadata](https://docs.rs/about/metadata)
- [docs.rs build environment](https://docs.rs/about/builds)
- [rustc source path remapping](https://doc.rust-lang.org/rustc/remap-source-paths.html)
- [Sigstore blob signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/)
- [Sigstore signature verification](https://docs.sigstore.dev/cosign/verifying/verify/)
- [SLSA provenance](https://slsa.dev/spec/v1.2/provenance)
- [CycloneDX specification](https://cyclonedx.org/specification/overview/)
- [SPDX specification](https://spdx.dev/use/specifications/)
