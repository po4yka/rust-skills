# Native Artifact Verification and Size Gate

Deep material for `rust-android-build`: what to inspect in a built `.so`, in
what order, and how to turn the checks into a release gate.

All commands use the NDK LLVM binaries. Resolve them once:

```bash
NDK_BIN="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
```

Substitute your own library name for `libnative.so`.

## What to verify, and in what order

Run the checks in this order. Each one is cheaper than the next, and an early
failure makes the later results meaningless.

| Order | Check | Tool | Pass condition |
|-------|-------|------|----------------|
| 1 | The file exists for every shipped ABI | `test -f` | One `.so` per ABI directory |
| 2 | The file is an ELF shared object for the right machine | `llvm-readelf -h` | `Type: DYN`, machine matches the ABI |
| 3 | LOAD segment alignment | `llvm-readelf -lW` | Every LOAD segment aligns to `0x4000` |
| 4 | Shared-library dependencies | `llvm-readelf -d` | Only NDK-provided libraries in `DT_NEEDED` |
| 5 | Exported dynamic symbols | `llvm-objdump -T` | Only the allowlist |
| 6 | Build ID present | `llvm-readelf -n` | A `GNU` build-id note exists |
| 7 | Size against baseline | `stat` plus a baseline file | Inside the budget |

Point the checks at the merged native-library tree that the packaging step
consumes. A check against one hand-picked build directory can pass while the
packaged tree still holds a stale artifact. The gate inspects the merged JNI
library tree; it does not open or validate an APK or AAB archive.

## 1-2. File presence and ELF header

```bash
"$NDK_BIN/llvm-readelf" -h <lib-dir>/arm64-v8a/libnative.so | grep -E 'Type|Machine'
# Type:    DYN (Shared object file)
# Machine: AArch64
```

Expected machine per ABI:

| ABI | `Machine` |
|-----|-----------|
| `arm64-v8a` | `AArch64` |
| `armeabi-v7a` | `ARM` |
| `x86_64` | `Advanced Micro Devices X86-64` |
| `x86` | `Intel 80386` |

A machine mismatch means a build wrote the wrong triple into the wrong ABI
directory. That normally comes from a shared `CARGO_TARGET_DIR` across parallel
per-ABI builds.

## 3. 16 KiB LOAD segment alignment

```bash
"$NDK_BIN/llvm-readelf" -lW <lib-dir>/arm64-v8a/libnative.so \
  | awk '/LOAD/ {print $NF}' \
  | sort -u
# Expected: 0x4000
```

The last column of a `readelf -lW` program-header line is the alignment.
`sort -u` must print exactly one value, `0x4000`. More than one value means one
segment kept the 4 KiB default.

Run this for every shipped ABI, including the 32-bit ones. A uniform
requirement gives you one assertion to write and one result to read.

## 4. Shared-library dependencies

```bash
"$NDK_BIN/llvm-readelf" -d <lib-dir>/arm64-v8a/libnative.so | grep NEEDED
```

Use this list to find the C dependency that broke alignment. A crypto backend
with C sources is the usual offender. Rebuild that dependency with an explicit
`CFLAGS=-Wl,-z,max-page-size=16384`.

An entry that is not provided by the NDK or bundled in the same `jniLibs`
directory fails at load time on a device, not on your machine.

## 5. Exported symbol allowlist

Allowed:

- `JNI_OnLoad`, `JNI_OnUnload`
- `Java_*`
- `_init`, `_fini`, `__cxa_finalize`

```bash
"$NDK_BIN/llvm-objdump" -T <lib-dir>/arm64-v8a/libnative.so \
  | awk '/ DF / && !/Java_/ && !/JNI_On/ && !/__cxa/ && !/_init/ && !/_fini/ {print}'
# Expected output: empty
```

The ` DF ` filter selects dynamic function symbols. Any line that survives the
filter is an exported Rust function that no caller on the Java side needs.

Fix at the source, not at the linker. Find the `#[unsafe(no_mangle)]` item and
remove the attribute, or rename it into the `Java_*` surface if it really is a
JNI method. A linker version script hides the symptom while the item keeps
being generated.

## 6. Build ID

```bash
"$NDK_BIN/llvm-readelf" -n <lib-dir>/arm64-v8a/libnative.so | grep -A1 'GNU'
```

The build ID links a stripped shipped library to its unstripped sidecar. Without
it, a crash report from the field cannot be symbolicated. The
`-Wl,--build-id=sha1` rustflag produces it.

## 7. Size gate

Keep a checked-in baseline file that maps library name and ABI to a byte count.
Compare each build against it:

| Rule | Threshold |
|------|-----------|
| Growth of one tracked library | at most 128 KiB |
| Total growth across all tracked libraries | the tighter of 2% or 256 KiB |

Two rules are needed. The per-library rule catches one crate that ballooned.
The total rule catches many small increases that each pass the per-library rule.

Do not copy byte counts into documentation. Read them from the baseline file.

Update the baseline in a separate commit that states the reason. A baseline
update mixed into a feature commit hides the growth from review.

## Wiring the gate into CI

1. Run the checks against the merged native-library tree, after the merge task
   and before packaging.
2. Fail the job on any check, do not warn. A warning in a native build gets
   ignored until a store review rejects the release.
3. Print the offending file, ABI, and measured value on failure. A gate that
   prints only "failed" costs an extra debugging round trip.
4. Run the full ABI set on the release path. A pull-request job may verify one
   ABI to save runner time, but the release path must verify all of them.
5. Keep the gate script in the repository, not in the CI configuration. You
   need to run it locally with the same logic that CI uses.

## Triage table

| Symptom | Cause | Action |
|---------|-------|--------|
| `sort -u` prints `0x1000` and `0x4000` | One object linked without the flag | Find it through `DT_NEEDED`, rebuild with the flag |
| `Machine` is wrong for the directory | Parallel builds shared a target directory | Give each ABI its own `CARGO_TARGET_DIR` |
| A new symbol appears in the allowlist check | A new `#[unsafe(no_mangle)]` item | Remove the attribute or move the item behind the JNI surface |
| No build-id note | The `--build-id` rustflag is missing for that target | Add the flag to that target block |
| Size grew on every ABI at once | LTO stopped applying, or the build used the dev profile | Confirm the profile that the build selected |
| Size grew on one ABI only | A target-specific code path or an intrinsic fallback | `cargo bloat` for that target |
