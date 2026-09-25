# NDK Toolchain and Gradle Task

Read this file when you set up the NDK toolchain, compute the API level of the NDK driver, write
or change the Gradle task that builds the Rust library, or bump the NDK.

Contents: toolchain environment; API level; Gradle task; NDK upgrades.

## Toolchain environment

1. Set `sdk.dir` in `local.properties`, or export `ANDROID_HOME`. `ANDROID_SDK_ROOT` is
   deprecated ([Android environment variables](https://developer.android.com/tools/variables)).
2. Install the NDK version that the build pins, at `$ANDROID_HOME/ndk/<version>`.
3. Export `ANDROID_NDK_HOME` for the manual commands in [SKILL.md](../SKILL.md).

Call cargo directly and give it the NDK driver through `CARGO_TARGET_<TRIPLE>_LINKER`. A wrapper
such as `cargo-ndk` is optional. C build scripts read `CC_<triple>`, `CXX_<triple>`, and
`AR_<triple>`; the `cargo-workflows` skill has that set.

## API level

Compute `<api>` per ABI from the NDK metadata. Fail when the application `minSdk` is below the NDK
floor: do not build native code for devices that the manifest admits and the NDK does not support.

```bash
ndk_min=$(jq -r '.min' "$ANDROID_NDK_HOME/meta/platforms.json")
ndk_max=$(jq -r '.max' "$ANDROID_NDK_HOME/meta/platforms.json")
abi_min=$(jq -r '."arm64-v8a".min_os_version' "$ANDROID_NDK_HOME/meta/abis.json")
test "$MIN_SDK" -ge "$ndk_min" || { echo "minSdk $MIN_SDK < NDK floor $ndk_min" >&2; exit 1; }
api=$(( MIN_SDK > abi_min ? MIN_SDK : abi_min ))
api=$(( api > ndk_max ? ndk_max : api ))
test -x "$NDK_BIN/aarch64-linux-android${api}-clang" \
  || { echo "no NDK driver for API $api" >&2; exit 1; }
```

In NDK r30 both floors are 21 for the four ABIs, and drivers exist for API 21 to 37. A `minSdk`
above the NDK maximum builds against the maximum: the NDK build-system guide selects the closest
available API below the requested one.

## Gradle task

Register a Gradle task that builds the Rust library before packaging and writes a
`jniLibs`-shaped tree:

```text
<generated-dir>/jniLibs/<abi>/libnative.so
```

1. Build each ABI as its own task, so that Gradle can run them in parallel.
2. Give every ABI its own `CARGO_TARGET_DIR`. Cargo locks a target directory, so a shared one
   serializes the builds.
3. Set `CARGO_TARGET_<TRIPLE>_LINKER` per ABI from the resolved NDK path. Remove `RUSTFLAGS` and
   `CARGO_ENCODED_RUSTFLAGS` from the task environment (`environment.remove(...)`), or fail the
   task when either one is set. The Gradle daemon inherits them from the shell that started it.
4. Set the `Exec` task `workingDir` to the Rust workspace root. The default is the Gradle module
   directory, where cargo does not find `.cargo/config.toml`.
5. Pass `--locked` on every cargo call. A build that updates `Cargo.lock` is not reproducible.
6. Select the Cargo profile from a Gradle property, not from a string in a developer command.
   Release-like builds use the size profile; local builds may use the dev profile.
7. Expose an ABI-override property. Default a local debug build to one ABI: `arm64-v8a` for a
   device, `x86_64` for an emulator. CI and release builds require the full shipping matrix.
8. Declare task inputs as the production-dependency closure of the FFI crate, plus the workspace
   `Cargo.toml`, `Cargo.lock`, `.cargo/config.toml`, `rust-toolchain.toml`, and the Gradle
   properties that select the profile and the ABI set. A missing input leaves the task up to date
   after a profile or toolchain change. The whole source tree as input reruns the native task on
   every unrelated commit.
9. Wire the task into the tasks that merge native libraries, not into Kotlin compilation.
   Compiling Kotlin must not trigger a cargo build.

Build through the Gradle task, not a hand-written cargo command. The task fixes the profile, the
linker, the ABI set, and the output layout in one place, so what you verify locally is what the
app packages.

## NDK upgrades

Pin one NDK version in the build. For a bump:

1. Read the rustc Android page again. It names no NDK version, so steps 4 and 5 are the proof
   that the pinned rustc works with the new NDK.
2. Read the floors in `meta/platforms.json` and `meta/abis.json` again, and check the application
   `minSdk` against them.
3. Read the NDK changelog for page-size, header, and linker changes. NDK r28 made 16 KiB the
   default on 64-bit ABIs, stopped defining `PAGE_SIZE` there, and removed the non-NDK binder
   headers. NDK r29 made `ndk-stack` match symbols by build ID and accept
   `native-debug-symbols.zip`. NDK r30 raised the maximum sysroot API to 37.
4. Rebuild every shipped ABI and run the ELF, export, and size gates. Update the size baseline in
   a separate commit, and only with a measured reason.
5. Run the installed release smoke on every ABI family that CI can exercise.
