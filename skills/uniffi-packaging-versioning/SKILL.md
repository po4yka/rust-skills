---
name: uniffi-packaging-versioning
description: Use when packaging a Rust UniFFI crate for Android and iOS (per-ABI Android .so files, generated Kotlin and Swift, the UniFFI header and modulemap for an XCFramework) or versioning its FFI surface, including pinning uniffi and uniffi-bindgen, regenerating checked-in bindings, classifying an exported change as additive or breaking, and debugging a load-time checksum mismatch, a RustBuffer error, or a missing native library. Also for a mobile support matrix and a mobile release proof from the shipped artifacts. Not for the exported API shape (use `uniffi-boundary`), Gradle build wiring (use `rust-android-build`), or XCFramework assembly (use `rust-ios-build`).
license: BSD-3-Clause
---

# UniFFI Packaging and Versioning

Turn one UniFFI crate into Android and Apple artifacts. Keep the checked-in
generated bindings and the compiled library at the same revision, so that a
bindings/library mismatch never reaches a device.

## Verify with these checks

| Claim | Check | Run it when | A pass does not prove |
|-------|-------|-------------|-----------------------|
| Checked-in bindings match the Rust source | Regeneration script in `--check` mode, in the Rust CI lane | Every change to the FFI crate or to the `uniffi` version | That a prebuilt artifact on a machine is current |
| The exported API is the same on every target | Generate from each shipping target library and diff against the checked-in files | Packaging, and after a `cfg` change in the FFI crate | Run-time behavior |
| The packaged library loads and passes its checksums | Kotlin: `uniffiEnsureInitialized()`, then one generated-binding call; Swift: one generated-binding call. Run it from a consumer on each shipping Android ABI family and on an iOS simulator | Before release, and after every `uniffi` bump | Another ABI, OS version, or artifact |
| The release candidate works as shipped | Final-artifact proof and release closure in `references/release-proof.md` | Once per release candidate | Anything about a rebuilt artifact |

A host `cargo check` or `cargo test` proves none of these claims.

## Failure triage

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `UniFFI API checksum mismatch`; on Kotlin, `ExceptionInInitializerError` with that cause, or a later `NoClassDefFoundError` for `UniffiLib` or `IntegrityCheckingUniffiLib` | Bindings and library from different revisions or `uniffi` versions | Regenerate with the in-crate generator from the library built at this revision; rebuild the artifact |
| Kotlin checksum mismatch only on an ARM32 or `arm64-v8a` device, with matching bindings and library | UniFFI defect in 0.30.0–0.32.0 | Upgrade to 0.32.1 or later. Never set `omit_checksums = true` as the fix |
| `UniFFI contract version mismatch` | Bindings and scaffolding from `uniffi` versions with different FFI contracts | Same fix as the first row |
| Kotlin `junk remaining in buffer after lifting` or `java.nio.BufferUnderflowException`; Swift `UniffiInternalError.incompleteData`, `.bufferOverflow`, or `.unexpectedEnumCase` (a variant from a newer library) | A record field or enum variant changed without a regenerate and rebuild | Regenerate and rebuild together; add the `--check` gate if it is missing |
| Native library not found at run time | Wrong ABI directory name, an ABI missing from the release set, or a renamed `.so` | Compare directory names with the Android ABI names; check every release ABI; derive the library name from the package name |
| Works on one machine, fails on another | A global `uniffi-bindgen`, or a formatter installed on one machine only | Use the in-crate binary everywhere; pass `--no-format` |
| `--check` fails on whitespace or line endings only | Editor or Git line-ending settings changed the checked-in files | Normalize trailing whitespace, line endings, and the final newline in the script |
| Hundreds of `cannot find type 'RustBuffer' in scope` in the generated Swift | The FFI Clang module did not build; `#if canImport(<crate_name>FFI)` hides the cause | Build the FFI module alone and read its first error; check the staged header, `module.modulemap`, and module name |
| Actor-isolation errors in the generated Swift | The file compiles in a module with `MainActor` default isolation (uniffi-rs #2818) | Move it to a SwiftPM target with the default `nonisolated` isolation |
| Swift cannot find the FFI module in an XCFramework | Modulemap not named `module.modulemap` in a slice, or it declares `framework module` | Rename it in the script; see `references/platform-artifacts.md` |

## Checksums and the record-field gap

Generated Kotlin and Swift embed one API checksum per exported function,
constructor, and method, plus a contract version. When the comparison with the
loaded library runs depends on the language:

- **Swift** checks at the first call into the library and calls `fatalError`
  on a mismatch.
- **Kotlin on UniFFI 0.30.0–0.32.2** checks only inside
  `uniffiEnsureInitialized()`. A single-crate binding never calls it, so a
  stale binding runs without an error, and `omit_checksums = false` proves
  nothing. Call `uniffiEnsureInitialized()` from the generated package
  (default `uniffi.<namespace>`) once at startup, from the adapter module,
  before the first binding call. Upstream `main` fixes this, but no release
  has the fix as of 2026-09.
- **Kotlin failure shape.** The check throws in a static initializer. Read the
  cause of the first `ExceptionInInitializerError`; the later
  `NoClassDefFoundError` (triage table) is a follow-on, not R8 stripping and
  not a missing JNA.

A hard failure is the good case.

A record or enum enters a checksum only by its name. A field or variant change
therefore leaves every checksum unchanged (uniffi-rs #1789). When new bindings
expect an added field and the library is stale, deserialization runs out of
`RustBuffer` data. In the other direction, stale bindings get an extra encoded
field and reject or ignore it, depending on the generated reader. A reorder of
two fields of the same type is the worst case: both sides read the same shape
and assign values to the wrong fields, with no error.

Rule: a structural change to a record, enum, or error that crosses the boundary
needs regenerated bindings and a rebuilt library in the same change. The
`--check` gate enforces the bindings half. Ship the bindings and the library
together for the other half.

## Pin the generator to the runtime

`uniffi-bindgen` must come from the same `uniffi` version as the runtime that
the FFI crate links. Checksums can change between versions even when the
exported API does not. UniFFI 0.31.0 removed the self type from method
checksums, so 0.30.x bindings fail against a 0.31.x library, and the reverse.

Build the generator from the FFI crate, behind a feature:

```toml
# Cargo.toml of the FFI crate
[dependencies]
uniffi = { workspace = true }   # workspace root: uniffi = "0.32.1"

[features]
# The default `cargo build/clippy/test --workspace` never compiles the CLI.
cli = ["uniffi/cli"]

[[bin]]
name = "uniffi-bindgen"         # src/bin/uniffi-bindgen.rs calls uniffi::uniffi_bindgen_main()
required-features = ["cli"]
```

Pin `uniffi` once at the workspace root and commit `Cargo.lock`. The generator
links the same locked crate, so parity holds without an `=` requirement. Do not
install `uniffi-bindgen` with `cargo install`. A global binary drifts from the
lock file and fails on one machine only.

Use UniFFI 0.32.1 or later. Generated Kotlin can fail its checksum check on a
device when bindings and library match: ARM32 release builds on 0.30.0–0.31.1
(JNA direct mapping, uniffi-rs #2740), and `arm64-v8a` on 0.31.2–0.32.0
(introduced in 0.31.2 by the ARM32 fix, reported as uniffi-rs #2939; fixed by
PR #2935 in 0.32.1). No 0.30.x or 0.31.x release is safe on both, so do not pin
a 0.31.x release as a workaround. Read the CHANGELOG for every version you
skip, patch releases included, before you bump. Read
`references/binding-compat.md` when you bump `uniffi`.

## Generate the bindings

Pass the built library, not a UDL file, as the generator source. The generator
reads the metadata that the UniFFI macros put into the binary, so only the
exact library has the correct metadata when `cfg` changes the exports. Reject
`cfg` and `cfg_attr` on exported functions, methods, records, enums, errors,
and objects with a source gate. If target-dependent exports are unavoidable,
generate and version separate bindings for each API.

```bash
# 1. Build the host library (no --target: the build machine).
cargo rustc --locked --profile release --crate-type cdylib -p <ffi-crate> --lib

# 2. Generate Kotlin and Swift. --no-format makes the output independent of
#    the ktlint and swift-format installs on this machine.
cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
  generate <host library> --language kotlin --language swift \
  --no-format --out-dir <tmp>
```

Since UniFFI 0.31 the generator detects a library path itself, and `--library`
has no effect. Omit it. Since 0.32, `--config` takes a global config file. The
generator ignores an old flat `uniffi.toml`-style file with only a warning.

Wrap generation in one checked-in script with two modes and an optional
library-path argument (the default is the host library):

- `--check` (the default): generate into a temporary directory and `diff`
  against the checked-in files. Exit non-zero on any difference.
- `--write`: overwrite the checked-in files.

The generator reads ELF, Mach-O, and PE libraries and static archives on any
host. To prove target independence, run the script in `--check` mode with each
shipping library as its input; the raw generator output always differs from
the checked-in files. Pass the unstripped
`target/<triple>/<profile>/lib<crate_name>.so` or `.a`. The generator reads ELF
metadata from the symbol table only, so a stripped `.so`, such as the one
inside an APK or AAB, gives no metadata.

Check in the generated Kotlin file, Swift file, C header, and modulemap. They
are the contract that consumers compile against, and their diff is the review
signal for an FFI change. Do not hand-edit them, because the next regeneration
discards the edit. Put a fix in the Rust crate or in the consumer adapter.
Read `references/binding-compat.md` when you write or fix the script, review an
FFI diff, or coordinate a breaking change.

Commit the regenerated files in the same commit as the Rust change. A split
commit gives `git bisect` a broken state. Run `--check` in the Rust CI lane and
make a diff block the merge.

## Classify an FFI change

| Change | Class | Required action |
|--------|-------|-----------------|
| Add a function or constructor | Additive | Regenerate bindings |
| Add a method to an object | Additive unless consumers implement the generated Swift protocol or Kotlin interface, for example in fakes | Regenerate bindings; update consumer implementations |
| Add a method to a foreign-implementable trait or callback interface | Source-breaking for every Kotlin and Swift implementation | Major bump |
| Add a record field with a generated default | Source-additive, checksum-blind | Confirm that an old constructor call still compiles in Kotlin and Swift; ship bindings and library together |
| Add a record field without a default | Source-breaking, checksum-blind | Major bump; update every constructor call; ship together |
| Add an enum or error variant | Source-breaking for exhaustive `when` and `switch`, checksum-blind | Treat as breaking; update consumer arms; ship together |
| Remove or rename a function, method, field, or variant | Breaking | Major bump; coordinate every consumer |
| Change an argument or return type | Breaking | Major bump |
| Change a record field type or the fields of a variant | Breaking, checksum-blind | Major bump; ship together |
| Rename the package or the library file | Breaking | Major bump; the loader looks up the old name |

Treat "binary-compatible" as a claim to justify, not a default. When in doubt,
classify the change as breaking and ship bindings and library together. A
record field is additive only when the selected UniFFI version generates a
default for it in every target language. The `uniffi-boundary` skill has the
default-value attribute forms.

## The artifact contract

| Consumer | Rust crate type | Artifact | Generated glue |
|----------|-----------------|----------|----------------|
| Android | `cdylib` | `lib<crate_name>.so`, one per ABI, under `jniLibs/<abi>/` | Kotlin file; JNA 5.12.0 or later in its `@aar` form at run time |
| Apple | `staticlib` | `<Name>.xcframework` with one slice per platform | Swift file, C header, and modulemap |
| Host (bindgen only) | `cdylib` | `lib<crate_name>.{dylib,so}` or `<crate_name>.dll` | None; this is the generator input |

Commit the generated glue. Do not commit the `.so`, `.a`, or `.xcframework`;
the release job rebuilds them from the tagged revision. A committed artifact
goes stale, and the `--check` gate does not catch it.

Keep one FFI crate. Put every platform-facing export in it, so there is one
checksum set, one artifact name, and one version. A second Rust `staticlib` in
the same app is likely to conflict (Rust Reference, linkage), and two UniFFI
libraries in one iOS app define the same C types (uniffi-rs #2802).

Keep unwinding in the packaging profile. UniFFI catches a panic at the exported
call, and `panic = "abort"` turns that panic into a process abort.

Select the crate type on the packaging command, not in the manifest:

```toml
# Cargo.toml of the FFI crate
[lib]
crate-type = ["lib"]   # the default. Do not add "cdylib" or "staticlib" here.
# Set no `name` key. The artifact name then follows the package name, with
# hyphens replaced by underscores.
```

```bash
# Android slice
cargo rustc --locked --profile android-jni --target aarch64-linux-android \
  --crate-type cdylib -p <ffi-crate> --lib
```

Reason: `crate-type = ["cdylib", "staticlib", "lib"]` in the manifest makes
every `cargo build`, `cargo clippy`, and `cargo test` link all three artifacts,
in every lane, including the lanes that never package.

Export `IPHONEOS_DEPLOYMENT_TARGET` once, as the "Set one deployment target"
section of the `rust-ios-build` skill shows. Then build each Apple slice with
the `--crate-type staticlib` command of that skill, which sets `SDKROOT`. If
the deployment target is not set, the C objects and the Rust objects of one
slice get different minimum iOS versions.

Declare the `android-jni` and `ios-release` profiles in the workspace
`Cargo.toml`, as the `rust-android-build` and `rust-ios-build` skills show. Each
one inherits `release`, keeps `panic = "unwind"`, sets `strip = "none"`, and
adds line tables. The default `release` profile has no line tables, and Cargo
then strips debug info, so native symbols and dSYMs get no Rust file or line
data. Keep `--profile release` only for the host
library that feeds the generator.

## Android: one cdylib per ABI

Build each ABI with the Android slice command above, and copy
`target/<triple>/android-jni/lib<crate_name>.so` into
`<generated>/jniLibs/<abi>/`. Name each ABI directory with the Android ABI name
exactly: `arm64-v8a`, not `aarch64`. The packager ignores a wrong directory
name without an error, and the library is then missing at run time. The
`rust-android-build` skill has the ABI-to-target table, the shipping ABI matrix
rule, the NDK environment, and the Gradle task that fills `jniLibs`. Read
`references/platform-artifacts.md` when you set up the `jniLibs` layout, the
host library for the generator, or the consumer modules.

## Apple: staticlib slices and the generated C module

Build one `staticlib` per Apple target in the support matrix. Follow the
`rust-ios-build` skill for the target list, the slice environment, the simulator
`lipo` merge, `xcodebuild -create-xcframework`, and SwiftPM `binaryTarget`
wiring. This skill adds the UniFFI parts:

- Stage the generated `<crate_name>FFI.h` and the modulemap into the headers
  directory of every slice. Name the modulemap file `module.modulemap`.
  `uniffi-bindgen generate` writes `<crate_name>FFI.modulemap`, so rename it in
  the regeneration script, not by hand. Read `references/platform-artifacts.md`
  when you stage these files or need `uniffi-bindgen-swift`.
- A compile-only CI lane may build `aarch64-apple-ios-sim` alone. Put that
  behind an explicit mode flag, and make the release path fail when the flag is
  set. A one-slice release fails on every device.

## Keep the generated layer internal

Put the generated bindings in their own module. Only an adapter module depends
on it, and the adapter maps the generated types onto a port type that feature
modules use. Make every `when` and `switch` over generated types exhaustive,
with no wildcard arm: a drifted binding is then a compile error, not silent
behavior. Keep the generated Swift target at the SwiftPM default `nonisolated`
isolation (uniffi-rs #2818). Read the consumer-layering section of
`references/platform-artifacts.md` when you set up the generated Gradle module,
the JNA dependency, or the SwiftPM targets.

## Prove a release

Read `references/release-proof.md` when you define the mobile support matrix,
prove a release candidate on its final APK, AAB, AAR, or XCFramework, or record
the release closure. Do not replace those lanes with tests against intermediate
`.so`, `.a`, or generated source files.

## Related skills

Other skills own the adjacent work. Use them when they are installed:

| Topic | Skill |
|-------|-------|
| Exported API shape, type mapping, errors, panics, default values | `uniffi-boundary` |
| Callbacks, progress, and cancellation across the boundary | `ffi-error-progress-cancel` |
| APK and AAB contents, NDK version and environment, packaging profile, ELF alignment, exported symbols, stripping | `rust-android-build` |
| Apple target list, slice environment, packaging profile, `lipo`, XCFramework assembly and inspection, SwiftPM `binaryTarget` checksums, signing, dSYMs | `rust-ios-build` |
| Profiles, the toolchain pin, cross-compilation targets | `cargo-workflows` |

## Sources

- <https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md>: breaking
  changes and fixes per release.
- <https://github.com/mozilla/uniffi-rs/issues/1789>: the record-field
  checksum gap.
- <https://mozilla.github.io/uniffi-rs/latest/swift/uniffi-bindgen-swift.html>:
  Swift-specific generation of sources, headers, and modulemaps.
- <https://mozilla.github.io/uniffi-rs/latest/kotlin/gradle.html>: the JNA
  dependency.
