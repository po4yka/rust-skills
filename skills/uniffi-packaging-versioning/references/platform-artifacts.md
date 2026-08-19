# Platform artifacts: Android jniLibs and Apple XCFramework

Mechanics for the two packaging paths. The decision rules and the commands you
run most often are in `SKILL.md`; this file holds the detail you need when the
build breaks or when you wire it up the first time.

---

## Android

### Resolve the NDK, do not guess it

The NDK installs under the Android SDK at `<sdk>/ndk/<version>`. Pin the version
explicitly. A build system that accepts "whatever NDK is installed" produces a
different binary on every machine.

The clang drivers and the LLVM archiver live in one prebuilt toolchain
directory:

```text
<sdk>/ndk/<version>/toolchains/llvm/prebuilt/<host-tag>/bin/
```

`<host-tag>` is the build machine, not the target: `darwin-x86_64`,
`linux-x86_64`, or `windows-x86_64`. Apple Silicon hosts also use
`darwin-x86_64`; the toolchain runs under Rosetta or ships universal binaries
depending on the NDK release.

The driver name encodes the target triple and the minimum API level, for example
`aarch64-linux-android35-clang`. The API level in the driver name must match the
`minSdk` you ship. A mismatch either fails to link or produces a library that
loads only on newer devices.

### Environment variable naming rules

Two different conventions apply at once. Get both right or the link silently
uses the host linker.

| Variable | Naming rule | Example for `aarch64-linux-android` |
|----------|-------------|-------------------------------------|
| `CARGO_TARGET_<TRIPLE>_LINKER` | Triple uppercased, hyphens to underscores | `CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER` |
| `CC_<triple>` | Triple lowercased, hyphens to underscores | `CC_aarch64_linux_android` |
| `CXX_<triple>` | Same as `CC_` | `CXX_aarch64_linux_android` |
| `AR_<triple>` | Same as `CC_` | `AR_aarch64_linux_android` |

Cargo reads the `CARGO_TARGET_*_LINKER` form. The `cc` crate, used by any
dependency that compiles C or C++, reads the `CC_`/`CXX_`/`AR_` forms. Set all
four. If you set only the Cargo linker, a crate with a C dependency compiles its
C sources with the host compiler and the link fails with unresolved symbols or
an architecture mismatch.

Point `AR_*` at `llvm-ar` in the same prebuilt `bin` directory. Do not use the
host `ar`.

The full per-ABI command is in `SKILL.md`.

### Output layout

```text
<generated root>/jniLibs/
  arm64-v8a/lib<crate_name>.so
  armeabi-v7a/lib<crate_name>.so
  x86_64/lib<crate_name>.so
  x86/lib<crate_name>.so
```

Rules:

- The directory names come from the ABI table in `SKILL.md`. They are not the
  Rust target triples and not the architecture names. `arm64-v8a`, not
  `aarch64`, not `arm64`.
- The file name is `lib` plus the package name with hyphens replaced by
  underscores, plus `.so`. Do not set an explicit `[lib] name`; let it follow
  the package name so the loader lookup, the artifact name, and the crate name
  can never drift apart.
- Write into a generated directory under the build output, not into source
  control. Register that directory with the build system as a generated source
  directory of the variant, so packaging picks it up automatically.

### Build-system wiring

Whatever build system you use, hold these properties:

- **One task per variant and ABI.** Each task has exactly one target triple, one
  output file, and declared inputs. That gives you correct incremental builds
  and a usable build cache.
- **Declare the NDK path, the Rust sources, and the `Cargo.lock` as inputs.**
  A task that declares only the sources reuses a stale cache entry after an NDK
  or dependency bump.
- **Separate the per-ABI build from the merge.** Build tasks produce one `.so`
  each; one ABI-aware merge task assembles the `jniLibs` tree. The merge stays
  cacheable and cheap.
- **Different ABI policy per build type.** Debug and developer builds default to
  the single host or emulator ABI and accept an override property for a wider
  set. Release rejects a subset and builds all four. Encode this as a hard
  failure, not a warning.
- **Pass `--locked`.** A packaging build that silently updates `Cargo.lock`
  produces an artifact that does not match the committed revision.

### Host library for bindgen

The bindgen step needs a host `cdylib`, not an Android slice. Build it with the
same `cargo rustc --crate-type cdylib` form and no `--target`. On macOS the
output is `lib<crate_name>.dylib`; on Linux it is `lib<crate_name>.so`. Look up
both extensions in the regeneration script rather than branching on the
operating system.

---

## Apple

### Build the slices

Build one `staticlib` per target with `cargo rustc --crate-type staticlib`. Use
the same profile as the Android release build so that optimization and
`panic` settings match across platforms. Keep unwinding enabled in that profile.
UniFFI catches a panic at the exported call, and `panic = "abort"` disables
`catch_unwind`, so the whole process aborts instead.

Merge the two simulator architectures into one fat archive:

```bash
lipo -create \
  target/aarch64-apple-ios-sim/release/lib<crate_name>.a \
  target/x86_64-apple-ios/release/lib<crate_name>.a \
  -output <staging>/simulator/lib<crate_name>.a
```

Do not `lipo` the device archive together with a simulator archive. Both hold
the same `arm64` architecture, so `lipo` refuses the merge. Device and simulator
are different platforms in the XCFramework, not different architectures of one
slice. Pass them to `xcodebuild` as two separate `-library` arguments instead.

### Stage the headers

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

**Modulemap naming trap.** The generator emits the modulemap under a name that
has changed between UniFFI releases - `<crate_name>FFI.modulemap` in some
versions, `module.modulemap` in others. The Swift compiler discovers a modulemap
inside a framework headers directory under the name `module.modulemap`. Handle
both names in the regeneration script, normalize to one checked-in name, and
stage that name into every slice. Do not leave this as a manual rename step in a
runbook; it is forgotten exactly once and then costs an afternoon.

### Assemble

```bash
xcodebuild -create-xcframework \
  -library <staging>/device/lib<crate_name>.a \
  -headers <staging>/device/headers \
  -library <staging>/simulator/lib<crate_name>.a \
  -headers <staging>/simulator/headers \
  -output <build>/<Name>.xcframework
```

`xcodebuild` derives the slice directory names from the archives, producing
`ios-arm64` for the device slice and `ios-arm64_x86_64-simulator` for the merged
simulator slice. Delete any previous `<Name>.xcframework` before you run the
command; `-create-xcframework` fails when the output already exists.

### CI mode

A pull-request lane usually needs only proof that the Apple side still compiles
and links. Build the Apple Silicon simulator target alone and assemble a
single-slice XCFramework. Put this behind an explicit mode flag, and make the
release path fail if the flag is set. A release artifact with one slice installs
cleanly and then fails on every device.

### Swift Package Manager wiring

Reference the XCFramework as a `binaryTarget`:

```swift
// Local path target: no checksum, rebuilt in place.
.binaryTarget(
    name: "<Name>FFI",
    path: "../../<relative>/<Name>.xcframework"
)

// Remote target: checksum is mandatory and changes on every rebuild.
.binaryTarget(
    name: "<Name>FFI",
    url: "https://<host>/<Name>-<version>.xcframework.zip",
    checksum: "<sha256 from swift package compute-checksum>"
)
```

Choose the local `path:` form while the Rust core and the app live in one
repository. It removes a whole class of "forgot to update the checksum" failures
and it makes a local Rust change visible to the app after one rebuild. Move to
the remote `url:` form only when consumers are in other repositories, and then
automate the checksum update in the release job.

### Swift package layering

Split the Swift side into two packages or two targets:

1. **Generated package** - holds the generated Swift file, the `*FFI` system
   target that wraps the C header and modulemap, the `binaryTarget`, and a thin
   adapter that maps generated types onto your own protocol.
2. **Public package** - holds the actor or client type the app uses, and the
   protocol it conforms to. It depends on the port protocol, never on the
   generated types.

Do not export the generated target from the public package. Generated types that
reach SwiftUI views turn every regeneration into an app-wide refactor.
