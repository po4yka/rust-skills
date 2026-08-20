---
name: rust-android-build
description: Use when you build, verify, or package a Rust cdylib for Android - install cross-compilation targets, set up the NDK toolchain, write per-ABI rustflags in .cargo/config.toml, enforce 16 KiB page alignment, tune a size-optimized release profile, audit the exported ELF symbol set, hold .so size budgets, drive cargo from Gradle into jniLibs, produce native debug symbols, or publish a reusable AAR or Prefab package.
license: BSD-3-Clause
---

# Rust Android Build

This skill covers the build-and-verify discipline for a Rust `cdylib` that ships
inside an Android app: which rustflags go where, how to prove 16 KiB alignment
per ABI, which symbols the `.so` is allowed to export, how to hold a size
budget, and how a Gradle task drives cargo.

Version note: the NDK details below describe NDK 29 at time of writing. Check
the NDK release notes after any bump and re-verify the artifacts.

## When to use this skill

- You edit `.cargo/config.toml` for any `*-linux-android*` target.
- You edit the release profile that the Android build uses.
- You audit a built `.so` before a release.
- You review the Gradle wiring that calls cargo.
- You create native debug symbols or publish an AAR or Prefab package.
- You investigate a store rejection that cites 16 KiB alignment, a native
  crash, or an unexpected exported symbol.

## Target mapping

| Android ABI | Rust target triple |
|-------------|--------------------|
| `arm64-v8a` | `aarch64-linux-android` |
| `armeabi-v7a` | `armv7-linux-androideabi` |
| `x86_64` | `x86_64-linux-android` |
| `x86` | `i686-linux-android` |

Use `armv7-linux-androideabi` for `armeabi-v7a`. Do not write `armv7a-` in a
Cargo target position: that spelling is the NDK linker wrapper name, not a Rust
target triple. The two differ only for this ABI, and the mismatch is a common
build failure. See the linker table below.

Install the targets you ship:

```bash
rustup target add \
    aarch64-linux-android \
    armv7-linux-androideabi \
    x86_64-linux-android \
    i686-linux-android
```

## Toolchain setup

1. Point the build at the Android SDK. Set `sdk.dir` in `local.properties`, or
   export `ANDROID_SDK_ROOT`.
2. Install the NDK version that your build pins. The NDK lives at
   `$ANDROID_SDK_ROOT/ndk/<version>`.
3. Export `ANDROID_NDK_HOME` for the manual verification commands below.

The prebuilt toolchain binaries are here:

```bash
NDK_BIN="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
```

You do not need `cargo-ndk`. Call cargo directly and give it the NDK linker
through the environment:

```bash
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$NDK_BIN/aarch64-linux-android<minSdk>-clang"
cargo build --locked --target aarch64-linux-android --profile android-jni
```

The linker binary name embeds your `minSdk`. The `CARGO_TARGET_*_LINKER`
variable uses the target triple upper-cased with underscores:

| Rust target | Environment variable | Linker binary in `$NDK_BIN` |
|-------------|----------------------|-----------------------------|
| `aarch64-linux-android` | `CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER` | `aarch64-linux-android<minSdk>-clang` |
| `armv7-linux-androideabi` | `CARGO_TARGET_ARMV7_LINUX_ANDROIDEABI_LINKER` | `armv7a-linux-androideabi<minSdk>-clang` |
| `x86_64-linux-android` | `CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER` | `x86_64-linux-android<minSdk>-clang` |
| `i686-linux-android` | `CARGO_TARGET_I686_LINUX_ANDROID_LINKER` | `i686-linux-android<minSdk>-clang` |

Only `armeabi-v7a` breaks the pattern: the Rust triple starts with `armv7-` and
the NDK wrapper starts with `armv7a-`. List `$NDK_BIN` once and confirm the
exact name before you set the variable.

See `cargo-workflows` for the matching `CC_*`, `CXX_*`, and `AR_*` variables
that C build scripts read.

Do not put NDK paths in `.cargo/config.toml`. A checked-in absolute path breaks
on every other machine. The host build system knows where the NDK lives; the
config file holds codegen flags only.

## Crate setup

```toml
[lib]
crate-type = ["cdylib"]
```

`crate-type = ["cdylib"]` is mandatory. Android loads the library through
`System.loadLibrary()`, which needs a `.so`. An `rlib` is a Rust-only artifact
and produces no loadable library.

## Per-ABI rustflags

Put the codegen and link flags in `.cargo/config.toml` next to the workspace
`Cargo.toml`. Apply the same block to every Android target you ship:

```toml
[target.aarch64-linux-android]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,--build-id=sha1",
    "-C", "force-frame-pointers=yes",
]

[target.x86_64-linux-android]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,--build-id=sha1",
    "-C", "force-frame-pointers=yes",
]

[target.armv7-linux-androideabi]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,--build-id=sha1",
    "-C", "force-frame-pointers=yes",
]

[target.i686-linux-android]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,--build-id=sha1",
    "-C", "force-frame-pointers=yes",
]
```

| Flag | Why |
|------|-----|
| `-Wl,-z,max-page-size=16384` | Aligns LOAD segments to 16 KiB. A library linked for 4 KiB pages fails to load on a 16 KiB-page device. |
| `-Wl,--build-id=sha1` | Emits a build ID, so a stripped `.so` correlates with its unstripped symbol sidecar. |
| `-C force-frame-pointers=yes` | Keeps frame pointers for profilers and crash symbolication. |

Apply the alignment, build-id, and frame-pointer flags to all four targets, not
only to the 64-bit ones. A uniform block removes a whole class of "it works on
arm64 only" bugs.

## 16 KiB page-size alignment

### Status

Google Play requires 16 KiB-aligned `.so` files for new and updated apps that
target Android 15 and later, since 1 November 2025. NDK r28 and later compile
16 KiB-aligned by default. The `.cargo/config.toml` block above reinforces the
default and keeps the guarantee explicit and reviewable.

### Verification per ABI

Check the `Align` column of every LOAD segment. It must read `0x4000`:

```bash
"$NDK_BIN/llvm-readelf" -lW <build-dir>/arm64-v8a/libnative.so \
  | awk '/LOAD/ {print $NF}' \
  | sort -u
# Expected: 0x4000
```

Repeat per ABI. Require `0x4000` on `armeabi-v7a` and `x86` too, even though
those devices use 4 KiB pages. A uniform result is one assertion instead of
four.

Verify the merged native-library tree that the packaging step consumes, not one
hand-picked file. A verification script that walks `.../merged_native_libs/.../out/lib`
catches a stale artifact that a single-file check misses.

Then verify the final package. ELF segment alignment and ZIP entry alignment are
different properties. A correctly linked `.so` can still be packaged at a 4 KiB
ZIP boundary.

```bash
# Check every uncompressed native library entry in the final APK.
"$ANDROID_SDK_ROOT/build-tools/<version>/zipalign" -c -P 16 -v 4 app-release.apk

# Prove the policy that the AAB requests for Play-generated APK variants.
bundletool dump config --bundle=app-release.aab | grep PAGE_ALIGNMENT_16K

# Build the DEFAULT APK set for all supported device configurations. Do not pass
# --mode=universal here. Extract the set and check every split and standalone APK.
bundletool build-apks \
  --bundle=app-release.aab \
  --output=app-release-default.apks \
  --overwrite
unzip -q app-release-default.apks -d <default-apks-dir>
find <default-apks-dir> -name '*.apk' -print0 \
  | xargs -0 -n1 "$ANDROID_SDK_ROOT/build-tools/<version>/zipalign" -c -P 16 -v 4

# Optional local smoke artifact. This is one broad APK, not release proof for
# the split and standalone variants that Play can serve.
bundletool build-apks \
  --bundle=app-release.aab \
  --output=app-release-universal.apks \
  --mode=universal \
  --overwrite
```

Gate the release path on both layers. Fail when any shipped ELF LOAD segment is
not `0x4000`, when `zipalign` rejects a final APK, or when an AAB does not declare
`PAGE_ALIGNMENT_16K`. Check the DEFAULT APK set when CI must inspect the actual
split and standalone APK entries. A universal APK is only a local smoke artifact.
It does not cover those Play delivery variants. Do not treat a check of the
merged JNI tree as proof about the archive that ships. See
`references/elf-verification.md` for the full gate design.

### Common traps

- **A transitive C dependency compiled without the `-z` flag.** Enumerate the
  shared-library dependencies with
  `llvm-readelf -d libnative.so | grep NEEDED`, find the offender, and
  rebuild it with an explicit linker option. Use the link channel that its
  build system provides, for example `LDFLAGS=-Wl,-z,max-page-size=16384` or
  CMake `target_link_options(... PRIVATE "-Wl,-z,max-page-size=16384")`. Do not
  put a linker option in `CFLAGS`; compile-only invocations do not apply it to
  the final shared object. Crypto backends with C sources are the usual source.
- **An `mmap(addr, size, ...)` call in vendor C code where `size` is not 16 KiB
  aligned.** The kernel rounds the mapping up; the C code keeps using its
  smaller original size and reads or writes past what it believes it owns.
  Audit every `mmap` in your C dependencies.
- **A `#define PAGE_SIZE 4096` in a vendor C dependency.** NDK r29 removed
  `PAGE_SIZE` from `unistd.h` for `arm64-v8a` and `x86_64` to force this audit.
  A build failure on an undefined `PAGE_SIZE` is the correct outcome. Fix the C
  code to call `sysconf(_SC_PAGESIZE)`.

## Size-optimized release profile

Declare the profiles in the workspace `Cargo.toml`:

```toml
[profile.android-jni]
inherits = "release"
opt-level = "z"           # size beats speed for app distribution
lto = "fat"
codegen-units = 1
panic = "unwind"          # the JNI boundary needs unwind for catch_unwind
strip = "none"
debug = "line-tables-only"

[profile.android-jni-dev]
inherits = "dev"
opt-level = 1             # faster local iteration
panic = "unwind"
debug = "line-tables-only"  # symbols for on-device profiling
```

Rules:

- Keep `panic = "unwind"` in both Android profiles. A `catch_unwind` at the JNI
  boundary cannot stop a panic that aborts. See `rust-panic-safety` and
  `rust-jni`.
- Keep `strip = "none"` and `debug = "line-tables-only"`. The packaging step
  strips the shipped copy and keeps the unstripped one for symbolication. A
  profile that strips too early destroys the sidecar.
- Set `lto = "fat"` and `codegen-units = 1` together. Fat LTO with many codegen
  units gives back most of the size it saves.
- Measure `opt-level = "z"` against `"s"` and `3` on the real `.so` before you
  ship it. `"z"` is not automatically the smallest, and a compute-bound JNI path
  can prefer `3`. See `skills/rust-performance/references/build-configuration.md`.

Two link-time flags reduce size further. Add them to the `rustflags` block only
if you also verify their effect; do not document a flag that is absent from
`.cargo/config.toml`:

| Flag | Effect |
|------|--------|
| `-Wl,--gc-sections` | Dead-code elimination at link time. About 5-10% smaller. |
| `-Wl,--icf=all` | Identical code folding. Duplicate function bodies, common after generic monomorphization, collapse into one. About 5% smaller. |

For a further 20-40% reduction, build the standard library with immediate
abort. This costs you all panic messages. `-Z build-std` needs the standard
library source, so install it first:

```bash
rustup component add rust-src --toolchain nightly
cargo +nightly build --locked \
  --target aarch64-linux-android \
  --profile android-jni \
  -Z build-std=std,panic_abort \
  -Z build-std-features=panic_immediate_abort
```

`panic_immediate_abort` strips the `core::fmt::Arguments` machinery and the
unwind tables. It also breaks `catch_unwind`, so it is not compatible with a
JNI boundary that translates panics into Java exceptions. If you adopt it, keep
a second profile that inherits `release` with `panic = "unwind"` and full debug
info, and build it on a nightly soak job, so a crash report has a reproducible
binary behind it.

## ELF symbol allowlist

A shipped `.so` should export these symbols and nothing else:

- `JNI_OnLoad` and `JNI_OnUnload`.
- `Java_*` methods that follow the JNI naming convention.
- Linker-generated system symbols: `_init`, `_fini`, `__cxa_finalize`.

Verify:

```bash
"$NDK_BIN/llvm-objdump" -T <build-dir>/arm64-v8a/libnative.so \
  | awk '/ DF / && !/Java_/ && !/JNI_On/ && !/__cxa/ && !/_init/ && !/_fini/ {print}'
# Expected output: empty
```

Any extra symbol is an ABI leak. It is almost always a `pub fn` somewhere in
the workspace marked `#[unsafe(no_mangle)]` without the `Java_*` prefix. Such a
symbol exposes your Rust ABI to any process that can `dlopen` the library, and
it pins the signature: you cannot change it later without breaking whoever
bound to it.

Enforce the allowlist in the same CI script that checks alignment. Do not rely
on source visibility alone. Use a checked-in linker version script as a
defense-in-depth allowlist, wire it into the actual Android link command, and
keep the artifact check. The script prevents accidental dependency exports;
the check proves that the final `.so` used it. With `RegisterNatives`, export
only `JNI_OnLoad` and any other lifecycle entry point that the JVM resolves by
name.

## `.so` size budgets

Keep the per-ABI baseline in a checked-in JSON file and compare each build
against it. A budget that works:

| Rule | Threshold |
|------|-----------|
| Growth of one tracked library | at most 128 KiB |
| Total growth across all tracked libraries | the tighter of 2% or 256 KiB |

Keep the byte counts in the baseline file, never in prose. A number copied into
documentation goes stale on the first legitimate size change.

Audit a regression from the crate that produces the `.so`:

```bash
cargo bloat --locked --profile android-jni --target aarch64-linux-android --crates -n 30
cargo bloat --locked --profile android-jni --target aarch64-linux-android -n 30   # by function
```

Common causes:

- A generic that monomorphizes into many copies. Move the body into a
  non-generic inner function. See `rust-performance`.
- A new transitive dependency. Diff `cargo tree --locked -p <ffi-crate>`.
- An LTO regression. Confirm `lto = "fat"` is still active in the profile that
  the build actually selected.

## Gradle and jniLibs integration

Register a Gradle task that builds the Rust workspace before `preBuild` and
writes a `jniLibs`-shaped tree:

```text
<generated-dir>/jniLibs/<abi>/libnative.so
```

Rules for the task:

1. Build each ABI as its own unit so the build system can schedule them in
   parallel. Per-ABI parallel cargo invocations beat a sequential driver.
2. Give every ABI its own `CARGO_TARGET_DIR`. A shared target directory
   serializes the parallel builds on the cargo lock.
3. Set `CARGO_TARGET_<TRIPLE>_LINKER` per ABI from the resolved NDK path.
4. Always pass `--locked`. A build that silently updates `Cargo.lock` is not
   reproducible.
5. Select the Cargo profile from a Gradle property, not from a hardcoded string
   in a developer command. Release-like builds use the size-optimized profile;
   local builds may use the faster dev profile.
6. Expose an ABI-override property. Default a local debug build to one ABI -
   `arm64-v8a` for devices, `x86_64` for an emulator-heavy loop. Require the
   full shipping ABI set for CI and release builds.
7. Declare task inputs as the production-dependency closure of the FFI crate,
   not the whole source tree. Otherwise an unrelated crate invalidates the
   native task on every commit.
8. Wire the task into the packaging tasks that consume native libraries, and
   keep it off the plain Kotlin compilation path. Compiling Kotlin must not
   trigger a cargo build.

Build through the Gradle task, not through a hand-written cargo command. The
task fixes the profile, the linker, the ABI set, and the output layout in one
place, so what you verify locally is what the app packages.

## Production release packaging

Keep the unstripped Rust outputs as symbol inputs. Let the Android packaging
step strip the copies that ship. Build the app package and its native symbol
sidecar from the same release variant and invocation. Then compare the ELF
build ID for every ABI and library. File names and archive presence do not
prove that symbols match the shipped code.

Run an installed release smoke test from the final APK or from APKs generated
from the final AAB. The test must load the native library and call one stable
JNI entry point. A successful assemble task is not runtime proof.

Read `references/release-packaging.md` when you configure native debug symbols,
verify an exact release closure, test an installed package, or distribute a
reusable Android SDK as an AAR or Prefab package.

## NDK 29 specifics

NDK r29 changed these items:

- `PAGE_SIZE` is removed from `unistd.h` for `arm64-v8a` and `x86_64` when
  16 KiB mode is active. C code must call `sysconf(_SC_PAGESIZE)`.
- The LLVM toolchain moved forward. Codegen can shift `.so` size by 1-3%
  compared with r28. Re-baseline the size budget after the bump.
- Some Binder headers are removed. They were never part of the NDK ABI. A C
  dependency that includes `binder.h` must vendor the headers or fail.
- `lldb` startup fixes improve debugging of cross-compiled Rust. No change is
  needed in your build.

### NDK bump checklist

1. Check the minimum rustc version the new NDK expects and adjust
   `rust-toolchain.toml` if needed.
2. Rebuild every shipped ABI.
3. Run `llvm-readelf -lW` per `.so` and confirm the `0x4000` alignment.
4. Run the exported-symbol check per `.so`.
5. Re-run the size gate. Update the size baseline in a separate commit, and
   only when the growth is justified.
6. Run the instrumented device tests on every API level you support.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Missing `crate-type = ["cdylib"]` | Add it. An `rlib` produces no `.so`. |
| Missing 16 KiB alignment flags | Add `-Wl,-z,max-page-size=16384` to every Android target block. |
| ELF alignment passes but the packaged app fails the 16 KiB check | Run `zipalign -c -P 16 -v 4` on the final APK and inspect the AAB page-alignment policy. |
| Only a universal APK passes `zipalign` | Check `PAGE_ALIGNMENT_16K` in the AAB and build the DEFAULT APK set to inspect split and standalone variants. |
| Alignment flags on 64-bit targets only | Apply the same block to all four ABIs. |
| `panic = "abort"` in an Android profile | Use `panic = "unwind"`. The JNI boundary needs `catch_unwind`. |
| Wrong triple for `armeabi-v7a` | Use `armv7-linux-androideabi` as the Cargo target. |
| Linker not found for `armeabi-v7a` | The NDK wrapper is `armv7a-linux-androideabi<minSdk>-clang`, with the `a`. |
| NDK path in `.cargo/config.toml` | Set the linker from the build system environment instead. |
| Cargo profile hardcoded in a local command | Drive the build through the Gradle task that selects the profile. |
| Shared `CARGO_TARGET_DIR` across ABIs | Give every ABI its own target directory. |
| Gradle or NDK not configured | Set `sdk.dir` or `ANDROID_SDK_ROOT` and install the pinned NDK. |
| Size baseline numbers pasted into docs | Keep them in the checked-in baseline file. |

## Failure triage

| Symptom | Likely cause | First check |
|---------|--------------|-------------|
| `dlopen` fails at install or first load on Android 15+ | A LOAD segment is 4 KiB aligned | `llvm-readelf -lW` on every shipped `.so` |
| Alignment is correct in Rust code but wrong in the artifact | A transitive C dependency linked without the flag | `llvm-readelf -d` and `DT_NEEDED` |
| Build fails with undefined `PAGE_SIZE` | NDK r29 removed the macro on purpose | Replace with `sysconf(_SC_PAGESIZE)` |
| `UnsatisfiedLinkError` on a JNI method | The expected `Java_*` symbol is absent | `llvm-objdump -T` and grep the symbol |
| Unexpected exported symbol | A `#[unsafe(no_mangle)]` outside the JNI surface | Run the allowlist check |
| `.so` grew after a dependency change | New transitive crate or lost LTO | `cargo bloat --crates` and confirm the active profile |
| Size shifted 1-3% after an NDK bump | New LLVM codegen | Re-baseline in a separate commit |
| A panic aborts the process instead of raising a Java exception | `panic = "abort"` or `panic_immediate_abort` in the active profile | Inspect the profile that the build selected |

## Review checklist

Before you approve a change to the Android build:

- [ ] Every shipped ABI has an identical rustflags block in `.cargo/config.toml`.
- [ ] Every documented linker flag is present in the config that the build uses.
- [ ] Both Android profiles keep `panic = "unwind"`.
- [ ] `--locked` is on every cargo invocation the build system makes.
- [ ] Each ABI has its own `CARGO_TARGET_DIR`.
- [ ] The release path fails when alignment, the symbol allowlist, or the size
      budget regresses.
- [ ] The alignment gate checks every shipped ELF and the final APK or the APKs
      generated from the release AAB.
- [ ] The size baseline change, if any, is a separate commit with a reason.
- [ ] Every shipped native library has a matching symbol input with the same
      ELF build ID.
- [ ] No release `keepDebugSymbols` pattern matches a shipped Rust library, and
      no extracted final ELF contains a `.debug_*` section.
- [ ] An installed smoke test loads and calls the native library from the final
      APK or from APKs generated from the final AAB.
- [ ] A Prefab AAR contains metadata, headers, and the Rust library for every
      shipping ABI, and a clean CMake consumer links and runs it.
- [ ] Any Play or repository upload has separate explicit authorization.

## Reference

- `references/elf-verification.md` - the full verification and size-gate
  design: what to inspect, in what order, and how to wire it into CI.
- `references/release-packaging.md` - native debug symbols, exact artifact
  correlation, installed release smoke tests, and reusable AAR or Prefab SDKs.

## Related skills

- `cargo-workflows` - workspace layout, `Cargo.lock` discipline, profiles, and
  the full cross-compilation environment-variable set.
- `rust-jni` - JNI export naming, `JNIEnv` handling, and the boundary rules.
- `uniffi-packaging-versioning` - packaging a generated FFI layer for Android.
- `rust-panic-safety` - why the JNI boundary needs `catch_unwind`.
- `rust-performance` - flamegraphs, `cargo-bloat`, monomorphization audits.
- `rust-crate-architecture` - crate layering and dependency direction.
- `rust-code-style` and `rust-lints` - style and lint policy for the native
  workspace.
