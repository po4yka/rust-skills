---
name: rust-ios-build
description: Use when building, packaging, or verifying a Rust static library for iOS (Rust for iOS) - device and simulator slices, IPHONEOS_DEPLOYMENT_TARGET, C header and modulemap, XCFramework assembly, SwiftPM binaryTarget, dSYM UUID checks, simulator and device smoke tests, code signing, or PrivacyInfo.xcprivacy. Owns XCFramework and SwiftPM packaging for UniFFI builds too; UniFFI binding generation belongs to uniffi-packaging-versioning. Triggers on aarch64-apple-ios-sim, target_env = "sim", xcodebuild -create-xcframework, swift package compute-checksum, lipo, otool, or the ld message built for newer iOS version than being linked.
license: BSD-3-Clause
---

# Rust iOS Build

Build a Rust `staticlib`, expose a C header, package device and simulator
slices as an XCFramework, and prove that a Swift consumer links and runs it.

Route neighbouring work to these skills, when they are installed:

- `uniffi-packaging-versioning` generates the header, modulemap, and Swift
  sources for a UniFFI core. This skill still owns the slices, the
  XCFramework, SwiftPM, and the checks.
- `rust-swift-ffi` owns the hand-written Swift wrapper, callbacks, and Swift
  concurrency isolation.
- `rust-unsafe` owns ABI layout and pointer ownership.
- `rust-panic-safety` owns panic containment at the exported C ABI and the
  `panic` profile setting.
- `rust-native-linking` owns `build.rs`, C dependencies, and linker inputs.
- `rust-debugging` investigates a crash after symbol preservation works.

Link one Rust `staticlib` into an app. Each staticlib carries its own copy of
`std`, and the Rust Reference says that multiple Rust staticlibs "are likely to
conflict". Put every Rust crate the app needs behind one FFI crate.

Do not add an Objective-C wrapper when Swift can import the C header directly.
Do not build a dynamic library for an app when a static library is sufficient.

## Verification

Each check proves one claim. The "When" column sets how often it runs.

| Claim | Check | When | Does not prove |
| --- | --- | --- | --- |
| Rust code compiles for iOS | `cargo check --locked --target aarch64-apple-ios` | While iterating | Link, package, or load path |
| Each slice has the right platform and minimum OS | `otool -l` slice check in "Verify the slices" | Every package build | That Swift can import the module |
| The public C symbol exists | `nm -gU` on each slice | Every package build | That the header matches the symbol |
| Swift imports, links, and calls Rust | Simulator smoke test | Every package build | Device architecture, signing, entitlement, or loader behavior |
| The app records the right platform, minimum OS, and SDK | `vtool -show-build` and `otool -L` on the app | Release candidate | The minimum OS of objects inside the archive |
| The device load path and signing work | Physical-device smoke test | Release candidate | Behavior on other OS versions |
| The dSYM belongs to the shipped app | `dwarfdump --uuid` on the app and its dSYM | Release archive | Rust line data, which needs debug info in the Rust profile |

Fail the release when a required target is absent, a header differs between
slices, a row above fails, the physical-device result is missing from the
release evidence, or the app and dSYM UUIDs differ.

Report signing, device access, and privacy review as separate external gaps,
not as Rust build failures. Do not weaken an artifact check to make such a gap
look green.

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `ld: building for 'iOS-simulator', but linking in object file (...) built for 'iOS'` | A device archive entered the simulator slice | Keep device and simulator archives as separate XCFramework inputs. |
| `ld: warning: object file (...) was built for newer 'iOS-simulator' version (27.0) than being linked (17.0)` | `IPHONEOS_DEPLOYMENT_TARGET` was unset or stale for one object, often a `cc` build | Export the variable, rebuild in a fresh target directory, and repeat the `otool -l` slice check. Treat this warning as a failure. |
| `Undefined symbols for architecture arm64` names the exported function | Header, symbol name, or archive is stale | Run `nm -gU`, compare the header, and rebuild all slices from one revision. |
| Undefined `_Sec*`, `_CF*`, or C++ runtime (`__ZNSt...`, `___cxa_*`) symbols from a Rust dependency | A dependency needs a system framework or library, and a staticlib does not carry that link request | Run the `--print=native-static-libs` build and link each listed framework and library. |
| `duplicate symbol '__R...'` in two `lib*.a` archives | Two Rust staticlibs in one app; `-all_load` or `-force_load` loads both `std` copies | Build one staticlib for the app. |
| Swift reports `no such module` | Header or `module.modulemap` is absent from one slice | Inspect the selected slice and stage the same module files in every headers directory. |
| SwiftPM checksum does not match | ZIP bytes changed after checksum generation | Recreate the immutable release ZIP and update its checksum atomically. |
| Simulator passes and device fails to link | Release lacks the device slice | Require `aarch64-apple-ios` in the release matrix. |
| Crash report stays unsymbolicated | dSYM came from another archive action | Compare executable and dSYM UUIDs with `dwarfdump --uuid`. |
| Device build asks for a team or profile | Signing is not configured or not authorized | Report the signing gap. Do not change account state. |
| Store validation reports privacy-manifest issues | An applicable API or SDK declaration is absent | Audit the current Apple requirements and update the owning package manifest. |

## Respect signing and publishing authority

Building a Rust archive and an XCFramework does not require code signing.
Archiving an app and installing it on a physical device with the existing team,
bundle identifier, certificate, and profile are local actions. They need no
separate authorization.

Get authorization for the exact action before you sign a distributed
XCFramework, register a device, change the development team, create, import,
replace, or revoke a signing identity, profile, or certificate, notarize, or
upload to a store. These actions use release credentials or change account
state.

- Do not enable automatic signing or pass `-allowProvisioningUpdates` to make a
  build pass without authorization. That flag lets `xcodebuild` create
  profiles, app IDs, and certificates on the Apple Developer website.
- Do not print certificate, account, or profile secrets.
- Stop after the requested artifact or test. Do not submit it automatically.

## Select the targets

Use the Tier 2 targets that Rust distributes through `rustup`:

| Rust target | Apple platform | Required use |
| --- | --- | --- |
| `aarch64-apple-ios` | iPhone and iPad device | Release |
| `aarch64-apple-ios-sim` | Apple silicon simulator | Development and CI |
| `x86_64-apple-ios` | Intel simulator | Only when a consumer runs an x86_64 simulator |

Xcode 27 runs only on Apple silicon Macs. An x86_64 simulator now means an
Intel Mac with Xcode 26 or earlier, or a simulator under Rosetta. Install only
the targets in the support matrix:

```bash
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

Do not detect the simulator from `target_arch = "x86_64"`. An Apple silicon
simulator is `aarch64`. Use the simulator environment cfg:

```rust
pub const IS_APPLE_SIMULATOR: bool = cfg!(all(
    target_vendor = "apple",
    target_os = "ios",
    any(target_env = "sim", target_abi = "sim")
));
```

Rust 1.91 and later set `target_env = "sim"`. Earlier supported toolchains set
`target_abi = "sim"`. Keep both checks when the workspace MSRV is below 1.91.

Keep platform differences at the host boundary. Do not fork domain logic for
device and simulator builds.

## Pin the Xcode inputs

Build Apple targets on macOS with the Xcode version that the project declares.
Record that version in CI output:

```bash
xcodebuild -version
xcode-select -p
```

As of 2026-09, App Store Connect accepts only uploads built with Xcode 26 or
later and the iOS 26 SDK or later
([Apple upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)).
From April 2027, uploads need the iOS 27 SDK or later
([Apple news, 2026-09-09](https://developer.apple.com/news/?id=k1mtkt1k)).
Plan the release Xcode for the date of the upload. Xcode 26 and 27 accept iOS
deployment targets from iOS 15. Xcode 27 supports only iOS 17 or later devices
and simulators
([Xcode system requirements](https://developer.apple.com/xcode/system-requirements/)).
Choose the declared Xcode from these limits.

Resolve the SDK with `xcrun`. Do not check an absolute SDK path into Cargo
configuration:

```bash
DEVICE_SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
SIMULATOR_SDK="$(xcrun --sdk iphonesimulator --show-sdk-path)"
```

## Set one deployment target

Export one deployment target for every cargo invocation and for the Xcode
consumer:

```bash
export IPHONEOS_DEPLOYMENT_TARGET="<minimum-ios-version>"
rustc --print deployment-target --target aarch64-apple-ios
```

The value must equal the Swift package or Xcode target minimum. The `rustc`
command prints the value that rustc uses.

When the variable is unset, the objects in one slice disagree. rustc builds
Rust objects for iOS 10.0 (device) or 14.0 (arm64 simulator). The `cc` crate
builds C objects for the SDK version, for example 27.0 with Xcode 27. The
linked app still records the app minimum, so `vtool` on the app does not show
the mismatch. The linker prints only a warning, and the C object can call an
API that the minimum OS does not have.

Cargo does not rebuild a crate when only this variable changes (measured with
Cargo 1.98.1). A crate whose `cc` build script reruns is rebuilt. Other crates
can keep their old objects, so one archive can mix minimums. After you change
the value, build in a fresh `CARGO_TARGET_DIR`. The `otool -l` slice check
finds a stale object only when its minimum is above the new value.

## Produce the static libraries

Keep the normal Rust library type for development. Select `staticlib` in the
packaging command when other consumers still need an `rlib`:

```toml
[lib]
crate-type = ["lib"]

[profile.ios-release]
inherits = "release"
panic = "unwind"            # catch_unwind at the C ABI and in UniFFI scaffolding needs unwind
debug = 1
strip = "none"
```

Export a small C ABI. Keep Rust types, panics, and allocator ownership behind
the boundary:

```rust
#[unsafe(no_mangle)]
pub extern "C" fn native_core_abi_version() -> u32 {
    1
}
```

Build the device and Apple silicon simulator slices from the same lock file,
profile, and deployment target:

```bash
SDKROOT="$DEVICE_SDK" \
  cargo rustc --locked --profile ios-release \
  --target aarch64-apple-ios --crate-type staticlib \
  -p <ffi-crate> --lib

SDKROOT="$SIMULATOR_SDK" \
  cargo rustc --locked --profile ios-release \
  --target aarch64-apple-ios-sim --crate-type staticlib \
  -p <ffi-crate> --lib
```

Build `x86_64-apple-ios` with the simulator SDK only when the support matrix
requires it. Never merge a device archive with a simulator archive. Both can
contain `arm64`, but they are different Apple platforms.

The paths below assume the default target directory. When `CARGO_TARGET_DIR`
or `build.target-dir` is set, read `target_directory` from
`cargo metadata --format-version 1 --no-deps`. Otherwise an old archive under
`target/` can enter the package.

A staticlib does not carry the system libraries and frameworks that its
dependencies link. Print the list after a dependency change:

```bash
SDKROOT="$DEVICE_SDK" \
  cargo rustc --locked --profile ios-release \
  --target aarch64-apple-ios --crate-type staticlib \
  -p <ffi-crate> --lib -- --print=native-static-libs
```

The `note: native-static-libs:` line lists the linker inputs. Xcode links
`-lSystem`, `-lc`, and `-lm` without help. Add each `-framework <Name>` and
each other `-l<name>` to the consumer, for example `-lc++` from a C++ build
script. In SwiftPM, put `.linkedFramework("<Name>")` and
`.linkedLibrary("<name>")` in `linkerSettings` on the Swift target that depends
on the binary target. A `binaryTarget` has no linker settings.

## Define the C module

Generate a header from the exported ABI with the repository's pinned header
generator, or maintain a small header by hand. Do not parse Rust source with a
custom script.

Declare the functions in `native_core.h` with `<stdint.h>` fixed-width types
and `extern "C"` guards for C++ consumers. The header owns the public ABI
version, for example `uint32_t native_core_abi_version(void);`.

Expose the header through a modulemap:

```text
module NativeCore {
  header "native_core.h"
  export *
}
```

Stage the same header and `module.modulemap` beside every library slice. Fail
the package build when generated headers differ from their checked-in form.

## Assemble the XCFramework

When Intel simulator support is required, merge only the two simulator
archives:

```bash
lipo -create \
  target/aarch64-apple-ios-sim/ios-release/libnative_core.a \
  target/x86_64-apple-ios/ios-release/libnative_core.a \
  -output <staging>/simulator/libnative_core.a
```

Otherwise copy the Apple silicon simulator archive to the simulator staging
directory. Keep separate header directories for the two Apple platforms:

```text
<staging>/device/headers/native_core.h
<staging>/device/headers/module.modulemap
<staging>/simulator/headers/native_core.h
<staging>/simulator/headers/module.modulemap
```

Create the package at a new path:

```bash
xcodebuild -create-xcframework \
  -library <staging>/device/libnative_core.a \
  -headers <staging>/device/headers \
  -library <staging>/simulator/libnative_core.a \
  -headers <staging>/simulator/headers \
  -output <output>/NativeCore.xcframework
```

Use a new versioned or temporary output directory. `xcodebuild` refuses to
write into an existing XCFramework. Do not delete an existing path that the
current build did not create.

## Verify the slices

Read `Info.plist` instead of assuming the generated directory names. Xcode 27
names the slices `ios-arm64` and `ios-arm64-simulator`. A fat simulator slice
has `x86_64` in its name:

```bash
plutil -p <xcframework>/Info.plist
lipo -info <xcframework>/ios-arm64-simulator/libnative_core.a
```

`lipo -info` prints `arm64` for the device and the simulator slice alike. It
proves only the architectures, for example `x86_64` in a fat simulator slice.

Check the platform and minimum OS of every object. Run the check for each
slice:

```bash
otool -l <xcframework>/ios-arm64/libnative_core.a \
  | grep -A3 -E 'cmd LC_(BUILD_VERSION|VERSION_MIN_IPHONEOS)' \
  | grep -E '^ *(platform|minos|version) ' | sort | uniq -c
```

- The device slice shows `platform 2` (iOS) and never `platform 7`.
- The simulator slice shows `platform 7` (iOS Simulator) and never
  `platform 2`.
- An object built for an old minimum, such as a prebuilt `std` object at 10.0,
  has `LC_VERSION_MIN_IPHONEOS` and shows `version` instead of `minos`.
- Every `minos` and `version` value is at or below the app minimum. The
  prebuilt `std` objects keep the rustc default, which is correct.

Use `nm -gU` on a slice to confirm that the public C symbol exists before you
debug Swift imports. Use the Xcode link map when a required Rust symbol is
absent or duplicated.

Link a minimal Swift host. Then inspect the executable that Xcode produced.
`vtool` rejects a static archive with "file is not mach-o", and a static
archive has no dynamic dependency table, so the linked app is the artifact:

```bash
vtool -show-build <DerivedData>/Build/Products/<configuration>-iphoneos/<App>.app/<App>
otool -L <DerivedData>/Build/Products/<configuration>-iphoneos/<App>.app/<App>
```

`vtool` shows the platform, minimum OS, and SDK of the app. `otool -L` shows an
unexpected dynamic dependency or a non-system install name.

## Integrate with Swift Package Manager

Prefer a local binary target while the package and XCFramework share a
repository:

```swift
.binaryTarget(
    name: "NativeCore",
    path: "Artifacts/NativeCore.xcframework"
)
```

Name the binary target after the module in the modulemap, because Apple
requires the two names to match. A local `path` target
has no checksum. Compile a Swift target that depends on the binary target.
Import the module and call `native_core_abi_version()` in a test or smoke
screen.

Read [references/release.md](references/release.md) when you publish a remote
binary target, sign the XCFramework, preserve release symbols, or decide where
a privacy manifest belongs.

## Run consumer smoke tests

Run the fastest proof on a macOS CI runner:

1. Build the Apple silicon simulator slice.
2. Assemble the XCFramework.
3. Resolve the local Swift package.
4. Build and run a simulator test that calls the ABI version function.

Pick an installed device and the runtime nearest the minimum iOS version. Pin
the runtime with `OS=`, because the destination defaults to the latest runtime:

```bash
xcrun simctl list runtimes available
xcrun simctl list devices available
xcodebuild test \
  -scheme <smoke-scheme> \
  -destination 'platform=iOS Simulator,name=<available-device>,OS=<runtime-version>'
```

Before release, repeat the call on one physical device at the minimum supported
iOS version when that device is available:

```bash
xcodebuild test \
  -scheme <smoke-scheme> \
  -destination 'platform=iOS,id=<device-udid>'
```

A minimum below iOS 17 needs an Xcode 26.x lane on a macOS 26 host. Xcode 27
cannot run tests on an older device or simulator, and Xcode 26.x does not
support macOS 27. When no such lane exists, report the minimum-OS check as
blocked by the toolchain. Do not report a run on a newer OS as the minimum-OS
result. Do not invent a device identity. Record the device model, OS version,
app version, and test result as release evidence.
