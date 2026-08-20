---
name: uniffi-packaging-versioning
description: Use when you package a Rust UniFFI core as native artifacts for mobile consumers - per-ABI Android cdylib .so files, an iOS XCFramework assembled from staticlib slices, and generated Kotlin and Swift bindings - or when you version the FFI surface - pin the uniffi runtime against uniffi-bindgen, classify an exported API change as additive or breaking, keep checked-in bindings in step with the library, or debug a load-time checksum mismatch, a RustBuffer deserialization panic, or a missing native library.
license: BSD-3-Clause
---

# UniFFI Packaging and Versioning

This skill covers two jobs that must stay in step:

1. **Packaging.** Turn one Rust FFI crate into distributable native artifacts -
   a `cdylib` `.so` per Android ABI, and a `staticlib`-based XCFramework for
   Apple platforms.
2. **Versioning.** Keep the generated binding surface and the compiled library
   at the same revision, so a bindings/library mismatch never reaches users.

Related skills: `uniffi-boundary` owns the exported API surface, type mapping,
and error taxonomy. `ffi-error-progress-cancel` owns callbacks, progress, and
cancellation across the boundary. `cargo-workflows` owns profiles, the toolchain
pin, and cross-compilation targets. `rust-android-build` and `rust-jni` cover
the wider Android native build. Use this skill for the artifact contract and the
compatibility rules between them.

---

## When to use this skill

- You add, rename, or remove any `#[uniffi::export]` function, record, enum, or
  error variant.
- You ship a new version of the Rust core to an Android or iOS consumer.
- You investigate a `RustBuffer` deserialization panic, a "wrong number of
  fields" error, or a checksum error at library load after a native update.
- You set up a fresh developer machine or CI runner to build native artifacts.
- You must decide whether an FFI change is source-compatible,
  binary-compatible, or a breaking bump.

---

## The artifact contract

| Consumer | Rust crate type | Artifact | Generated glue |
|----------|-----------------|----------|----------------|
| Android | `cdylib` | `lib<crate_name>.so`, one per ABI, under `jniLibs/<abi>/` | Kotlin file plus JNA at runtime |
| Apple | `staticlib` | `<Name>.xcframework` with one slice per platform | Swift file plus a C header and a modulemap |
| Host (bindgen only) | `cdylib` | `lib<crate_name>.{dylib,so}` for the build machine | none - this is the bindgen input |

Keep **one** FFI crate. Do not create a second `cdylib` crate for a second
consumer. All platform-facing surface lives in the single crate, so there is one
checksum, one artifact name, and one version to reason about.

### Select the crate type at build time, not in the manifest

Leave the manifest at the default library type and pass `--crate-type` on the
packaging command:

```toml
# Cargo.toml of the FFI crate.
[lib]
crate-type = ["lib"]   # the default. Do not add "cdylib" or "staticlib" here.
# Set no `name` key. The artifact name then follows the package name, with
# hyphens replaced by underscores.
```

```bash
# Android slice
cargo rustc --locked --profile release --target aarch64-linux-android \
  --crate-type cdylib -p <ffi-crate> --lib

# Apple slice
cargo rustc --locked --profile release --target aarch64-apple-ios \
  --crate-type staticlib -p <ffi-crate> --lib
```

Why: a manifest that declares `crate-type = ["cdylib", "staticlib", "lib"]`
makes every ordinary `cargo build`, `cargo clippy`, and `cargo test` link all
three artifacts. That cost lands on every developer and every CI lane, including
the ones that never package anything. Keep normal builds at the Rust `lib` type
and select the packaging type explicitly.

---

## Android: one cdylib per ABI

Ship **all** release ABIs together. A release that omits an ABI silently
degrades every device on it. A debug or developer build may build a single host
or emulator ABI to keep the loop fast, but the release path must reject a
subset.

| Android ABI | Rust target triple |
|-------------|--------------------|
| `arm64-v8a` | `aarch64-linux-android` |
| `armeabi-v7a` | `armv7-linux-androideabi` |
| `x86_64` | `x86_64-linux-android` |
| `x86` | `i686-linux-android` |

The ABI directory names must match the table exactly. `arm64-v8a` is correct;
`aarch64` is not. The packager silently ignores a wrong directory name, and the
library is then missing at run time.

Two ways to drive the cross-compile:

- **`cargo-ndk`** - a wrapper that resolves the NDK toolchain and sets the
  linker environment for you. Fewer moving parts; you depend on the wrapper
  being installed on every machine and CI runner.
- **Direct `cargo rustc` with explicit NDK linker environment** - no extra tool
  to install or version, at the cost of setting the variables yourself. Prefer
  this when the build system (for example a Gradle task) already resolves the
  pinned NDK path from the configured SDK.

The direct form, per ABI:

```bash
# example: arm64-v8a, NDK prebuilt toolchain at $NDK_BIN
CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=$NDK_BIN/aarch64-linux-android<api>-clang \
CC_aarch64_linux_android=$NDK_BIN/aarch64-linux-android<api>-clang \
CXX_aarch64_linux_android=$NDK_BIN/aarch64-linux-android<api>-clang++ \
AR_aarch64_linux_android=$NDK_BIN/llvm-ar \
cargo rustc --locked --profile release --target aarch64-linux-android \
  --crate-type cdylib -p <ffi-crate> --lib
```

Then copy `target/<triple>/release/lib<crate_name>.so` into
`<generated>/jniLibs/<abi>/`, and register that directory as a generated source
directory of the variant so the build system packages it. Do not commit the
`.so` files.

See `references/platform-artifacts.md` for the environment-variable naming
rules, the NDK layout, and build-system wiring.

---

## Apple: staticlib slices to XCFramework

Build one `staticlib` per Apple target, then assemble the slices:

| Target triple | Slice |
|---------------|-------|
| `aarch64-apple-ios` | device |
| `aarch64-apple-ios-sim` | Apple Silicon simulator |
| `x86_64-apple-ios` | Intel simulator |

`lipo`-merge the two simulator targets into one fat slice
(`ios-arm64_x86_64-simulator`), then run `xcodebuild -create-xcframework` over
the device archive and the fat simulator archive. Stage the generated C header
and the modulemap into each slice's `Headers/` directory.

A CI lane that only needs a compile check can build the Apple Silicon simulator
target alone. Keep that behind an explicit mode flag so a release build cannot
take the short path by accident.

Reference the result from Swift Package Manager as a `binaryTarget`:

- A **local `path:`** target needs no checksum. Rebuild the XCFramework in place
  and SPM picks it up.
- A **remote `url:`** target requires a `checksum:` value. Every rebuild changes
  the archive, so the checksum must be regenerated and committed with it.

See `references/platform-artifacts.md` for the full assembly sequence, header
staging, and the modulemap naming trap.

---

## Binding generation

Generate bindings from the **built host library**, not from a UDL file and not
from a device slice. The exported API and its checksums are
platform-independent, so the host `cdylib` is the correct and fastest input.

```bash
# 1. build the host library (no --target: this is the build machine)
cargo rustc --locked --profile release --crate-type cdylib -p <ffi-crate> --lib

# 2. generate both languages from that one library
cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
  generate --library <host lib<crate_name>.{dylib,so}> \
  --language kotlin --out-dir <tmp>

cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
  generate --library <host lib<crate_name>.{dylib,so}> \
  --language swift --out-dir <tmp>
```

Wrap both calls in one checked-in script with two modes:

- `--write` - overwrite the checked-in generated files.
- `--check` (make this the default) - generate into a temporary directory and
  `diff` against the checked-in files. Exit non-zero on any difference.

The script must also normalize trailing whitespace and the final newline.
Without that, formatter settings differ between machines and the `--check` gate
fails on noise.

**Check in the generated bindings.** They are the contract that the consumer
compiles against, and the diff is the review signal that an FFI change happened.

---

## Version pinning: uniffi runtime == uniffi-bindgen

The `uniffi-bindgen` binary must come from the **same revision** as the `uniffi`
crate that the FFI crate links. A mismatch between the generator and the runtime
causes checksum failures at library load even when the exported API did not
change (uniffi-rs issue #1190).

Guarantee this structurally: build the generator **from the FFI crate itself**,
behind a feature gate. There is then no separate binary to version and no
dev-dependency to drift.

```toml
# Cargo.toml of the FFI crate
[dependencies]
uniffi = { workspace = true }   # for example: uniffi = "0.31" at the workspace root

[features]
# Pull in the bindgen CLI dependencies only when explicitly enabled, so the
# default `cargo build/clippy/test --workspace` never compiles them.
cli = ["uniffi/cli"]

[[bin]]
name = "uniffi-bindgen"         # src/bin/uniffi-bindgen.rs -> uniffi::uniffi_bindgen_main()
required-features = ["cli"]
```

Pin `uniffi` once at the workspace level and let `Cargo.lock` freeze the patch
release. Because the generator links that same pinned crate, generator/runtime
parity holds without an `=` version specifier.

Do not install `uniffi-bindgen` globally with `cargo install`. A globally
installed binary drifts from the workspace pin the moment either side moves, and
the failure appears as an unexplained checksum error on one machine only.

---

## API checksums and the record-field gap

UniFFI computes an **API checksum** for exported functions and types. The
generated Kotlin and Swift verify these checksums against the loaded library at
startup. A mismatch raises a hard error immediately. That is the good case:
loud, at load time, before any data moves.

The gap: **checksums do not cover record field additions** (uniffi-rs issue
#1789). If new bindings expect an added field but the loaded library is stale,
deserialization exhausts the old `RustBuffer`. In the other direction, stale
bindings receive an extra encoded field and can reject or ignore trailing data,
depending on the generated reader and UniFFI version. A type-compatible field
reorder is worse: both sides can consume the same number and shape of values but
assign them to the wrong fields without a checksum error.

Issue #333 is a different skew mode. It reports inscrutable undefined symbols
when generated interface sides are out of date at link time. It is not evidence
for the record-field checksum gap.

**Rule.** Any structural change to a record, enum, or error that crosses the
boundary requires an **atomic** regenerate-plus-rebuild before the artifact is
committed. Enforce it with the `--check` diff gate in CI; do not rely on
reviewer attention.

---

## Semver classification for FFI changes

| Change | Compatibility class | Required action |
|--------|--------------------|-----------------|
| Add a required field to an exported record | **Source-breaking** and checksum-blind | Major bump; regenerate bindings, rebuild the library, and update every constructor call in the same change |
| Add a record field with a supported generated default | Source-additive but checksum-blind | Verify the default in every target language; regenerate bindings and rebuild the library in the same commit |
| Add a new exported function or method | Additive | Regenerate bindings |
| Remove or rename a function, method, or field | **Breaking** | Major bump; coordinate with every consumer |
| Change an argument or return type | **Breaking** | Major bump |
| Add, remove, or change an error variant | **Breaking** | Major bump |
| Rename an enum variant | **Breaking** | Major bump |
| Change the crate name or the library file name | **Breaking** | Major bump; the loader looks up the old name |

Treat "binary-compatible" as a claim you must justify, not a default. When in
doubt, classify the change as breaking and ship bindings and library together.
Generated Kotlin and Swift constructors expose record fields as parameters. A
new required parameter breaks existing source calls. Classify it as additive
only when the selected UniFFI version generates a supported default for every
target and an old constructor call still compiles in each binding language.

---

## Regeneration discipline

1. Make the Rust change in the FFI crate.
2. Run the regeneration script in `--write` mode. It builds the host library,
   runs the in-crate bindgen for Kotlin **and** Swift, normalizes whitespace,
   and overwrites every checked-in generated file: the Kotlin file, the Swift
   file, the C header, and the modulemap.
3. Commit the regenerated files **with** the Rust change, in one commit. Never
   split them across commits; a bisect then lands on a broken state.
4. Keep the `--check` mode in the CI lane that builds Rust. A diff blocks the
   merge.

Never merge an FFI change without the regenerated bindings. The gate catches the
violation, but the discipline avoids the wasted CI cycle.

---

## Consumer-side changes on a binding bump

Layer the consumer so that a regeneration touches as little code as possible.

```text
generated bindings module   <- overwritten by the generator, never edited
        |  (internal dependency)
adapter module              <- maps generated types onto your own port type
        |  (public interface)
feature modules             <- depend on the port only
```

Keep the generated types **internal** to the adapter module. Use an
`implementation`-scope dependency on Android and a non-exported target on Apple,
so generated symbols cannot leak into UI code. Make the adapter's `when` and
`switch` arms exhaustive and explicit: a drifted binding is then a compile error
or a failing test, never a silent mismatch.

### Android

- Regenerate. The new Kotlin replaces the checked-in file in the bindings
  module.
- The bindings module is a plain JVM/Kotlin module. It needs the JNA dependency
  in its Android form at run time.
- Update the adapter if a type changed. Fix the exhaustive arms the compiler
  now rejects.
- Feature modules that depend only on your port interface are unaffected unless
  the port itself changed.
- Run the adapter unit tests and the FFI smoke test on a device or emulator.

### Apple

- Regenerate. The new Swift file, the C header, and the modulemap replace the
  checked-in copies.
- Update the adapter target and any public actor or protocol whose shape
  changed.
- Rebuild the XCFramework. With a local `path:` binaryTarget there is no
  checksum to update. With a remote `url:` binaryTarget, recompute and commit
  the checksum.
- Run the integration tests that link against the rebuilt XCFramework.

---

## Failure triage

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Checksum error at library load | Bindings and library from different revisions, or generator/runtime version skew | Regenerate from the host library built at the current revision; confirm the generator is the in-crate feature-gated binary |
| `RustBuffer` deserialization panic, or "wrong number of fields" | A record gained or lost a field without regeneration - the checksum-blind case | Regenerate and rebuild atomically; add the `--check` gate if it is missing |
| Native library not found at run time | Wrong ABI directory name, missing ABI in the release set, or a renamed `.so` | Compare the directory names against the ABI table; verify every release ABI is present; keep the library name derived from the package name |
| Works on one machine, fails on another | A globally installed `uniffi-bindgen` on one of them | Remove the global install; use the in-crate binary everywhere |
| `--check` gate fails but the diff looks empty | Trailing whitespace or final-newline difference | Normalize both in the regeneration script |
| Apple build cannot find the FFI module | Modulemap staged under the wrong name in a slice's `Headers/` | See the modulemap naming rules in `references/platform-artifacts.md` |
| Simulator run fails, device build passes | Simulator slice missing an architecture from the `lipo` merge | Rebuild both simulator targets and re-merge |

---

## Rules

- **Never ship mismatched bindings and library.** The `--check` diff gate and
  the load-time checksum both exist to prevent this. Neither covers record
  fields, so the atomic-commit rule is the real defence.
- **Build every release ABI.** A subset degrades excluded devices silently.
- **Do not rename the shared library.** The loader looks up
  `lib<crate_name>.so`, derived from the package name with hyphens replaced by
  underscores. Renaming it is a breaking change.
- **Do not hand-edit generated bindings.** The next regeneration discards the
  edit. Put the fix in the Rust crate or in the adapter layer.
- **Do not commit build outputs.** Commit the generated bindings; never commit
  the `.so`, `.a`, or `.xcframework`.
- **No panics across the boundary.** Every fallible exported function returns
  `Result<_, E>` with a `#[derive(uniffi::Error)]` error type. See
  `uniffi-boundary` for the mapping rules and `rust-panic-safety` for catching
  panics before they reach the boundary.
- **One FFI crate.** Additional `cdylib` crates multiply the artifacts,
  checksums, and version skew you must track.

---

## External references

- <https://mozilla.github.io/uniffi-rs/latest/swift/xcode.html> - UniFFI Swift
  and Xcode integration guide.
- <https://github.com/mozilla/uniffi-rs/issues/1789> - record-field checksum
  gap.
- <https://github.com/mozilla/uniffi-rs/issues/333> - linker diagnostics when
  generated interface sides are out of date.
- <https://github.com/mozilla/uniffi-rs/issues/1190> - uniffi runtime and
  bindgen version pinning.
- <https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md> - breaking
  changes per minor version. Read it before every uniffi bump.
- <https://github.com/ianthetechie/uniffi-starter> - end-to-end UniFFI plus
  XCFramework example. It uses `cargo-ndk` for the Android slices.

---

## References in this skill

- `references/platform-artifacts.md` - Android NDK linker environment, jniLibs
  layout, build-system wiring, XCFramework assembly, header and modulemap
  staging, SPM binaryTarget wiring.
- `references/binding-compat.md` - checksum mechanics, the regeneration script
  contract, the CI gate, and a review checklist for FFI changes.
