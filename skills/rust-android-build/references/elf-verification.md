# Native Artifact Verification and Size Gate

Read this file when you write or change the release gate script for the Rust `.so` files, or when
the size gate fails. It says what to inspect in each built library, in what order, how to audit a
size regression, and how to wire the checks into CI.

Contents: check order; file and ELF header; LOAD alignment; `DT_NEEDED`; exported symbols; build
ID; size gate, size audit, and linker size flags; CI wiring; triage.

All commands use the NDK LLVM tools. Resolve them once:

```bash
NDK_BIN="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
```

Substitute your own library name for `libnative.so`.

## Check order

Run the checks in this order. Each one is cheaper than the next, and an early failure makes the
later results meaningless.

| Order | Check | Tool | Pass condition |
|-------|-------|------|----------------|
| 1 | The file exists for every shipped ABI | `test -f` | One `.so` per ABI directory |
| 2 | The file is an ELF shared object for the right machine | `llvm-readelf -h` | `Type: DYN`, machine matches the ABI |
| 3 | LOAD segment alignment | `llvm-readelf -lW` | `0x4000` or larger on 64-bit ABIs; 32-bit per project policy |
| 4 | Shared-library dependencies | `llvm-readelf -d` | Only system libraries or libraries shipped in the same ABI directory |
| 5 | Exported dynamic symbols | `llvm-readelf --dyn-syms` | Exactly the boundary allowlist |
| 6 | Build ID present | `llvm-readelf -n` | A GNU build-ID note exists |
| 7 | Size against baseline | `stat` plus the baseline file | Inside the budget |

Point the checks at the merged native-library tree that the packaging step consumes. A check
against one hand-picked build directory can pass while the packaged tree still holds a stale
artifact. This gate does not open an APK or AAB. The package and device checks in
[SKILL.md](../SKILL.md) cover the final archive.

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

A machine mismatch means that the copy step put the output of one Rust target into the directory
of another ABI. Check the triple-to-ABI mapping in the Gradle task.

## 3. 16 KiB LOAD segment alignment

```bash
"$NDK_BIN/llvm-readelf" -lW <lib-dir>/arm64-v8a/libnative.so \
  | awk '/LOAD/ {print $NF}' \
  | sort -u
# Expected on arm64-v8a and x86_64: 0x4000, or a larger power of two such as 0x10000
```

The last column of a `readelf -lW` program-header line is the alignment. Run the command once per
file. The final link gives every LOAD segment of one file the same alignment, so `sort -u` prints
one value. Two values mean that the command read more than one file.

On `armeabi-v7a` and `x86`, the NDK default is `0x1000`. Require `0x4000` there only when the
project policy applies the 16 KiB flag to 32-bit ABIs.

## 4. Shared-library dependencies

```bash
"$NDK_BIN/llvm-readelf" -d <lib-dir>/arm64-v8a/libnative.so | grep NEEDED
```

A Rust `cdylib` normally needs only system libraries such as `libc.so` and `libdl.so`. Any other
entry is a prebuilt shared library. It must ship in the same ABI directory, or the load fails on a
device and not on your machine. It also keeps its own LOAD alignment: run check 3 on it. A static
C archive linked into the Rust `cdylib` is not listed here, and it takes the alignment of the
final link.

Rebuild a misaligned prebuilt with a linker option in its build system, for example
`LDFLAGS=-Wl,-z,max-page-size=16384` or CMake
`target_link_options(<target> PRIVATE "-Wl,-z,max-page-size=16384")`. A linker option in `CFLAGS`
does not reach the final link.

## 5. Exported symbol allowlist

Use the allowlist diff from [SKILL.md](../SKILL.md): `llvm-readelf --dyn-syms --wide`, keep
defined `GLOBAL` or `WEAK` symbols of type `FUNC` or `OBJECT`, and compare with the sorted
expected set in both directions. Do not filter `llvm-objdump -T` output on ` DF `: that keeps
functions only, so an exported `#[unsafe(no_mangle)] pub static` passes.

rustc owns the `cdylib` export list and passes its own linker version script. A user version
script does not hide a Rust export, and a user map that names an undefined symbol fails the link.
Fix an unexpected export at its source: remove the `#[unsafe(no_mangle)]` or
`#[unsafe(export_name)]` attribute, or turn off the dependency feature that adds it.

## 6. Build ID

```bash
"$NDK_BIN/llvm-readelf" -n <lib-dir>/arm64-v8a/libnative.so | sed -n 's/.*Build ID: //p'
```

The command must print one hex ID. The build ID links a stripped shipped library to its unstripped
symbol input. Without it, a crash report from the field cannot be symbolicated reliably. The
`-Wl,--build-id=sha1` flag produces it. A plain `--build-id` makes LLD write an 8-byte ID that the
Android Studio LLDB does not recognize.

## 7. Size gate

Keep a checked-in baseline file that maps library name and ABI to a byte count. Apply the two
thresholds from the release-gates section of [SKILL.md](../SKILL.md). The per-library limit catches
one crate that ballooned, and the total limit catches many small increases that each pass the
per-library limit.

Read byte counts from the baseline file, not from documentation. Update the baseline in a separate
commit that states the reason. A baseline update inside a feature commit hides the growth from
review.

### Audit a regression

`cargo bloat` builds with `cargo build` and accepts only bin, dylib, and cdylib targets. On a
`crate-type = ["lib"]` package it stops with `only 'bin', 'dylib' and 'cdylib' crate types are
supported`. Rank the symbols of the unstripped `.so` from the Gradle task instead:

```bash
"$NDK_BIN/llvm-nm" -S --size-sort --radix=d -C <unstripped>/libnative.so | tail -30
```

Or run `cargo bloat` on a thin shim package that declares `crate-type = ["cdylib"]` and holds
`pub use <ffi_crate>;` in its `lib.rs`. Without that line, rustc does not link the FFI crate, and
`cargo bloat` measures an empty library.

```bash
cargo bloat --locked --profile android-jni --target aarch64-linux-android -p <cdylib-shim> --crates -n 30
cargo bloat --locked --profile android-jni --target aarch64-linux-android -p <cdylib-shim> -n 30   # by function
```

Common causes: a generic that monomorphizes into many copies (move the body into a non-generic
inner function), a new transitive dependency (diff `cargo tree --locked -p <ffi-crate>`), or a
build that selected a profile without fat LTO.

### Linker size flags

Do not add `-Wl,--gc-sections`: rustc already passes it for a `cdylib`. `-Wl,--icf=all` folds
identical function bodies. Measure it, and use it only when no linked C or C++ code compares
function addresses. `--icf=safe` needs `.llvm_addrsig` tables, which rustc 1.98.1 objects do not
carry, so it folds little Rust code.

## Wiring the gate into CI

1. Run the checks against the merged native-library tree, after the merge task and before
   packaging.
2. Fail the job on any check; do not warn. A warning in a native build is ignored until a store
   review rejects the release.
3. Print the file, the ABI, and the measured value on failure. A gate that prints only "failed"
   costs an extra debugging round trip.
4. Run the complete declared shipping ABI matrix on the release path. A pull-request job may check
   one ABI to save runner time.
5. Keep the gate script in the repository, not in the CI configuration, so that you run the same
   logic locally.

## Triage table

| Symptom | Cause | Action |
|---------|-------|--------|
| `sort -u` prints `0x1000` and `0x4000` | The command read several files | Run it per file; the `0x1000` file is a separately linked `.so` or a 32-bit build |
| A 64-bit prebuilt `.so` is `0x1000` | It was linked without the flag | Rebuild it with a linker option |
| `Machine` is wrong for the directory | The copy step mapped a triple to the wrong ABI | Fix the triple-to-ABI mapping |
| A new symbol appears in the allowlist check | A new `#[unsafe(no_mangle)]` item, possibly in a dependency | Remove the attribute, or the dependency feature that adds it |
| Link fails with `version script assignment of 'global' to symbol ... failed: symbol not defined` | A user version script names an absent symbol | Remove the version script |
| No build-ID note | The `--build-id=sha1` flag is missing, `RUSTFLAGS` replaced the config flags, or cargo ran outside the workspace root | Check the config tables, the environment, and the working directory |
| Size grew on every ABI at once | LTO stopped applying, or the build used the dev profile | Confirm the profile that the build selected |
| Size grew on one ABI only | A target-specific code path or an intrinsic fallback | `llvm-nm --size-sort` on that target's unstripped `.so`, or `cargo bloat` on a `cdylib` package |
