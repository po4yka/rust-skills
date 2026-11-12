---
name: uniffi-packaging-versioning
description: Use when packaging a Rust UniFFI crate for Android and iOS (Android .so files, generated Kotlin and Swift, the UniFFI header and modulemap) or versioning its FFI surface, including pinned uniffi and uniffi-bindgen versions, regenerated checked-in bindings, an additive or breaking change, and a load-time checksum mismatch, a RustBuffer error, or a missing native library. Also for a mobile support matrix and a mobile release proof. Not for the exported API shape (use `uniffi-boundary`), Gradle build wiring (use `rust-android-build`), or XCFramework assembly (use `rust-ios-build`).
license: BSD-3-Clause
---

# UniFFI Packaging and Versioning

Turn one UniFFI crate into Android and Apple artifacts. Keep the checked-in bindings and the
compiled library at the same revision, so that a mismatch never reaches a device.

## Verify with these checks

| Claim | Check | Run it when | A pass does not prove |
|-------|-------|-------------|-----------------------|
| Checked-in bindings match the Rust source | Regeneration script in `--check` mode, in the Rust CI lane | Every change to the FFI crate or `uniffi` version | That a prebuilt artifact is current |
| The exported API is the same on every target | `--check` with each shipping target library as input | Packaging, and after a `cfg` change | Run-time behavior |
| The packaged library loads and passes its checksums | Kotlin: `uniffiEnsureInitialized()`, then one binding call; Swift: one binding call. Run it from a consumer on each Android ABI family and an iOS simulator | Before release, and after every `uniffi` bump | Another ABI, OS version, or artifact |
| The release candidate works as shipped | Final-artifact proof and release closure in `references/release-proof.md` | Once per release candidate | Anything about a rebuilt artifact |

A host `cargo test` proves none of these claims.

## Failure triage

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `UniFFI API checksum mismatch`; on Kotlin, `ExceptionInInitializerError` with that cause, or a later `NoClassDefFoundError` for `UniffiLib` | Bindings and library from different revisions or `uniffi` versions | Regenerate with the in-crate generator from this revision's library; rebuild the artifact |
| Kotlin checksum mismatch only on an ARM32 or `arm64-v8a` device, with matching bindings and library | UniFFI device defect | Upgrade to 0.32.1 or later. Never set `omit_checksums = true` as the fix |
| `UniFFI contract version mismatch` | Bindings and scaffolding from different `uniffi` versions | Same fix as the first row |
| Kotlin `junk remaining in buffer after lifting` or `BufferUnderflowException`; Swift `UniffiInternalError.incompleteData`, `.bufferOverflow`, or `.unexpectedEnumCase` | A record field or enum variant changed without a regenerate and rebuild | Regenerate and rebuild together; add the `--check` gate |
| Native library not found at run time | Wrong ABI directory name, a missing ABI, or a renamed `.so` | Check ABI directory names and every release ABI; derive the library name from the package name |
| Works on one machine, fails on another | A global `uniffi-bindgen`, or a local formatter | Use the in-crate binary; pass `--no-format` |
| `--check` fails on whitespace or line endings only | Editor or Git settings changed the checked-in files | Normalize whitespace, line endings, and the final newline in the script |
| Hundreds of `cannot find type 'RustBuffer' in scope` in the generated Swift | The FFI Clang module did not build; `#if canImport(<crate_name>FFI)` hides the cause | Build the FFI module alone and read its first error |
| Actor-isolation errors in the generated Swift | A module with `MainActor` default isolation (uniffi-rs #2818) | Move it to a SwiftPM target with `nonisolated` isolation |
| Swift cannot find the FFI module in an XCFramework | Modulemap not named `module.modulemap`, or it declares `framework module` | Rename it in the script |

## Checksums and the record-field gap

Generated Kotlin and Swift embed one API checksum per exported function, constructor, and
method, plus a contract version. Swift checks at the first call and calls `fatalError` on a
mismatch. Kotlin on UniFFI 0.30.0 to 0.32.2 checks only inside `uniffiEnsureInitialized()`,
which a single-crate binding never calls, so a stale binding runs without an error. Call
`uniffiEnsureInitialized()` from the generated package once at startup, from the adapter
module, before the first binding call. On a mismatch, read the cause of the first
`ExceptionInInitializerError`; the later `NoClassDefFoundError` is a follow-on, not R8 and not
a missing JNA.

A record or enum enters a checksum only by its name, so a field or variant change leaves
every checksum unchanged (uniffi-rs #1789): a reorder of two fields of the same type puts
values in the wrong fields with no error. Read `references/binding-compat.md` when you
diagnose skew.

Rule: a structural change to a record, enum, or error that crosses the boundary needs
regenerated bindings (the `--check` gate) and a rebuilt library, shipped together.

## Pin the generator to the runtime

`uniffi-bindgen` must come from the same `uniffi` version as the runtime that the FFI crate
links: checksums can change between versions even when the exported API does not.

Build the generator from the FFI crate as a `uniffi-bindgen` binary behind a `cli` feature
(`cli = ["uniffi/cli"]`), and pin `uniffi` once at the workspace root with a committed
`Cargo.lock`. Do not install `uniffi-bindgen` with `cargo install`: a global binary drifts from
the lock file.

Use UniFFI 0.32.1 or later (older Kotlin can fail its checksum check on an ARM32 or
`arm64-v8a` device), and read the CHANGELOG of every version you skip. Read
`references/binding-compat.md` when you bump `uniffi`.

## Generate the bindings

Pass the built library, not a UDL file, as the generator source. The generator reads the
macro metadata in the binary, which `cfg` can change: reject `cfg` and `cfg_attr` on exported
items with a source gate, or generate and version separate bindings for each API.

```bash
cargo rustc --locked --profile release --crate-type cdylib -p <ffi-crate> --lib
cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
  generate <host library> --language kotlin --language swift --no-format --out-dir <tmp>
```

Wrap generation in one checked-in script with a `--check` mode (the default: generate into a
temporary directory, `diff`, exit non-zero on a difference) and a `--write` mode. To prove
target independence, run `--check` with each unstripped shipping library
(`target/<triple>/<profile>/lib<crate_name>.so` or `.a`) as input: a stripped `.so`, such as
the one inside an APK, gives no metadata.

Check in the generated Kotlin file, Swift file, C header, and modulemap, never hand-edit them,
and commit them with the Rust change. Read
[references/binding-compat.md](references/binding-compat.md) for the manifest, the script
contract, FFI diff review, and breaking-change coordination.

## Classify an FFI change

| Change | Class | Required action |
|--------|-------|-----------------|
| Add a function or constructor | Additive | Regenerate bindings |
| Add a method to an object | Additive unless consumers implement the generated protocol or interface (fakes) | Regenerate; update consumer implementations |
| Add a method to a foreign-implementable trait | Source-breaking for every implementation | Major bump |
| Add a record field with a generated default | Source-additive, checksum-blind | Confirm an old constructor call still compiles; ship bindings and library together |
| Add a record field without a default | Source-breaking, checksum-blind | Major bump; update every constructor call; ship together |
| Add an enum or error variant | Source-breaking for exhaustive `when` and `switch`, checksum-blind | Breaking; update consumer arms; ship together |
| Remove or rename a function, method, field, or variant | Breaking | Major bump |
| Change an argument or return type | Breaking | Major bump |
| Change a record field type or the fields of a variant | Breaking, checksum-blind | Major bump; ship together |
| Rename the package or the library file | Breaking | Major bump; the loader looks up the old name |

When in doubt, classify a change as breaking and ship bindings and library together. A
record field is additive only when UniFFI generates a default for it in every target
language.

## The artifact contract

| Consumer | Rust crate type | Artifact | Generated glue |
|----------|-----------------|----------|----------------|
| Android | `cdylib` | `lib<crate_name>.so` per ABI, under `jniLibs/<abi>/` | Kotlin file; JNA 5.12.0+ `@aar` at run time |
| Apple | `staticlib` | `<Name>.xcframework` with one slice per platform | Swift file, C header, and modulemap |
| Host (bindgen only) | `cdylib` | `lib<crate_name>.{dylib,so}` or `<crate_name>.dll` | None; generator input |

Do not commit the `.so`, `.a`, or `.xcframework`: the release job rebuilds them from the
tagged revision, and a committed artifact goes stale where `--check` does not see it.

Keep one FFI crate with every platform-facing export: one checksum set, one artifact name,
one version. Link one Rust `staticlib` into an iOS app: two UniFFI libraries in one app also
define the same C types (uniffi-rs #2802).

Under `panic = "abort"`, a panic in an export ends the process. Select the crate type on the packaging command
(`cargo rustc --crate-type cdylib` or `staticlib`), never in `[lib] crate-type`: there it makes
every `cargo build`, `clippy`, and `test` link all three artifacts. Build each slice with a
ship profile (`android-jni`, `ios-release`) that keeps `panic = "unwind"`, `strip = "none"`,
and line tables. Read [references/platform-artifacts.md](references/platform-artifacts.md)
for the manifest, the slice commands, and the iOS deployment target.

## Android: one cdylib per ABI

Copy each `target/<triple>/android-jni/lib<crate_name>.so` into
`<generated>/jniLibs/<abi>/`. Name each ABI directory with the Android ABI name exactly:
`arm64-v8a`, not `aarch64`. The packager ignores a wrong name without an error, and the
library is then missing at run time. Read `references/platform-artifacts.md` when you set up
the `jniLibs` layout, the host library for the generator, or the consumer modules.

## Apple: staticlib slices and the generated C module

Build one `staticlib` per Apple target in the support matrix, and assemble them with
`xcodebuild -create-xcframework`. Stage the generated `<crate_name>FFI.h` and the modulemap
into the headers directory of every slice, renamed to `module.modulemap` by the regeneration
script. Read `references/platform-artifacts.md` when you stage these files or need
`uniffi-bindgen-swift`. A compile-only CI lane may build `aarch64-apple-ios-sim` alone behind
an explicit mode flag; make the release path fail when the flag is set.

## Keep the generated layer internal

Put the generated bindings in their own module. Only an adapter module depends on it, and it
maps the generated types onto port types. Make every `when` and `switch` over generated types
exhaustive, with no wildcard arm, so a drifted binding is a compile error. Read the
consumer-layering section of `references/platform-artifacts.md` for the Gradle module, JNA,
and SwiftPM targets.

## Prove a release

Read `references/release-proof.md` when you define the support matrix, prove a release
candidate on its final APK, AAB, AAR, or XCFramework, or record the release closure. Do not
replace those lanes with tests against an intermediate `.so`, `.a`, or generated source.

## Related skills

When installed, the `uniffi-boundary` skill owns the exported API shape, and the
`ffi-error-progress-cancel` skill owns callbacks, progress, and cancellation.
