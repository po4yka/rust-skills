# Consumer release proof

Use this reference when a release must prove that generated Kotlin and Swift
bindings work with the exact artifacts that consumers receive. Keep ordinary
compatibility checks separate from release proof.

## Declare the support matrix

Store one versioned support-matrix document in the consumer repository. Give
each revision a stable identifier or content digest. Declare these values:

| Platform | Producer or compiler support | Runtime support |
|----------|------------------------------|-----------------|
| Android | Pinned Kotlin and Android build-tool tuple; add a floor tuple only when a reusable SDK promises consumer build-tool compatibility | Floor and current Android API levels, with ABI lanes selected by policy |
| Apple | Floor and current Swift/Xcode tuples; both compile and link at the same declared minimum iOS deployment target | Floor and current iOS runtimes, simulator or device, and architecture |

The project owns these versions. Do not copy a universal version table into
this skill. Update the project matrix when product support changes or when a
toolchain upgrade changes generated bindings.

Pin the Android generation tuple as the `uniffi` runtime, the in-crate bindgen,
and the complete `uniffi.toml`. Set `bindings.kotlin.kotlin_target_version` to
the declared Kotlin floor and include it in that tuple. Record the Kotlin and
Android build-tool versions that compile the generated file. Generated code
can change when any item in this tuple changes even when the Rust API does not.
Set `bindings.kotlin.omit_checksums = false`. An Android lane cannot pass
release proof when the generated binding omits UniFFI checksum checks.

Record Apple toolchain fields separately. Record `xcodebuild -version`,
`swift --version`, the package `swift-tools-version`, and the configured Swift
language mode. A Swift 6 compiler running Swift 5 language mode is not proof of
Swift 6 language-mode compatibility. Claim Swift 6 strict-concurrency support
only when that mode compiles the relevant generated API. Treat UniFFI async
code that is not `Sendable` as an unsupported case until the configured lane
proves it. UniFFI documents its partial Swift 6 support here:
<https://mozilla.github.io/uniffi-rs/latest/swift/overview.html#swift-6-support>.

## Keep ordinary lanes small

Use the smallest paired lanes that prove the declared contract:

1. For an Android application, compile with the pinned producer tuple. For a
   reusable SDK that promises a consumer toolchain floor, also compile with
   that floor tuple.
2. Run Android at the declared floor and current API levels. Select ABI lanes
   from the shipping policy instead of creating a second ABI list. Give every
   shipping ABI family that CI can execute at least one runtime lane. For each
   remaining shipping ABI family, retain package and device-spec inspection and
   record runtime proof as blocked or unverified. Do not report inspection as
   runtime proof.
3. Compile the Apple wrapper with the floor Swift/Xcode tuple and the current
   tuple. Use the same declared minimum deployment target in both lanes.
4. Pair the floor Apple compiler lane with the floor runtime when available,
   and pair the current compiler lane with the current runtime. The runtime OS
   can differ. The deployment target must not differ.

Do not build the Cartesian product of every Kotlin, Swift, API, iOS, ABI, and
architecture value. Add another pair only after a real compatibility boundary
appears, such as a generated-language feature, an ABI-specific defect, or a
deployment-target change. If the Android floor is below API 27, use an AVD,
another emulator provider, or a physical device. Gradle Managed Devices do not
provide that floor lane. Android documents that limit here:
<https://developer.android.com/studio/test/managed-devices>.

Compile lanes are fast compatibility checks. They can consume a local native
artifact and they do not need a device. Runtime compatibility lanes can use an
emulator. Neither lane proves a release when it consumes an intermediate
artifact.

## Prove the Android consumer artifact

Start from the final release output:

- For an application, use the signed APK or the exact AAB selected for release.
- For a reusable SDK, use the final AAR in a minimal consumer application.

Record the SHA-256 digest of the final APK, AAB, or AAR before proof starts.
For an AAB, use a pinned `bundletool` to derive the device-specific APK set from
that exact AAB. Record the `bundletool` version and device-spec digest. Compute
and record the SHA-256 digest of the lane-specific `.apks` immediately after
derivation. Verify that digest immediately before `bundletool install-apks`.
Reuse that APK set for its declared lane. Do not rebuild the AAB or derive APKs
from another AAB for a later lane. Do not use a universal APK as release proof.

Select the API and ABI lane from the project support matrix. Install the final
APK set or APK on that emulator or device. Before the call, record the actual
device API level and ABI list. Require them to match the declared lane and the
selected payload. Start the consumer and call one stable generated Kotlin
binding. Require a deterministic value that proves all of these steps:

1. Android selected the expected ABI payload.
2. The checked-in generated Kotlin binding used its pinned Android JNA
   dependency to load the packaged library.
3. The generated binding passed its UniFFI checksum checks.
4. One generated API call crossed the boundary and returned the expected
   value.

For an AAR, make the consumer depend on the final AAR through the same Gradle
path that downstream applications use. Use a clean consumer outside the
producer build. Reject `project(...)`, composite-build substitution, or a
direct dependency on the source module or its `jniLibs` directory. Inspect the
resolved dependency and require the recorded AAR digest.

Use the declared `minSdk` as the runtime floor. Require the support-matrix
floor, the release Gradle `minSdk`, and the API level encoded in the NDK linker
driver to match. Confirm that this floor is not below the minimum supported by
the pinned NDK. A successful call below the declared floor does not create a
support claim. Treat an incompatible `minSdk`, a wrong ABI selection, or a
missing packaged library as `Fail`, not `Blocked`.

Use `rust-android-build` for APK or AAB contents, ELF alignment, export
allowlists, stripping, build IDs, and native symbol evidence. Reference that
evidence from the release closure. Do not repeat those inspections here.

Android documents `bundletool` as the tool that converts an AAB into the APKs
delivered to a device and installs the matching split APKs:
<https://developer.android.com/guide/app-bundle/test>.

## Prove the Apple consumer artifact

Use the exact Swift Package dependency selected for release:

- For a local `binaryTarget(path:)`, consume the final XCFramework at that
  package-relative path. Keep the XCFramework inside the package root. A local
  binary target has no Swift Package checksum. Create a sorted manifest of each
  relative file path and SHA-256 digest in the final XCFramework, then record
  the manifest digest.
- For a remote `binaryTarget(url:checksum:)`, sign the XCFramework first when
  the release policy requires signing and signing is authorized. Put that exact
  XCFramework at the root of the final ZIP. Run `swift package
  compute-checksum` on that ZIP. Publish the immutable archive URL and the
  matching `Package.swift` checksum together. Then resolve and download the
  dependency through Swift Package Manager. Require the resolved checksum to
  match before consumer proof starts.

Make a Swift source target hold the checked-in generated `.swift` file and
depend on the XCFramework binary target. Make the test target depend on this
wrapper target. Import the high-level UniFFI module in the test. Run one stable
generated API call on a simulator lane from the support matrix. Run the same
call on a physical device at the minimum supported iOS version before release
when that device is available. A device on a newer iOS version does not replace
this lane. Require the same deterministic result in both lanes. A raw C call
does not prove the generated Swift binding.

Build with the deployment target declared by the support matrix. Do not raise
the target to match an available simulator. A successful build at a newer
target does not prove the support floor.

Use `rust-ios-build` for target slices, XCFramework assembly, deployment-target
inspection, signing, dSYM UUIDs, and symbolication evidence. Reference that
evidence from the release closure. Do not rebuild or re-sign the artifact in
this proof step.

Apple documents the XCFramework and Swift Package binary distribution
contracts here:

- <https://developer.apple.com/documentation/xcode/creating-a-multi-platform-binary-framework-bundle>
- <https://developer.apple.com/documentation/xcode/distributing-binary-frameworks-as-swift-packages>

## Record one immutable release closure

Create one release manifest after packaging and before consumer proof. Include:

- the source revision and release identifier;
- the exact `uniffi` runtime and in-crate bindgen version or revision;
- digests of generated Kotlin and Swift sources, the C header, and the
  modulemap;
- digests of the final AAB, APK, AAR, XCFramework, or remote XCFramework
  archive, as applicable, and of each lane-specific `.apks` derived from an
  AAB;
- the remote Swift Package checksum, when a remote `binaryTarget` applies;
- the pinned Rust, NDK, Android Gradle Plugin, Gradle wrapper, Kotlin, JNA, and
  `bundletool` versions, plus the actual JDK version used by each applicable
  Android lane;
- the actual Xcode build version, Swift compiler version,
  `swift-tools-version`, Swift language mode, and deployment target used by
  each applicable Apple lane;
- the support-matrix identifier or digest;
- the Android device-spec digest and selected and observed API and ABI, when
  applicable;
- references and digests for applicable Android native-symbol and Apple dSYM
  evidence;
- the runtime lane identity and test result for each required proof.

Add fields only when they identify an input, output, or required proof. Do not
turn the manifest into a copy of build logs.

Verify every digest before each proof lane. Attach results to the same release
manifest. Never rebuild, regenerate, repackage, re-sign, or re-download from a
mutable location after the manifest exists. A replacement is a new release
candidate with a new closure and new proof.

The UniFFI guide states that metadata from a library is the input for generated
bindings and that only the exact library has correct metadata when conditional
compilation applies:
<https://mozilla.github.io/uniffi-rs/latest/tutorial/foreign_language_bindings.html>.

## Report failures and blocked lanes

Use three outcomes:

| Outcome | Meaning | Release action |
|---------|---------|----------------|
| Pass | The declared lane consumed the recorded artifact and the generated binding call returned the expected value | Attach the result to the closure |
| Fail | The lane ran, but build, install, load, checksum, or binding behavior was wrong | Fix the cause and create a new release closure when any artifact changes |
| Blocked | The declared lane could not run because its device, simulator runtime, toolchain, credentials, or service was unavailable | Keep the release blocked until the same lane runs |

Do not report a blocked lane as a product failure. Do not report it as a pass.
Record the missing resource and the last completed step. A mandatory blocked
lane leaves the release candidate unverified.

Use `Blocked` only when a transient infrastructure or provisioning failure
prevents the declared toolchain from starting the lane. If the provisioned
toolchain rejects the generated bindings, consumer build, or artifact, report
`Fail`.

If the physical device at the minimum supported iOS version is unavailable,
keep that exact device proof blocked. A device on a newer iOS version does not
replace it. If the floor simulator runtime is unavailable, provision that
runtime or an equivalent declared lane. Do not run a newer runtime and silently
lower the support claim. Change the support matrix only through the product
support decision, not as a CI workaround. If artifact selection completes but
the device is unavailable, report selection as `Pass` and runtime as `Blocked`.
