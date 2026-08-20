# Binary Release Distribution

Use this reference when a release includes downloadable binaries or other built artifacts.
Do not use it for a registry-only crate release.

## Keep release channels separate

A Cargo registry stores a source package.
A hosted release stores built assets.
These channels can use the same version and tag, but they have separate failure modes and
permissions.

Record which actions the user authorizes:

- create and push the release tag;
- publish each registry package;
- create a hosted draft;
- upload each named asset;
- sign an artifact or publish an attestation;
- finalize or otherwise make the hosted release public.

Do not infer one authorization from another.
Read the repository workflow before you act.
Do not run a local upload when the tag already starts an upload workflow.

## Freeze the distribution contract

Record this matrix before the build:

| Field | Required value |
|---|---|
| Source | Exact commit and release tag |
| Toolchain | Rust toolchain and required external tool versions |
| Build | Locked command, profile, features, and relevant environment |
| Target | Exact Rust target triple and supported CPU or system baseline |
| Runner | Native or existing cross-build environment |
| Asset | Exact immutable file name and archive format |
| Contents | Explicit files and expected executable name |
| Metadata | Checksum, SBOM, provenance, and signature policy |

Name an asset with the product, version, and exact target identity.
Use the complete target triple when it carries an ABI or C runtime distinction.
Use one stable pattern, such as `<product>-<version>-<target>.<archive-extension>`.
Do not publish a mutable `latest` asset as the only download.
Do not call a target supported until its release artifact passes its target-specific checks.

## Build from fixed inputs

Use a clean checkout of the approved commit.
Build the final binary with the repository's release command.
When no release command exists, start with this minimum command:

```bash
cargo build --locked --release --target <target> -p <package> --bin <binary>
```

Use the exact supported feature set instead of adding `--all-features` by habit.
Record the lockfile, compiler, linker, native libraries, build scripts, and environment inputs.
Do not copy an artifact from an earlier build or a developer target directory.

Separate these claims:

- **Deterministic packaging** means the same files and normalized archive metadata produce the
  same archive bytes.
- **Reproducible build** means independent builds of the same source and declared inputs produce
  byte-identical artifacts.

Do not claim a reproducible build after one build.
Two clean directories on one runner establish local repeatability only. They can share toolchain,
cache, environment, and undeclared host inputs.
Before you claim reproducibility, build on independently provisioned builders from the declared
inputs. Compare the unpacked payload digests and the final archive digests.
Use `--remap-path-prefix` only when the repository already requires it or the release process
controls all affected tools.
It does not remove every path that an external linker or build tool can embed.

## Stage a safe archive

Create a fresh staging directory with one versioned top-level directory.
Copy only an explicit allowlist, such as the executable, README, license, and required runtime
files.
Do not copy the repository root or a complete build directory.

Reject these archive entries:

- absolute paths or names with a `..` component;
- symbolic or hard links that escape the archive root;
- device nodes, sockets, and other special files;
- secrets, credentials, private keys, signing material, and CI state;
- debug files or native libraries that the release contract does not include.

Set stable file order, timestamps, owner and group metadata, and permission bits with the
repository's existing archive command.
Keep the executable bit on Unix targets.
Do not assume that the same archive flags work on GNU, BSD, and Windows tools.
Pin the release runner and record the archive tool version when exact archive bytes matter.

Run a programmatic gate over every archive entry and link target before extraction. Reject:

- POSIX absolute paths, Windows drive paths, UNC paths, and device paths;
- `..` traversal under both `/` and `\` separators;
- symbolic or hard-link targets that escape the archive root;
- special files and target-invalid Windows names, alternate data streams, and reserved names.

Only after that gate passes, extract into a new disposable directory with owner and permission
restoration disabled. Assert that every canonical extracted path stays below that directory.
Archive listing commands are useful for human review, but they are not the safety gate:

```bash
tar -tvf <asset>.tar.gz
unzip -Z1 <asset>.zip
```

Run the packaged executable from that directory, not from `target/`.

```bash
<extracted-path>/<binary> --version
<repository-smoke-command> <extracted-path>/<binary>
```

Run the smoke check on the matching target environment.
Check required shared libraries and system baselines there.

## Create release metadata

Generate one checksum manifest from every final immutable archive, SBOM, and provenance file.
Do not include the checksum manifest itself or its signatures.
Use SHA-256 unless repository policy requires another approved digest.
Sort the manifest by asset name and keep the conventional `<digest><two spaces><file>` format.
Generate it with the existing release command or the platform's available checksum tool.
Do not edit a checksum by hand.

Generate an SBOM for the released artifact, not only for the source workspace.
Use the repository's configured CycloneDX or SPDX generator and supported schema version.
Include the product, version, target, dependencies, and final artifact digest when the selected
format and generator support those fields.
Validate the result with the existing schema or repository command.
An SBOM lists release contents and dependencies; it does not prove where the artifact was built.

Generate provenance with the configured build platform when the repository supports it.
Bind provenance to the final artifact digest.
Record the source revision, builder identity, build invocation, relevant inputs, and output
subjects according to the selected provenance format.
Do not claim a SLSA level that the build platform and workflow do not establish.
A signature over an artifact is not a substitute for provenance.

Require an authenticated attestation or envelope from the configured build platform. Verify its
signature or bundle, expected builder workflow identity, source repository, ref and commit,
predicate type, and every subject digest. Plain provenance JSON is metadata, not verified
provenance.

Do not add a new SBOM, signing, or attestation dependency only for this release.
If the repository has no approved mechanism, report the missing control and follow its release
policy.

## Sign and verify final bytes

Use one closed authentication policy. The default policy is to sign the exact final checksum
manifest that covers every archive, SBOM, and provenance file. Consumers verify that manifest
signature and identity before they trust any listed digest. Use direct per-file signatures only
when policy requires every released file to have one; do not leave any downloaded release file
outside the authenticated set.

Sign only final files after archive creation.
Use the repository's existing key, identity-based workflow, hardware token, or signing service.
Never create or export a signing key without explicit authorization.
Remember that identity-based signing can write to an external transparency service.
Request authorization before that action.

Verify against an established trust policy:

- expected key, or expected certificate identity and issuer;
- exact artifact bytes or checksum manifest;
- required transparency proof, timestamp, or bundle;
- expected provenance subject digest and builder identity.

Do not trust a public key only because it is downloaded from the same release as the signature.
Do not accept a valid signature for an unexpected identity.
Keep detached signatures, certificates, bundles, and attestations that consumers need for offline
verification.

## Upload in a recoverable order

Verify all local assets before the first upload.
Create a draft or other non-final release state when the existing host and workflow support it.
Do not introduce a new release state only for this rule.

Upload in this order:

1. Upload the immutable binary archives.
2. Upload each SBOM and provenance file that names those archives.
3. Upload the checksum manifest.
4. Upload the signatures, certificates, or verification bundles.
5. Download draft assets through the host's authenticated asset endpoint and run remote
   verification.
6. Make the release final only after every required check passes and that finalization is
   authorized.
7. Download every file again through the unauthenticated public URL and repeat digest,
   signature, provenance, archive, and smoke checks.

Upload metadata after the files that it identifies.
Never overwrite an existing asset with different bytes.
After an upload timeout, refresh the authoritative asset list a bounded number of times, then
apply this decision per asset:

| Observed remote state | Action |
|---|---|
| Downloaded remote digest equals the local digest | Accept the upload as successful. Do not retry. |
| Asset is absent after the bounded refresh | Request authorization before one retry of the identical bytes. |
| Digest differs, download is ambiguous, or different bytes already use the name | Stop. Do not overwrite or delete without exact authorization. Use a new version after publication. |

## Verify as a consumer

For a draft, download every file through the authenticated host endpoint into a new directory.
After finalization, repeat the complete check through the public release path without release
credentials. Do not verify the local upload source in place of either download.

Check all of these facts:

- the release tag points to the approved commit;
- the remote asset set exactly matches the target matrix;
- the checksum manifest signature or every required direct signature passes the established
  identity policy before any listed digest is trusted;
- each downloaded digest matches the authenticated checksum manifest;
- each provenance attestation passes its builder and source identity policy and every subject
  matches the downloaded artifact digest;
- each SBOM identifies the expected product, version, and target;
- every archive passes the path and link safety review;
- every extracted binary reports the expected version and passes its smoke check.

Record the public asset URLs and observed digests in the completion report.

## Stop and recovery rules

Stop the release sequence when any required target fails, an archive contains an unsafe entry,
a digest differs, a signature has the wrong identity, provenance names the wrong source or
artifact, or an upload result is uncertain.

Keep an incomplete release non-final when the current workflow supports that state.
Do not delete or hide a public release without explicit authorization.
Do not replace an asset in place.
For changed bytes, create a new version under project policy and explain the superseded release.
If a leaked secret or signing key enters an asset, revoke it immediately and contact the release
host.

## Official references

- [Cargo build](https://doc.rust-lang.org/cargo/commands/cargo-build.html)
- [rustc source path remapping](https://doc.rust-lang.org/rustc/remap-source-paths.html)
- [Sigstore blob signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/)
- [Sigstore signature verification](https://docs.sigstore.dev/cosign/verifying/verify/)
- [SLSA provenance](https://slsa.dev/spec/v1.2/provenance)
- [CycloneDX specification](https://cyclonedx.org/specification/overview/)
- [SPDX specification](https://spdx.dev/use/specifications/)
