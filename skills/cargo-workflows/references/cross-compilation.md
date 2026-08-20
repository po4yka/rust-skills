# Cross-Compilation and Native Build Integration

Deep material for `cargo-workflows`: target rustflags, the manual linker setup
that replaces `cargo-ndk`, XCFramework packaging, and the rules for driving
cargo from a host build system such as Gradle or Xcode.

## Put shared config at the invocation root

Cargo searches `.cargo/config.toml` from the current directory through its
ancestors. It does not start again from each workspace member. A config under
`crates/member/.cargo/` works when Cargo runs from that member and disappears
when CI runs from the workspace root.

Put shared target configuration at `<workspace>/.cargo/config.toml`. Run the
same command from the same directory in local development, CI, Gradle, and
Xcode tasks. If a member needs private config, pass `--config` explicitly and
record it as a task input.

## rustflags in `.cargo/config.toml`

Put target-wide codegen flags here. Do not put linker paths here - the host
build system knows where the NDK or SDK lives, and a checked-in absolute path
breaks on every other machine.

```toml
[target.aarch64-linux-android]
rustflags = [
  "-C", "link-arg=-Wl,-z,max-page-size=16384",
  "-C", "link-arg=-Wl,--build-id=sha1",
  "-C", "force-frame-pointers=yes",
]
```

| Flag | Why |
|------|-----|
| `-Wl,-z,max-page-size=16384` | Android 15+ devices can use a 16 KiB page size. A library linked for 4 KiB pages fails to load. |
| `-Wl,--build-id=sha1` | Emits a build ID so a stripped `.so` correlates with its unstripped symbol sidecar. |
| `-C force-frame-pointers=yes` | Keeps frame pointers for profilers and crash symbolication. |

Repeat the block for every shipping target. All four Android ABIs normally share
the same flags.

## Do not depend on `cargo-ndk`

You do not need `cargo-ndk`. Call cargo directly and set the linker through the
environment at build time:

```bash
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=<ndk>/bin/aarch64-linux-android<minSdk>-clang
export CC_aarch64_linux_android=<ndk>/bin/aarch64-linux-android<minSdk>-clang
export CXX_aarch64_linux_android=<ndk>/bin/aarch64-linux-android<minSdk>-clang++
export AR_aarch64_linux_android=<ndk>/bin/llvm-ar
cargo build --locked --target aarch64-linux-android --profile <profile>
```

The `CC_*`, `CXX_*`, and `AR_*` variables use the triple with underscores. The
`CARGO_TARGET_*_LINKER` variable uses the triple upper-cased with underscores.
Set both forms: `cc`-based build scripts read the first, cargo reads the second.

## Separate cross-compilation from test execution

`cargo test --target <triple>` builds a target test binary, then tries to run
it. Configure `target.<triple>.runner` when an emulator, device bridge, or
remote executor can run that binary:

```toml
[target.aarch64-unknown-linux-gnu]
runner = ["qemu-aarch64", "-L", "/usr/aarch64-linux-gnu"]
```

If no runner exists, report the lane as compile-only. Do not call it a test
pass. Keep target execution in a separate device or emulator lane and record
the exact artifact digest that it runs.

## iOS XCFramework packaging

1. Build the static library for `aarch64-apple-ios`, `aarch64-apple-ios-sim`,
   and `x86_64-apple-ios`.
2. Merge the two simulator archives into one fat archive with `lipo`.
3. Package the device archive and the fat simulator archive with
   `xcodebuild -create-xcframework`. The result has two slices: `ios-arm64` and
   `ios-arm64_x86_64-simulator`.
4. Distribute the XCFramework through Swift Package Manager as a local or binary
   target.

Give CI a reduced mode that builds only `aarch64-apple-ios-sim`. A full
three-target build on every pull request wastes runner time.

## Wiring a host build system to cargo

Follow these rules when a Gradle or Xcode build drives cargo:

1. Register one task per variant and ABI. Independent tasks let the build system
   schedule the ABIs in parallel.
2. Give every ABI its own `CARGO_TARGET_DIR`. A shared target directory
   serializes parallel builds on the cargo lock and can thrash the cache.
3. Merge the per-ABI outputs in a separate cacheable task that produces the
   `jniLibs`-shaped tree, then attach that directory to the variant.
4. Declare task inputs as the recursive production-dependency closure of the FFI
   crate, not the whole `crates/` directory. Otherwise an unrelated crate
   invalidates the native task on every commit. Add a test that compares the
   declared input list with the closure that `cargo metadata` reports.
5. Expose two properties: a boolean that disables native work entirely, and an
   ABI override. Default a debug build to the host or emulator ABI. Require the
   complete shipping ABI set for a release build.
6. Wire the task into the packaging tasks that consume native libraries, and
   keep it off the plain Kotlin compilation path. Compiling Kotlin must not
   trigger a cargo build.
7. Keep gates on the release path: the native library must exist, be a valid ELF
   file for its ABI, and stay under a size budget.
