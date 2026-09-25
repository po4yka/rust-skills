---
name: rust-android-build
description: Use when building, verifying, or packaging a Rust cdylib for Android - NDK linker setup and per-ABI rustflags in .cargo/config.toml, 16 KiB page alignment and the Play 16 KB page size check, exported ELF symbols, .so size budgets, a Gradle task that fills jniLibs, native debug symbols, installed release smoke tests, or a reusable AAR or Prefab package. Not for JNI function code; use rust-jni.
license: BSD-3-Clause
---

# Rust Android Build

As of 2026-09, the current NDK LTS is r30 (`30.0.16248370`,
[NDK downloads](https://developer.android.com/ndk/downloads)). Rust supports the most recent NDK
LTS ([rustc Android platform page](https://doc.rust-lang.org/rustc/platform-support/android.html)),
and that page names no NDK version. Check both pages again after an NDK or Rust toolchain bump.

## Release gates

Each claim has one check. A green check proves its own row only.

| Claim | Check | It does not prove |
|-------|-------|-------------------|
| Every 64-bit LOAD segment is 16 KiB aligned | `llvm-readelf -lW` on every shipped `.so` | ZIP alignment inside the package |
| Uncompressed native entries are 16 KiB ZIP aligned | `zipalign -c -P 16 -v 4` on the final APK or the default APK set | Native load on a 16 KB device |
| The app loads without 16 KB backcompat mode | Installed smoke on a 16 KB device with backcompat off | Other ABIs |
| The `.so` exports only its boundary | Dynamic-symbol allowlist diff | That the Java names match |
| The library loads and a JNI call works | Installed release smoke from the final APK or AAB | Symbol correlation |
| Crash symbols match the shipped code | GNU build-ID comparison, shipped copy against retained input | Symbol completeness |
| Size stays in budget | Size gate against the checked-in baseline | Speed |

Run the ELF, export, and size gates in one repository script against the merged native-library
tree. Run the package and device checks against the final artifact. A check of the merged
`jniLibs` tree proves nothing about the archive that ships, and a successful assemble task is not
runtime proof. Build the package and its native symbols in one release invocation; file names and
archive presence do not prove that symbols match the shipped code. When no 16 KB emulator image or
device is available, report the device rows as not run; do not report the release gate as passed.

The size gate compares each build against a checked-in per-ABI baseline of byte counts. The
default thresholds are at most 128 KiB growth for one tracked library, and total growth across all
tracked libraries of at most the tighter of 2% or 256 KiB; tune them per product. Keep byte counts
in the baseline file, not in prose, and update the baseline in a separate commit that states the
reason.

Read [references/elf-verification.md](references/elf-verification.md) when you write or change the
gate script, or when the size gate fails: it has the audit commands and the linker size flags.
Read [references/release-packaging.md](references/release-packaging.md) when you configure native
debug symbols, prove a release closure, run the installed smoke, or publish an AAR or Prefab
package.

Get separate explicit authorization before a Play Console upload, a symbol upload, or a repository
publish. Local builds, signing for a local smoke, and inspection need none.

## Failure triage

| Symptom | Likely cause | First check or fix |
|---------|--------------|--------------------|
| Final Android build produced no `.so` | No `cdylib` crate type | Pass `--crate-type cdylib` to `cargo rustc`, or declare it in the manifest |
| `--target armv7a-linux-androideabi` fails | NDK driver name used as the Rust target | Use `armv7-linux-androideabi` |
| Linker not found for `armeabi-v7a` | Driver name without the `a`, or no driver for that API level | `ls "$NDK_BIN" \| grep armv7a`, then recompute `<api>` |
| `dlopen` fails, or the device shows a 16 KB backcompat warning | A 64-bit LOAD segment is `0x1000`, or an uncompressed library sits at a 4 KiB ZIP offset | The ELF check, then the package check |
| The `rustc` line from `cargo build -v` lacks the alignment or build-ID flag | `RUSTFLAGS` or `CARGO_ENCODED_RUSTFLAGS` is set, or cargo ran outside the workspace root and did not read the config file | Unset the variable, or run cargo from the workspace root (see [Link flags](#link-flags-in-cargoconfigtoml)) |
| One `.so` in the tree is `0x1000` on a 64-bit ABI | A prebuilt shared library linked without the flag | Rebuild it with a linker option |
| ELF check passes, package check fails | Uncompressed libraries at a 4 KiB ZIP offset | AGP 8.5.1 or later, or `useLegacyPackaging = true` |
| Only a universal APK passes `zipalign` | Split and standalone variants not checked | Build and check the default APK set |
| Build fails with undefined `PAGE_SIZE` | NDK r28 and later do not define it on 64-bit ABIs | Call `sysconf(_SC_PAGESIZE)` |
| Link fails with `version script assignment of 'global' to symbol ... failed: symbol not defined` | A user version script names an absent symbol | Remove the version script |
| Unexpected exported symbol | An `#[unsafe(no_mangle)]` item outside the boundary, maybe in a dependency | Allowlist diff, then remove it at the source |
| `UnsatisfiedLinkError` on a JNI method | Expected `Java_*` export is absent or misnamed | `comm -13` of the allowlist files; the `rust-jni` skill owns naming |
| No build-ID note in the `.so` | `--build-id=sha1` absent for that target | `llvm-readelf -n` and the config tables |
| AGP cannot extract native debug metadata | Cargo stripped the input | `strip = "none"` in the selected profile |
| `.so` grew after a dependency change | New transitive crate, or lost LTO | The selected profile, then `llvm-nm --size-sort` on the unstripped `.so` or `cargo bloat --crates` on a `cdylib` package |
| A panic aborts instead of raising a Java exception | `panic = "abort"`, or the nightly `panic = "immediate-abort"`, in the selected profile | Inspect the profile that the build selected |
| Parallel ABI builds run one after another | A shared `CARGO_TARGET_DIR` | One target directory per ABI |

## Link flags in `.cargo/config.toml`

Put the Android link flags in `.cargo/config.toml` at the workspace root. Cargo reads config
files from the current directory upward, not from the `--manifest-path` directory. Run every
Android cargo invocation from the workspace root or below it, or cargo drops these flags without a
message. Two `cfg` tables cover every Android target:

```toml
[target.'cfg(target_os = "android")']
rustflags = ["-C", "link-arg=-Wl,--build-id=sha1"]

[target.'cfg(all(target_os = "android", any(target_arch = "aarch64", target_arch = "x86_64")))']
rustflags = ["-C", "link-arg=-Wl,-z,max-page-size=16384"]
```

Cargo joins the `rustflags` of every matching `[target.<triple>]` and `[target.<cfg>]` table. A
profiling addition in a triple table therefore adds to these flags; the `rust-performance` skill
owns `force-frame-pointers`. A matching target table also makes Cargo ignore `build.rustflags`.
Copy any `build.rustflags` entry that Android builds need into the cfg table.

| Flag | Why |
|------|-----|
| `-Wl,--build-id=sha1` | The NDK driver adds no build ID to a Rust link. Without one, a stripped `.so` cannot be matched to its symbol file. Do not pass a plain `--build-id`: LLD then writes an 8-byte ID that the Android Studio LLDB does not recognize. |
| `-Wl,-z,max-page-size=16384` | Aligns LOAD segments to 16 KiB on `arm64-v8a` and `x86_64`. NDK r28 and later do this by default for those ABIs; the flag keeps the rule explicit and reviewable. On NDK r27 or older, also pass `-Wl,-z,common-page-size=16384`, or upgrade the NDK. |

The NDK driver links `armeabi-v7a` and `x86` at 4 KiB (`0x1000`), and the NDK plans no 16 KiB page
size for 32-bit ABIs. Apply the 16 KiB flag there only as a stated project policy, and then gate
on it.

A `RUSTFLAGS` or `CARGO_ENCODED_RUSTFLAGS` environment variable replaces every config `rustflags`
entry. It does not add to them. Even `RUSTFLAGS=""` removes both flags. The build ID then
disappears without a message, and so does the alignment flag on NDK r27 or older and on 32-bit
ABIs under a 16 KiB policy. Never set or inherit either variable in the Gradle task or CI job that
builds the shipped library. To deny warnings, use `CARGO_BUILD_WARNINGS=deny` (Cargo 1.97+)
instead of `RUSTFLAGS=-Dwarnings`.

## 16 KiB page size

### Policy as of 2026-09

The [page-size guide](https://developer.android.com/guide/practices/page-sizes) (updated
2026-09-16) requires apps that target API 35 or higher to support 16 KB pages on 64-bit devices.
From 2027-02-01, Play blocks an app update that does not. New phone apps and updates must target
API 36 since 2026-08-31
([target API rules](https://developer.android.com/google/play/requirements/target-sdk)), so every
phone release is in scope. Read both pages again before a release decision.

A device with a 16 KB kernel can run a non-compliant app in 16 KB backcompat mode and warn the
user. A misaligned library therefore does not always fail to load, and a smoke test on that device
can pass. The `android:pageSizeCompat` manifest attribute turns backcompat mode on or off for one
app and suppresses the warning. Fail the release gate when the merged release manifest sets
`android:pageSizeCompat="enabled"`, because a library manifest can add it.

### ELF check

Set `NDK_BIN` once for every NDK tool command in this skill. The macOS NDK uses `darwin-x86_64` on
Apple silicon too.

```bash
NDK_BIN="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
"$NDK_BIN/llvm-readelf" -lW <lib-dir>/arm64-v8a/libnative.so \
  | awk '/LOAD/ {print $NF}' \
  | sort -u
# Expected on arm64-v8a and x86_64: one line, 0x4000.
# A larger power of two, such as 0x10000, also passes.
```

Run it on every shipped `.so` in the merged native-library tree. On a 32-bit ABI, expect `0x1000`
unless the project policy requires `0x4000`.

### Package check

A correctly linked `.so` can still sit at a 4 KiB ZIP offset. Use `zipalign` from build-tools 35.0.0 or later; older
versions do not have `-P 16`.

```bash
ZIPALIGN="$ANDROID_HOME/build-tools/<35.0.0-or-later>/zipalign"
"$ZIPALIGN" -c -P 16 -v 4 app-release.apk            # a final APK

# An AAB: prove the requested alignment, then check every APK in the DEFAULT set.
# Do not pass --mode=universal here.
bundletool dump config --bundle=app-release.aab | grep PAGE_ALIGNMENT_16K
bundletool build-apks --bundle=app-release.aab \
  --output=app-release-default.apks --overwrite
unzip -q app-release-default.apks -d <default-apks-dir>
find <default-apks-dir> -name '*.apk' -print0 \
  | xargs -0 -n1 "$ZIPALIGN" -c -P 16 -v 4
```

A universal APK is a local smoke artifact only. It does not cover the split and standalone APKs
that Play can serve. Fail the gate when an AAB with uncompressed native libraries does not declare
`PAGE_ALIGNMENT_16K`. AGP 8.5.1 and later align uncompressed native libraries at 16 KiB. On an
older AGP, upgrade, or set `packaging.jniLibs.useLegacyPackaging = true` so that the libraries
ship compressed and the device extracts them at install.

### Device check

The static checks do not prove the runtime path. When no 16 KB emulator image or device is
available, report the device rows as not run; do not report the release gate as passed. On a
16 KB emulator image or device, run these commands before you install the app:

```bash
adb shell getconf PAGE_SIZE     # must print 16384
adb shell setprop bionic.linker.16kb.app_compat.enabled false
adb shell setprop pm.16kb.app_compat.disabled true
test "$(adb shell getprop bionic.linker.16kb.app_compat.enabled)" = false
test "$(adb shell getprop pm.16kb.app_compat.disabled)" = true
```

Fail when a read-back differs: `setprop` can fail on a user build without root. On Android 17 or
later, set `fatal` instead of `false` so that a misaligned library aborts at load, and expect
`fatal`. Then run the installed release smoke from
[references/release-packaging.md](references/release-packaging.md).

### Common traps

- A prebuilt `.so` that ships next to the Rust library (a `DT_NEEDED` entry or a `jniLibs`
  sibling) keeps its own alignment. A static C archive linked into the Rust `cdylib` takes the
  final link's alignment. Rebuild a prebuilt with a linker option in its own build system; a
  linker option in `CFLAGS` does not reach the final link.
- An `mmap` or `mprotect` size that assumes a 4096-byte page is not 16 KiB aligned. The kernel
  rounds the mapping up, and the code keeps using its smaller size. Read the page size at run
  time: `sysconf(_SC_PAGESIZE)` in C, `libc::sysconf(libc::_SC_PAGESIZE)` in Rust.
- For an undefined `PAGE_SIZE` in C code on a 64-bit ABI, replace the macro with
  `sysconf(_SC_PAGESIZE)`. Do not define `__BIONIC_DEPRECATED_PAGE_SIZE_MACRO`, because it
  restores `4096` and hides the bug.

## Release profile

Declare the profiles in the workspace `Cargo.toml`:

```toml
[profile.android-jni]
inherits = "release"
opt-level = "z"             # measure against "s" and 3
lto = "fat"
codegen-units = 1
panic = "unwind"            # catch_unwind at the JNI boundary needs unwind
strip = "none"              # packaging strips the shipped copy
debug = "line-tables-only"

[profile.android-jni-dev]
inherits = "dev"
opt-level = 1               # faster local iteration
panic = "unwind"
debug = "line-tables-only"  # no debugger variables; use true for an LLDB session
```

- Keep `panic = "unwind"` in every Android profile when the boundary contract turns a panic into a
  Java exception or an error value. With `panic = "abort"` or the nightly
  `panic = "immediate-abort"`, `catch_unwind` cannot run, and a panic kills the app process. Use an
  aborting profile only when the production contract accepts process termination, and do not call
  it panic containment. The `rust-panic-safety` skill owns the boundary policy.
- Keep `strip = "none"`. The packaging step strips the shipped copy and extracts symbols from the
  unstripped input. A Cargo-stripped input destroys the symbol file.
- Measure `opt-level` (`"z"`, `"s"`, `3`), `lto`, and `codegen-units` changes on the real `.so`
  with the size gate. `"z"` is not always the smallest. `"s"` and `"z"` both disable loop
  vectorization, so a compute-bound JNI path can need `3`. The `rust-performance` skill has the
  measurement workflow.
- Do not add `-Wl,--gc-sections`: rustc already passes it for a `cdylib`. Use `-Wl,--icf=all` only
  after a size measurement, and only when no linked C or C++ code compares function addresses.

## Exported symbols

rustc owns the export list of a `cdylib`. It passes its own `-Wl,--version-script` and
`-Wl,--no-undefined-version`, and it exports every `#[unsafe(no_mangle)]` and
`#[unsafe(export_name)]` item in the crate graph, even one in a dependency that the library never
calls, under fat LTO too. A checked-in `--version-script` does not narrow that list: with Rust
1.98.1 and NDK r30 `ld.lld`, `global: Java_*; local: *;` left a `#[unsafe(no_mangle)]` helper
exported, and a map that names an absent symbol, such as `JNI_OnUnload`, breaks the link. Do not
add a version script. Remove a leak at its source: delete the attribute, or turn off the
dependency feature that adds it.

The allowed set depends on the boundary:

- JNI name-based binding: `JNI_OnLoad` and `JNI_OnUnload` when the crate defines them, and the
  `Java_*` methods.
- `RegisterNatives`: `JNI_OnLoad`, and `JNI_OnUnload` when defined. Registered methods need no
  exported name.
- UniFFI: the functions that the generated C header declares, plus the `UNIFFI_META_*` data
  symbols that the UniFFI macros export, plus `JNI_OnLoad` when the crate defines one to seed
  `JavaVM::singleton()` for callback threads. The header does not declare the `UNIFFI_META_*`
  symbols, and uniffi-bindgen reads them from the unstripped library, so do not remove them.

Derive `expected-exports.txt` from the JNI registration table or the UniFFI header. For UniFFI, add
the `UNIFFI_META_*` names from the dynamic symbols of the same build, and `JNI_OnLoad` when the
crate defines it. Sort the file, and compare it with the defined dynamic symbols of each final
`.so`:

```bash
"$NDK_BIN/llvm-readelf" --dyn-syms --wide <lib-dir>/arm64-v8a/libnative.so \
  | awk '$5 ~ /^(GLOBAL|WEAK)$/ && $7 != "UND" && $4 ~ /^(FUNC|OBJECT)$/ {print $8}' \
  | sort -u > actual-exports.txt
comm -23 actual-exports.txt expected-exports.txt > unexpected-exports.txt
comm -13 actual-exports.txt expected-exports.txt > missing-exports.txt
test ! -s unexpected-exports.txt && test ! -s missing-exports.txt
```

The filter keeps data symbols (`OBJECT`, for example a `#[unsafe(no_mangle)] pub static`) and drops
imports (`UND`) such as `__cxa_finalize`. An unexpected symbol is an ABI leak: any process that
can `dlopen` the library can call it, and it pins the signature. A missing name-based export fails
at run time with `UnsatisfiedLinkError`.

## Gradle and jniLibs integration

Build the shipped library through one Gradle task per ABI that writes
`<generated-dir>/jniLibs/<abi>/libnative.so`, not through a hand-written cargo command. Give each
ABI its own `CARGO_TARGET_DIR`, and pass `--locked` on every cargo call. Remove both rustflags
variables from the task environment, because the Gradle daemon inherits them from its shell, and
set the `Exec` task `workingDir` to the workspace root. Read
[references/ndk-and-gradle.md](references/ndk-and-gradle.md) when you write or change the task.

## Targets and linker

| Android ABI | Rust target | Linker variable | NDK driver in `$NDK_BIN` |
|-------------|-------------|-----------------|--------------------------|
| `arm64-v8a` | `aarch64-linux-android` | `CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER` | `aarch64-linux-android<api>-clang` |
| `armeabi-v7a` | `armv7-linux-androideabi` | `CARGO_TARGET_ARMV7_LINUX_ANDROIDEABI_LINKER` | `armv7a-linux-androideabi<api>-clang` |
| `x86_64` | `x86_64-linux-android` | `CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER` | `x86_64-linux-android<api>-clang` |
| `x86` | `i686-linux-android` | `CARGO_TARGET_I686_LINUX_ANDROID_LINKER` | `i686-linux-android<api>-clang` |

Only `armeabi-v7a` breaks the pattern. The Rust target starts with `armv7-`, and the NDK driver
starts with `armv7a-`. Do not write `armv7a-` in a Cargo target position.

Store one project-owned shipping ABI matrix. Local builds can select a declared subset; CI and
release builds must build the complete matrix.

```bash
rustup target add aarch64-linux-android armv7-linux-androideabi \
    x86_64-linux-android i686-linux-android
```

Keep `crate-type = ["lib"]` under `[lib]` in `Cargo.toml`, and select the `cdylib` per invocation.
A plain `cargo build` of that package writes only an rlib and never runs the NDK linker. Set
`NDK_BIN` as in the [ELF check](#elf-check).

```bash
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$NDK_BIN/aarch64-linux-android<api>-clang"
cargo rustc --locked --target aarch64-linux-android --profile android-jni \
  --crate-type cdylib -p <ffi-crate> --lib
```

Declare `crate-type = ["cdylib"]` in the manifest only when every supported build of that package
must link the Android artifact.

Compute `<api>` per ABI from the NDK metadata, and fail when the application `minSdk` is below the
NDK floor. Pin one NDK version in the build. Do not put NDK paths in `.cargo/config.toml`: a
checked-in absolute path breaks on every other machine, so the config file holds flags only. Read
[references/ndk-and-gradle.md](references/ndk-and-gradle.md) when you set up the NDK toolchain,
compute `<api>`, or bump the NDK.

## Related skills

Use these skills when they are installed:

- `cargo-workflows`: `Cargo.lock` policy, profiles, and the full cross-compilation variable set.
- `rust-jni`: JNI export naming, `JNIEnv` handling, and `JNI_OnLoad`.
- `rust-panic-safety`: the panic policy at the JNI boundary.
- `uniffi-packaging-versioning`: packaging a generated UniFFI layer.
- `rust-performance`: profiling additions such as frame pointers, `simpleperf`, and size audits.
- `rust-debugging`: tombstones and symbolication of a native crash.
