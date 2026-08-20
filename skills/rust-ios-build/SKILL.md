---
name: rust-ios-build
description: Use when you build, package, verify, or distribute a Rust static library for iOS outside UniFFI, including Rust for iOS, SDKROOT, IPHONEOS_DEPLOYMENT_TARGET, aarch64-apple-ios, aarch64-apple-ios-sim, target_env = "sim", C headers, modulemaps, XCFramework assembly, SwiftPM binaryTarget, compute-checksum, lipo, otool, vtool, dSYM UUID checks, iOS Simulator tests, physical-device smoke tests, code signing, or PrivacyInfo.xcprivacy.
license: BSD-3-Clause
---

# Rust iOS Build

Build a Rust `staticlib`, expose a stable C header, package device and simulator
slices as an XCFramework, and prove that a Swift consumer can link and run it.
Use this skill when the boundary does not use UniFFI.

Keep these boundaries:

- Use `rust-unsafe` for ABI layout, pointer ownership, and panic containment.
- Use `rust-native-linking` for `build.rs`, C dependencies, and linker inputs.
- Use `uniffi-packaging-versioning` when UniFFI generates the header and Swift
  bindings.
- Use `rust-debugging` to investigate a crash after symbol preservation works.

Do not add an Objective-C wrapper when Swift can import the C header directly.
Do not build a dynamic library for an app when a static library is sufficient.

## Completion evidence

Complete all applicable checks:

1. Build the exact release profile for the device and supported simulator
   targets.
2. Assemble an XCFramework from a fresh output path.
3. Inspect every slice architecture.
4. Link the XCFramework into a minimal Swift consumer.
5. Inspect the final executable deployment target and dynamic dependencies.
6. Run one exported function in an iOS Simulator.
7. Run the same function on a physical device before release.
8. Archive the exact app and preserve its matching dSYM.

`cargo check` is not completion evidence. It does not prove the final Apple
link, package, or load path.

## Select the targets

Use the Tier 2 targets that Rust distributes through `rustup`:

| Rust target | Apple platform | Required use |
| --- | --- | --- |
| `aarch64-apple-ios` | iPhone and iPad device | Release |
| `aarch64-apple-ios-sim` | Apple Silicon simulator | Development and CI |
| `x86_64-apple-ios` | Intel simulator | Only when the support matrix includes Intel hosts |

Install only the targets in the support matrix:

```bash
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

Do not detect the simulator from `target_arch = "x86_64"`. An Apple Silicon
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

Resolve the SDK with `xcrun`. Do not check an absolute SDK path into Cargo
configuration:

```bash
DEVICE_SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
SIMULATOR_SDK="$(xcrun --sdk iphonesimulator --show-sdk-path)"
```

Set one deployment target for Rust and the Xcode consumer:

```bash
export IPHONEOS_DEPLOYMENT_TARGET="<minimum-ios-version>"
```

The value must equal the Swift package or Xcode target minimum. A lower Rust
value does not make the final app support that version when the host target
requires a newer version. A higher Rust value can make Rust object files
unavailable to an otherwise supported host.

## Produce the static libraries

Keep the normal Rust library type for development. Select `staticlib` in the
packaging command when other consumers still need an `rlib`:

```toml
[lib]
crate-type = ["lib"]

[profile.ios-release]
inherits = "release"
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

Build the device and Apple Silicon simulator slices from the same lock file,
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

## Define the C module

Generate a header from the exported ABI with the repository's pinned header
generator, or maintain a small header by hand. Do not parse Rust source with a
custom script.

The header owns the public ABI version and exact integer widths:

```c
#ifndef NATIVE_CORE_H
#define NATIVE_CORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t native_core_abi_version(void);

#ifdef __cplusplus
}
#endif

#endif
```

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

Otherwise copy the Apple Silicon simulator archive to the simulator staging
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

Use a new versioned or temporary output directory. Do not delete an existing
path that was not created by the current build.

## Verify the binary, not only the directory names

Inspect each static library before distribution:

```bash
lipo -info <xcframework>/ios-arm64/libnative_core.a
lipo -info <xcframework>/ios-arm64-simulator/libnative_core.a
```

The second slice name can include `x86_64` when the simulator archive is fat.
Read `Info.plist` instead of assuming the generated directory name:

```bash
plutil -p <xcframework>/Info.plist
```

Link a minimal Swift host. Then inspect the executable that Xcode produced:

```bash
vtool -show-build <DerivedData>/Build/Products/<configuration>-iphoneos/<App>.app/<App>
otool -L <DerivedData>/Build/Products/<configuration>-iphoneos/<App>.app/<App>
```

Use `vtool` output to verify the iOS platform, minimum OS, and SDK. Use
`otool -L` to find an unexpected dynamic dependency or a non-system install
name. A static archive has no final runtime dependency table. The linked app is
the authoritative artifact for this check.

Use the Xcode link map when a required Rust symbol is absent or duplicated.
Use `nm -gU` on a slice to confirm that the public C symbol exists before you
debug Swift imports.

## Integrate with Swift Package Manager

Prefer a local binary target while the package and XCFramework share a
repository:

```swift
.binaryTarget(
    name: "NativeCore",
    path: "Artifacts/NativeCore.xcframework"
)
```

A local `path` target has no checksum. Compile a Swift target that depends on
the binary target. Import the module and call `native_core_abi_version()` in a
test or smoke screen.

Use a remote target only for a released immutable archive:

```swift
.binaryTarget(
    name: "NativeCore",
    url: "https://example.invalid/NativeCore-<version>.xcframework.zip",
    checksum: "<swift-package-checksum>"
)
```

If the release policy requires a signed XCFramework, complete the signing step
before you create the ZIP. Create the final ZIP, then compute the checksum from
those exact bytes:

```bash
swift package compute-checksum NativeCore-<version>.xcframework.zip
```

Publish the ZIP and the `Package.swift` checksum as one release operation.
Never reuse a URL for different bytes. A checksum mismatch means the archive
or manifest changed; do not bypass the check.

## Preserve symbols from the exact release

A Rust static library is not the final load image. Xcode links its object code
into the app executable. Preserve the `.xcarchive` and app dSYM from the same
archive action that produced the distributed app.

Verify the UUID pair before uploading symbols:

```bash
dwarfdump --uuid <archive>/Products/Applications/<App>.app/<App>
dwarfdump --uuid <archive>/dSYMs/<App>.app.dSYM
```

Require the UUID sets to match. Reject a dSYM from a rebuild, even when the Git
revision and version are the same. Preserve the XCFramework ZIP, lock file,
Xcode version, Rust version, app archive, and dSYM under one release identity.

Do not claim that a `.dSYM` made from the `.a` can symbolize the shipped app.
The final Xcode link assigns the app image UUID and addresses.

## Run consumer smoke tests

Run the fastest proof on a macOS CI runner:

1. Build the Apple Silicon simulator slice.
2. Assemble the XCFramework.
3. Resolve the local Swift package.
4. Build and run a simulator test that calls the ABI version function.

Use an available simulator runtime and an explicit destination selected by the
CI image:

```bash
xcrun simctl list devices available
xcodebuild test \
  -scheme <smoke-scheme> \
  -destination 'platform=iOS Simulator,name=<available-device>'
```

Before release, repeat the call on one physical device at the minimum supported
iOS version when that device is available. A simulator result does not prove
device architecture, signing, entitlement, or loader behavior.

```bash
xcodebuild test \
  -scheme <smoke-scheme> \
  -destination 'platform=iOS,id=<device-udid>'
```

Do not invent a device identity or silently select another minimum OS. Record
the device model, OS version, app version, and test result as release evidence.

## Respect signing and publishing authority

Building a Rust archive and an XCFramework does not require code signing.
Installing on a physical device, archiving an app, registering a device,
changing a development team, creating a profile, notarizing, or uploading to a
store can modify external state or use credentials.

Sign a distributed XCFramework only when the release policy requires a signed
artifact and the user authorizes use of the existing identity:

```bash
codesign --timestamp -s "<authorized-identity>" <xcframework>
codesign --verify --strict --verbose=2 <xcframework>
```

Do not create, import, replace, or revoke a signing identity to complete this
step. Keep an unsigned artifact when signing is not part of the release policy.

Before those actions:

- Confirm that the user authorized the exact external action.
- Use the existing team, bundle identifier, certificate, and profile.
- Do not enable automatic signing to make a build pass without authorization.
- Do not print certificate, account, or profile secrets.
- Stop after the requested artifact or test. Do not submit it automatically.

Treat a missing signing identity or unavailable device as a verification gap,
not as a Rust build failure.

## Route privacy manifest work

Do not add an empty `PrivacyInfo.xcprivacy` to every Rust library. First inspect
what the library and its native dependencies do.

- For an app-owned raw static library, record applicable API reasons and data
  practices in the app privacy manifest.
- A raw static-library XCFramework cannot carry a privacy resource. If a
  distributed SDK must include its own manifest, use an Xcode 15 or later static
  framework to bundle `PrivacyInfo.xcprivacy`, then package that framework.
- If the Rust library has no applicable API use or data collection, record the
  audit result. Do not invent declarations.
- Re-run the audit after a native dependency or Apple requirement changes.

The application or SDK package owner owns the manifest. Route policy questions
to current Apple documentation and the release owner. Do not infer a reason
code from a linked symbol alone.

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `building for iOS Simulator, but linking in object file built for iOS` | Device archive entered the simulator slice | Keep device and simulator libraries as separate XCFramework inputs. |
| `ld: symbol(s) not found` for the exported function | Header, symbol name, or archive is stale | Run `nm -gU`, compare the header, and rebuild all slices from one revision. |
| Swift reports `no such module` | Header or `module.modulemap` is absent from one slice | Inspect the selected slice and stage the same module files in every headers directory. |
| App supports a newer iOS version than declared | Rust and Xcode deployment targets differ | Set one minimum and verify the linked app with `vtool -show-build`. |
| SwiftPM checksum does not match | ZIP bytes changed after checksum generation | Recreate the immutable release ZIP and update its checksum atomically. |
| Simulator passes and device fails to link | Release lacks the device slice | Require `aarch64-apple-ios` in the release matrix. |
| Crash report stays unsymbolicated | dSYM came from another archive action | Compare executable and dSYM UUIDs with `dwarfdump --uuid`. |
| Device build asks for a team or profile | Signing is not configured or not authorized | Report the signing gap. Do not change account state. |
| Store validation reports privacy-manifest issues | An applicable API or SDK declaration is absent | Audit the current Apple requirements and update the owning package manifest. |

## Release gate

Fail the release when any required target is absent, a header differs between
slices, a public symbol is missing, the Swift consumer does not link, the
simulator smoke does not call Rust, the physical-device smoke is missing from
the release evidence, or the app and dSYM UUIDs differ.

Report signing, device access, or privacy review as separate external gaps.
Never weaken the artifact checks to make those gaps look green.
