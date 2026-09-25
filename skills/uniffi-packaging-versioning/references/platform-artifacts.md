# Platform artifacts: Android jniLibs and the Apple C module

Mechanics for the two packaging paths. The decision rules and the commands you
run most often are in `SKILL.md`. This file holds the detail you need when you
wire the build the first time or when it breaks.

Contents:

- Android: toolchain pointers, output layout, build-system wiring, the host
  library for the generator
- Apple: the UniFFI header and modulemap, `uniffi-bindgen-swift`
- Consumer layering: the generated module, the adapter, JNA, SwiftPM targets,
  Swift isolation, exhaustive arms

---

## Android

### Toolchain and environment

The `rust-android-build` skill resolves the NDK, the linker driver, and the
per-ABI API suffix from `meta/platforms.json` and `meta/abis.json`. The
`cargo-workflows` skill has the `CC_<triple>`, `CXX_<triple>`, and
`AR_<triple>` set.

### Output layout

```text
<generated root>/jniLibs/
  arm64-v8a/lib<crate_name>.so
  armeabi-v7a/lib<crate_name>.so
  x86_64/lib<crate_name>.so
  x86/lib<crate_name>.so
```

Rules:

- The directory names are the Android ABI names (the `rust-android-build`
  skill has the table). They are not the Rust target triples and not the
  architecture names. Write `arm64-v8a`, not
  `aarch64` or `arm64`.
- The file name is `lib` plus the package name with hyphens replaced by
  underscores, plus `.so`. Do not set an explicit `[lib] name`. Let it follow
  the package name, so the loader lookup, the artifact name, and the crate name
  cannot drift apart.
- Write into a generated directory under the build output, not into source
  control. Register that directory with the build system as a generated source
  directory of the variant, so packaging picks it up.

### Build-system wiring

Wire the per-ABI build tasks as the `rust-android-build` skill describes
(Gradle and jniLibs integration): task inputs, the cargo environment, the
working directory, and the ABI set per build type.

### Host library for the generator

The generator step needs a host `cdylib`, not an Android slice. Build it with
the same `cargo rustc --crate-type cdylib` form and no `--target`. The output is
`lib<crate_name>.dylib` on macOS, `lib<crate_name>.so` on Linux, and
`<crate_name>.dll` on Windows. Try all three names and require exactly one
match instead of branching on the operating system.

---

## Apple

The `rust-ios-build` skill owns the slice build environment (`SDKROOT`,
`IPHONEOS_DEPLOYMENT_TARGET`), the simulator `lipo` merge, XCFramework assembly
and inspection, SwiftPM `binaryTarget` wiring and checksums, and signing.
Follow it for those steps. Write each XCFramework to a new output path; do not
delete a path that the current build did not create. This section covers only
the files that UniFFI generates.

### Stage the header and the modulemap

Each slice needs a headers directory that holds the generated C header and a
modulemap:

```text
<staging>/device/headers/
  <crate_name>FFI.h
  module.modulemap
<staging>/simulator/headers/
  <crate_name>FFI.h
  module.modulemap
```

`uniffi-bindgen generate --language swift` writes
`<ffi_module_filename>.modulemap`. The default is `<crate_name>FFI.modulemap`,
which declares `module <crate_name>FFI`. Clang looks for a modulemap in an
XCFramework headers directory under the name `module.modulemap`, so the
regeneration script renames the file. Stage the same two files into every
slice.

The generated Swift file imports the C module behind
`#if canImport(<crate_name>FFI)`. When that module fails to build or has
another name, the import disappears without an error, and the Swift compiler
reports hundreds of `cannot find type 'RustBuffer' in scope` errors. Read the
first Clang error for the module, not the Swift errors.

### Use `uniffi-bindgen-swift` when you need modulemap control

`uniffi-bindgen-swift` generates Swift sources, headers, and modulemaps
separately. It writes one modulemap for the whole library and sets the file
name directly. Add it as a second binary behind the same feature:

```toml
[[bin]]
name = "uniffi-bindgen-swift"   # src/bin/uniffi-bindgen-swift.rs calls uniffi::uniffi_bindgen_swift()
required-features = ["cli"]
```

```bash
cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen-swift -- \
  <library> <out-dir> --swift-sources --headers --modulemap \
  --module-name <crate_name>FFI --modulemap-filename module.modulemap
```

Rules:

- Pass `--module-name` with the FFI module name that the generated Swift
  imports (default `<crate_name>FFI`). Without it the tool names the module
  after the library file stem, and the `canImport` guard hides the mismatch.
- Do not pass `--xcframework` for an XCFramework made with `-library`. That
  flag emits `framework module`, which fits only a `.framework` bundle
  (uniffi-rs #2646). The UniFFI page calls this flag XCFramework-compatible;
  that holds only for an XCFramework built from `.framework` bundles.
- The tool reads a static archive directly, so you can generate from a
  shipping `.a` slice.

---

## Consumer layering

Layer each consumer so that a regeneration touches as little code as possible:

```text
generated bindings module   <- overwritten by the generator, never edited
        |  (internal dependency)
adapter module              <- maps generated types onto your own port type
        |  (public interface)
feature modules             <- depend on the port only
```

- **Android.** Put the generated Kotlin file in its own module. Depend on it
  with `implementation` scope from the adapter only. Declare
  `net.java.dev.jna:jna:<version>@aar` (5.12.0 or later) where the code runs on
  Android.
- **Apple.** Put the generated Swift file in its own SwiftPM source target that
  depends on the XCFramework binary target. Do not add a second C target for
  the same module, because the XCFramework already carries the header and
  modulemap. Do not export the generated target from the public package.
- **Swift isolation.** Keep the generated target at the SwiftPM default
  `nonisolated` isolation. Do not add `.defaultIsolation(MainActor.self)` to it,
  and do not compile the generated file in an app target whose default actor
  isolation is `MainActor`. The generated FFI code does not compile there
  (uniffi-rs #2818).
- **Adapter arms.** Make every `when` and `switch` over generated types
  exhaustive, with no wildcard arm. A drifted binding is then a compile error,
  not silent behavior.

On a binding bump, follow the upgrade procedure in `binding-compat.md`: it
regenerates, fixes the adapter arms, rebuilds both native artifacts, and runs
the generated-binding call on a device or emulator and on a simulator.
