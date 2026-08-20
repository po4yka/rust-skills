---
name: rust-native-linking
description: Use when a Rust crate must discover, compile, generate bindings for, link, package, or diagnose a native C or C++ library across host and cross targets. Triggers on build.rs, rustc-link-lib, links, *-sys, cc, pkg-config, vcpkg, CMake, bindgen, cbindgen, rpath, install name, undefined reference, library not loaded, or DLL not found.
license: BSD-3-Clause
---

# Rust Native Linking

Use this skill for Cargo integration with native C and C++ libraries. Own the
path from native source or an installed library to a loadable final artifact.

Keep these boundaries:

- Use `rust-unsafe` for FFI soundness, layout, ownership, and safety contracts.
- Use `cargo-workflows` for workspace layout, profiles, features, and general
  cross-target orchestration.
- Use `rust-android-build` for NDK selection, Android ABI policy, page size,
  `jniLibs`, and APK or AAB verification.
- Use this skill for `build.rs`, native discovery, native compilation, linker
  inputs, loader paths, and symbol or ABI diagnosis.

Do not add a native build step when an existing Rust crate already owns the
same library. Reuse its `*-sys` crate and its `links` contract.

## Completion evidence

Prove all applicable levels. Do not stop after `cargo check`. It does not link
the final artifact.

1. Build the exact target and crate type that ships.
2. Inspect the artifact architecture and native dependency table.
3. Inspect the required and exported symbols.
4. Run the packaged artifact outside `cargo run` and `cargo test`.
5. Repeat the check for each supported target policy or CI target.

## Select one integration path

| Input | Use | Do not use |
|---|---|---|
| A maintained crate already links the library | Its `*-sys` crate | A second `links` owner |
| A few C, C++, assembly, or CUDA source files | `cc` | Hand-written compiler and archiver commands |
| A Unix system package with a `.pc` file | `pkg-config` | Hard-coded `/usr/lib` or `/usr/local/lib` |
| A Windows package in a vcpkg tree | `vcpkg` | A machine-specific absolute `.lib` path |
| An upstream CMake project | `cmake` | Reimplementing its target graph in `cc` |
| C or C++ headers must become Rust declarations | `bindgen` | Hand-copied declarations that drift |
| A Rust ABI must expose a C or C++ header | `cbindgen` | Running `bindgen` in the wrong direction |

Use the upstream build system when it carries feature probes, generated files,
or platform rules. Use `cc` when the native build is only a short source list
and fixed flags.

Choose system or bundled source explicitly. Do not silently fall back from a
system library to bundled source. The fallback changes patch ownership,
licensing, ABI, and static or dynamic behavior. If both modes are required,
put the choice behind one documented feature in the single `*-sys` crate.

## Put native ownership in one `*-sys` crate

Use a small `foo-sys` package for these tasks:

- Declare `links = "foo"`.
- Discover or build `libfoo` in `build.rs`.
- Emit the link instructions once.
- Hold the raw declarations or generated bindings.
- Publish include paths or other facts as `cargo::metadata` when an immediate
  dependent build script needs them.

Keep the safe API in a separate crate. Do not put business logic in `foo-sys`.

```toml
[package]
name = "foo-sys"
version = "0.1.0"
edition = "2024"
links = "foo"
build = "build.rs"

[build-dependencies]
# Add only the helper selected by the integration path.
```

Cargo permits only one package for each `links` value in a dependency graph.
Use this rule to prevent duplicate copies and duplicate symbols. Do not make
system and bundled providers separate packages with the same `links` value.

Publish metadata after discovery:

```text
cargo::metadata=include=/absolute/target/include
cargo::metadata=version=1.2.3
```

An immediate dependent reads these values as `DEP_FOO_INCLUDE` and
`DEP_FOO_VERSION`. Cargo does not pass `DEP_*` metadata through transitive
dependencies. Forward a value deliberately if another native layer needs it.

## Keep `build.rs` deterministic

Treat `build.rs` as a host executable that produces target artifacts.

- Read inputs under `CARGO_MANIFEST_DIR`.
- Write generated files, object files, and native build trees only under
  `OUT_DIR`.
- Do not modify `src/`, a registry checkout, or a vendored source tree.
- Do not assume that `OUT_DIR` is empty. Replace outputs atomically or let the
  selected native builder manage its own subdirectory.
- Do not download source, install packages, or inspect unrelated host state.
- Return a non-zero status for a required native step that fails.
- Print diagnostics to stderr. Reserve stdout for `cargo::` instructions.
- Run `cargo build -vv` to see the command stream and saved script output.

Emit one change rule for every direct file and external environment variable
that the script reads. A directory rule scans the full directory. Prefer file
rules when the input set is known.

```rust
use std::env;
use std::path::PathBuf;

fn required(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("Cargo did not set {name}"))
}

fn main() {
    println!("cargo::rerun-if-changed=native/wrapper.h");
    println!("cargo::rerun-if-changed=native/source.c");
    println!("cargo::rerun-if-env-changed=FOO_ROOT");

    let target = required("TARGET");
    let target_os = required("CARGO_CFG_TARGET_OS");
    let out_dir = PathBuf::from(required("OUT_DIR"));

    eprintln!(
        "native target={target} os={target_os} out={}",
        out_dir.display()
    );
}
```

Do not emit `rerun-if-env-changed` for `TARGET` or another variable that Cargo
sets for the build script. Emit it for external inputs such as `FOO_ROOT`,
`CC`, or a custom SDK path when a selected helper does not already track it.

If the script has no external input, emit
`cargo::rerun-if-changed=build.rs`. Without any `rerun-if` instruction, Cargo
scans the package and can run the script after any package file changes.

Use `cargo::KEY=VALUE` on Rust 1.77 or newer. Use the legacy
`cargo:KEY=VALUE` spelling only when the declared MSRV is older than 1.77.

## Emit linker instructions in dependency order

Prefer structured instructions over raw linker arguments:

```text
cargo::rustc-link-search=native=/absolute/target/lib
cargo::rustc-link-lib=static=foo
cargo::rustc-link-lib=dylib=bar
cargo::rustc-link-search=framework=/absolute/Frameworks
cargo::rustc-link-lib=framework=CoreFoundation
```

The complete library syntax is
`[KIND[:MODIFIERS]=]NAME[:RENAME]`. Use `static`, `dylib`, or `framework` as
the kind. Add a modifier such as `+whole-archive` only when inspection proves
that normal archive extraction omits required registration objects.

The order of printed instructions can become linker argument order. Emit a
consumer object or archive before the libraries that satisfy its undefined
symbols. If native archive `foo` calls `bar`, emit `foo` before `bar` on a
one-pass linker. Fix the order before adding `--start-group` or
`+whole-archive`; both can hide a dependency cycle and increase the artifact.

Do not duplicate instructions that `cc`, `pkg-config`, `vcpkg`, or another
helper already emits. Configure the helper not to emit metadata only when the
script must control the final order itself.

Use `cargo::rustc-link-arg-*` only when Cargo has no structured instruction.
Select the narrow target type:

```text
cargo::rustc-link-arg-cdylib=-Wl,<platform-option>
cargo::rustc-link-arg-bin=app=-Wl,<platform-option>
```

These instructions affect only targets in the package whose `build.rs` emits
them. A `foo-sys` build script cannot add a run path to a dependent
application or `cdylib`. Put final-artifact linker arguments in the package
that builds that artifact, or in its host build system.

Do not apply one platform linker flag to every binary, test, example, and
benchmark.

## Use each native build helper for one job

### `cc`

Use `cc::Build` for a fixed list of source files. Let it select the compiler,
archiver, target flags, and C++ runtime. Do not invoke `gcc`, `clang`, `cl`, or
`ar` by name.

Track all source files and non-system headers. Respect target-qualified `CC`,
`CXX`, `AR`, `CFLAGS`, and `CXXFLAGS`. Keep custom flags behind
`is_flag_supported` or an explicit target condition. Use the `parallel`
feature only when native compilation is a measured bottleneck; Cargo already
coordinates build-script concurrency through its jobserver.

### `pkg-config`

Use `pkg_config::Config` when the target sysroot supplies a `.pc` file. Set a
minimum compatible version. Let the crate emit include paths, link search
paths, libraries, and transitive flags.

For cross-compilation, set target-qualified `PKG_CONFIG_PATH`,
`PKG_CONFIG_LIBDIR`, and `PKG_CONFIG_SYSROOT_DIR`. Do not set
`PKG_CONFIG_ALLOW_CROSS=1` without a target sysroot. A host `.pc` file can
produce a successful probe and an unusable target link.

### `vcpkg`

Use `vcpkg::Config` for a package in a vcpkg tree, primarily on Windows. Pin
the vcpkg baseline or manifest outside `build.rs`. Select the intended triplet
with `VCPKGRS_TRIPLET`. Treat `VCPKGRS_DYNAMIC=1` as a packaging change because
the final application must carry the selected DLLs.

Match the Rust target environment and CRT mode. An MSVC `.lib` is not a MinGW
archive. A static package built for a dynamic CRT is not the same as a fully
static CRT build.

### `cmake`

Use `cmake::Config` when the upstream project already owns a CMake graph. Give
it source under `CARGO_MANIFEST_DIR` and let it install under `OUT_DIR`. Pass
only project options that affect the required library. Do not mirror CMake's
compiler, generator, or cross-target selection in ad hoc shell commands.

Inspect the returned install prefix. Emit the actual `lib`, `lib64`, or
configuration-specific directory. Do not assume one layout across platforms.

## Generate bindings in the correct direction

### C or C++ to Rust with `bindgen`

Prefer checked-in generated bindings when consumers must build without
`libclang`, or when the public native ABI changes only at release time. Run a
CI command that regenerates into a temporary file and fails on a diff.

Use build-time `bindgen` only when target macros or headers change the binding
shape and every build environment provides compatible `libclang`.

- Wrap only the public headers that define the ABI.
- Allowlist the required functions, types, and variables.
- Pass the target triple and the same sysroot and include paths as the native
  compiler.
- Install `CargoCallbacks` so header changes trigger regeneration.
- Write build-time output to `OUT_DIR` and include it with `include!`.
- Add a size, alignment, and call smoke test for the supported ABI.

Do not use generated declarations as soundness evidence. Review ownership,
nullability, aliasing, and callbacks with `rust-unsafe`.

### Rust to C or C++ with `cbindgen`

Generate a public header from the Rust ABI in an explicit development or
release command. Check the header in when downstream build systems consume
source archives or published packages. Make CI regenerate and compare it.

Do not run `cbindgen` in `build.rs` only to update a checked-in header.
`build.rs` must not modify package source, and normal Rust consumers do not
need the header.

## Separate host and target

A build script compiles and runs on `HOST`. It produces native code for
`TARGET`.

- Read `TARGET` and `CARGO_CFG_TARGET_*` for target decisions.
- Do not use `cfg!(target_os)` in `build.rs`; it describes the host.
- Use `HOST != TARGET` as the cross-compilation test.
- Run generators and build tools for `HOST`.
- Compile libraries, probe headers, and select ABI files for `TARGET`.
- Never execute a target probe program from `build.rs`.
- Use compile-only feature checks or target metadata instead.
- Pass the resolved target linker or toolchain file to the native builder.
- Keep host tools out of target link search paths.

For `bindgen`, pass the target compiler view to Clang. For `pkg-config`, use a
target sysroot. For vcpkg, use a target triplet. For CMake, use the target
toolchain that Cargo or the environment selected. A native host success is not
cross-target evidence.

## Choose static, dynamic, or framework linking

| Mode | Select when | Required proof |
|---|---|---|
| Static archive | One artifact and license policy permit it | Symbols are present once; CRT and C++ runtimes match |
| Dynamic library | The platform or update policy owns a shared library | Loader path and every transitive library work after packaging |
| Apple framework | The dependency ships as a framework | Framework search path, architecture slices, embedding, signing |

Use `rustc-link-lib=static=foo`, `dylib=foo`, or `framework=Foo`. Do not infer
the mode from a file that happens to exist first in a search directory.

On Windows, distinguish a static `.lib` from a DLL import `.lib`. The import
library satisfies link-time symbols, but the corresponding `.dll` is still a
runtime dependency.

## Make runtime loading a packaging property

`cargo::rustc-link-search` solves link-time discovery. It does not install a
shared library beside the final program. Cargo adds link-search paths under
`OUT_DIR` to the loader environment for commands such as `cargo run` and
`cargo test`. It does not guarantee this behavior for external system paths.
A Cargo-run smoke test can therefore pass while the packaged program fails.

For an application package, run the installed artifact outside Cargo. For a
published Rust package, also run `cargo package --list`, create the `.crate`,
extract it into a temporary directory, and build it there. This proves that
headers, native sources, and generated inputs enter the published archive.
Use `rust-crate-release` for the complete package and publish gate.

### Linux ELF

Prefer a relocatable `DT_RUNPATH` such as `$ORIGIN/../lib` for an application
that ships private libraries. Quote `$ORIGIN` in shell commands so the shell
does not expand it. Remember that `DT_RUNPATH` applies only to direct
dependencies. Give each shared object a valid path to its own dependencies.

Use `LD_LIBRARY_PATH` for diagnosis, not as the installed product contract.
Do not run `ldd` on an untrusted executable. Inspect `DT_NEEDED`, `RUNPATH`,
and symbols with `readelf` first.

### macOS Mach-O

Give a relocatable library an install name such as `@rpath/libfoo.dylib`.
Give the executable or loading library an `LC_RPATH` such as
`@loader_path/../Frameworks`. Inspect the result with `otool -L` and
`otool -l`. Use `install_name_tool` only as an explicit packaging step. Prefer
correct linker inputs so rebuilt artifacts do not need repair.

Embed and sign frameworks or dylibs in the final bundle. Check every required
architecture slice with `lipo -info`.

### Windows PE/COFF

Package required DLLs in the application package or another intended search
location. Do not rely on a developer machine's global `PATH`. Keep safe DLL
search behavior. For explicit runtime loading, use an absolute path or the
`LOAD_LIBRARY_SEARCH_*` flags instead of the current directory.

Use `dumpbin /DEPENDENTS` for DLL names, `/IMPORTS` for imported symbols,
`/EXPORTS` for exports, and `/HEADERS` for the machine type.

## Diagnose the first failing layer

| Symptom | Likely layer | First evidence | Fix |
|---|---|---|---|
| `cannot find -lfoo` or `LNK1181` | Link search | Exact linker command and artifact directory | Correct discovery or `rustc-link-search`; do not copy to a global directory |
| `undefined reference` or `LNK2019` | Symbol or order | Undefined name plus provider symbol table | Add the real provider, correct mangling, or order consumer before provider |
| Duplicate symbol or `LNK2005` | Ownership | Link map and all `links` owners | Remove the second provider or archive copy |
| Wrong ELF class, bad CPU type, or `0xc000007b` | Architecture | Artifact header and `TARGET` | Rebuild every native input for the target architecture |
| `GLIBCXX_* not found` | C++ runtime version | `DT_NEEDED`, symbol versions, packaged runtime | Use one compatible C++ runtime policy and package it when required |
| `library not loaded` on macOS | Install name or run path | `otool -L` and `LC_RPATH` | Correct `@rpath`, `@loader_path`, embedding, and signing |
| DLL not found on Windows | Packaging or transitive DLL | `dumpbin /DEPENDENTS` recursively | Ship the correct DLLs in an intended search location |
| Works in `cargo run`, fails from package | Loader environment | Run outside Cargo and inspect dependency table | Add package-relative run path or package the DLL |
| Native build uses host headers while crossing | Host or target mix | `HOST`, `TARGET`, compiler command, sysroot | Select target-qualified tools, headers, libraries, and probes |
| Rebuilds on every edit | Change detection | `cargo build -vv` build-script reason | Add precise `rerun-if-changed` and `rerun-if-env-changed` rules |
| Header changed but bindings did not | Generation inputs | Regeneration diff and build-script output | Track included headers or make checked-in generation a CI gate |

Do not add more linker flags until you can name the missing file, symbol,
architecture, ABI, or loader path.

## Inspect final artifacts

Use the platform tools on the exact shipped file:

```bash
# Linux
file <artifact>
readelf -h -d --dyn-syms --wide <artifact>
nm -D --defined-only <shared-library>

# macOS
file <artifact>
lipo -info <artifact>
otool -L <artifact>
otool -l <artifact>
nm -gU <shared-library>
```

```text
rem Windows Developer Command Prompt
dumpbin /HEADERS <artifact>
dumpbin /DEPENDENTS <artifact>
dumpbin /IMPORTS <artifact>
dumpbin /EXPORTS <dll>
```

For a static archive, inspect its members and defined symbols with `ar t` and
`nm`. For a shared library, recurse through every dynamic dependency. A direct
dependency can load and still fail because one of its dependencies is absent.

## Validation checklist

- [ ] One crate owns each `links` value.
- [ ] `build.rs` writes only under `OUT_DIR`.
- [ ] Every direct input has a precise change rule.
- [ ] Structured Cargo instructions replace raw linker flags where possible.
- [ ] Link instructions follow consumer-before-provider order.
- [ ] The selected helper owns only the job it is designed to do.
- [ ] `HOST` tools and `TARGET` libraries stay separate.
- [ ] Static or dynamic selection is explicit.
- [ ] Generated bindings match the same target headers as the native build.
- [ ] The final artifact has the expected architecture and symbols.
- [ ] Every dynamic dependency is present in the packaged layout.
- [ ] The packaged artifact runs without Cargo's loader environment.

## Authoritative references

- [Cargo build scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html)
- [Cargo build-script environment](https://doc.rust-lang.org/cargo/reference/environment-variables.html#environment-variables-cargo-sets-for-build-scripts)
- [Rust native link attribute](https://doc.rust-lang.org/reference/items/external-blocks.html#the-link-attribute)
- [`cc` crate](https://docs.rs/cc/latest/cc/)
- [`pkg-config` crate](https://docs.rs/pkg-config/latest/pkg_config/)
- [`vcpkg` crate](https://docs.rs/vcpkg/latest/vcpkg/)
- [`cmake` crate](https://docs.rs/cmake/latest/cmake/)
- [bindgen user guide](https://rust-lang.github.io/rust-bindgen/)
- [cbindgen documentation](https://github.com/mozilla/cbindgen/blob/main/docs.md)
- [Linux dynamic loader](https://man7.org/linux/man-pages/man8/ld.so.8.html)
- [Apple run-path dependent libraries](https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/RunpathDependentLibraries.html)
- [Windows DLL search order](https://learn.microsoft.com/windows/win32/dlls/dynamic-link-library-search-order)
