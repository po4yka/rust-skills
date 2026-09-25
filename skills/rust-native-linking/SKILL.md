---
name: rust-native-linking
description: Use when writing a build.rs or *-sys crate that builds, discovers, binds, links, or packages a native C or C++ library, or when diagnosing a native link or load failure on host or cross targets. Triggers on rustc-link-lib, pkg-config, vcpkg, CMake, bindgen, cbindgen, rpath, install name, windows-msvc, windows-gnu, import library, raw-dylib, PDB, LNK2019, ERROR_BAD_EXE_FORMAT, undefined reference, undefined symbol, library not loaded, or DLL not found.
license: BSD-3-Clause
---

# Rust Native Linking

Hand these topics to sibling skills, when they are installed:

- The `rust-unsafe` skill owns FFI soundness, layout, ownership, and safety
  contracts.
- The `cargo-workflows` skill owns workspace layout, profiles, features, and
  general cross-target orchestration.
- The `rust-android-build` skill owns NDK selection, Android ABI policy, page
  size, `jniLibs`, APK or AAB checks, and the Android export gate.
- The `rust-wasm` skill owns WebAssembly link errors, including
  `undefined symbol` on `wasm32` targets.

Do not add a native build step when an existing Rust crate already owns the
same library. Reuse its `*-sys` crate and its `links` contract.

Read [references/windows.md](references/windows.md) when `TARGET` is a Windows
target. It covers the MSVC, GNU, and GNU LLVM toolchains, CRT selection,
import libraries and `raw-dylib`, vcpkg triplets, DLL loading, PDB files, and
final PE/COFF inspection.

## Completion evidence

`cargo check` does not link. A green check proves nothing about link inputs,
loader paths, or exported symbols. Prove each level that applies:

1. Build the exact target and crate type that ships.
2. Inspect the artifact architecture and native dependency table.
3. Inspect the required and exported symbols.
4. Run the packaged artifact outside `cargo run` and `cargo test`.
5. Repeat the check for each supported target policy or CI target. A link
   with `rust-lld` does not prove the archive order for a GNU ld target.

## Diagnose the first failing layer

Since Rust 1.97, the warn-by-default `linker_messages` lint prints linker
output as `warning: linker stderr: ...`. `-D warnings` does not deny it. Read
it before you change flags: it often names the missing library, the order
defect, or the unknown option. Output that rustc classes as informational goes
to the allow-by-default `linker_info` lint instead. On macOS with Rust 1.98.1
it hid the ld64 line `object file (...) was built for newer 'macOS' version
(X) than being linked (Y)`. That line marks `cc` objects built for another
deployment target than rustc. Pass `-W linker-info` while you diagnose a link,
for example `cargo rustc --bin <app> -- -W linker-info`. The `rust-lints` skill
owns the gate level for both lints.

| Symptom | Likely layer | First evidence | Fix |
|---|---|---|---|
| `cannot find -lfoo`, `unable to find library -lfoo`, `library 'foo' not found`, or `LNK1181` | Link search | Exact linker command and artifact directory | Correct discovery or `rustc-link-search`; do not copy to a global directory |
| `undefined reference`, `undefined symbol`, or `LNK2019` | Symbol or order | Undefined name plus provider symbol table | Add the real provider, correct mangling, or order consumer before provider |
| Links with `rust-lld` on x86_64 Linux, `undefined reference` with GNU ld or on another Linux target | Archive order that `rust-lld` tolerates | `--warn-backrefs` lane output | Emit each consumer before its provider |
| `undefined reference to 'open64'`, `fstat64`, or another `*64` name on `*-linux-musl`, Rust 1.93+ | Bundled musl 1.2.5 has no legacy LFS64 symbols | `cargo tree -i libc` and the object that references the name | Update `libc` to 0.2.146 or newer; rebuild the C input with the standard names. `-D_LARGEFILE64_SOURCE` is only a short-term shim |
| Duplicate symbol or `LNK2005` | Ownership | Link map and all `links` owners | Remove the second provider or archive copy |
| Wrong ELF class, bad CPU type, or `0xc000007b` | Architecture | Artifact header and `TARGET` | Rebuild every native input for the target architecture |
| `GLIBCXX_* not found` | C++ runtime version | `DT_NEEDED`, symbol versions, packaged runtime | Use one compatible C++ runtime policy and package it when required |
| `library not loaded` on macOS | Install name or run path | `otool -L` and `LC_RPATH` | Correct `@rpath`, `@loader_path`, embedding, and signing |
| DLL not found on Windows | Packaging or transitive DLL | `dumpbin /DEPENDENTS` recursively | Ship the correct DLLs in an intended search location |
| Works in `cargo run`, fails from package | Loader environment | Run outside Cargo and inspect dependency table | Add package-relative run path or package the DLL |
| Native build uses host headers while crossing | Host or target mix | `HOST`, `TARGET`, compiler command, sysroot, `cfg!(target_*)` in `build.rs` | Read `TARGET` and `CARGO_CFG_TARGET_*`, not `cfg!`; select target-qualified tools, headers, libraries, and probes |
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

Rust symbols use v0 mangling (`_R` prefix) by default since Rust 1.97, so a
`_ZN` grep finds nothing. `#[no_mangle]` and `#[export_name]` symbols keep
their literal names. The `rust-debugging` skill covers demangling.

Do not use `-Wl,--version-script` to hide exports of a Rust `cdylib`. rustc
passes its own version script, and an extra map did not remove a
`#[no_mangle]` export (lld, Rust 1.98.1). Compare the defined dynamic symbols
with an allowlist instead.

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

`lld` resolves a backward archive reference that GNU ld rejects. Since Rust
1.90, the rustup toolchain on an x86_64 Linux host links
`x86_64-unknown-linux-gnu` with `rust-lld` by default. An order defect passes
there and fails on a GNU ld target. Expose it in a dedicated CI lane on an
x86_64 Linux runner with the rustup toolchain:

```bash
RUSTFLAGS="-C link-arg=-Wl,--warn-backrefs -D linker-messages" \
  cargo test --locked --no-run --all-targets --target x86_64-unknown-linux-gnu
```

A defect prints `backward reference detected: <symbol> in <consumer archive>
refers to <provider archive>`. `--warn-backrefs` only warns through the
`linker_messages` lint, so `-D linker-messages` makes the lane fail. The lane
must link an artifact that uses the native archives. `cargo build` of a
`*-sys` library makes an rlib and runs no linker; a test that calls one native
function supplies the link. `RUSTFLAGS` replaces the rustflags from config
files, so keep it out of the normal build.

To get a hard GNU ld failure instead, pass `-C linker-features=-lld` on the
same runner, or build on an `aarch64-unknown-linux-gnu` runner. Both link with
the system linker.

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
and fixed flags. Read
[references/build-helpers.md](references/build-helpers.md) when `build.rs`
configures one of these helpers or generates bindings. It holds each helper's
tracking, cross-compilation, and CI regeneration rules.

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

    eprintln!("native target={target} os={target_os} out={}", out_dir.display());
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

Pass flags to each compiler through its own channel: a nested `rustc` reads
`CARGO_ENCODED_RUSTFLAGS` (never split it on spaces), and `cc` 1.2.2
or newer copies compatible Rust codegen flags into C flags. Read
[references/build-helpers.md](references/build-helpers.md) when `build.rs` runs
a nested compiler or when a Rust flag change must not change the C objects.

## Separate host and target

A build script compiles and runs on `HOST`. It produces native code for
`TARGET`.

- Read `TARGET` and `CARGO_CFG_TARGET_*` for target decisions.
- Do not use `cfg!(target_os)` in `build.rs`; it describes the host.
- Use `HOST != TARGET` as the cross-compilation test.
- Run generators and build tools for `HOST`.
- Compile libraries, probe headers, and select ABI files for `TARGET`.
- Never execute a target probe program from `build.rs`; a cross target binary
  cannot run on the host. Use compile-only feature checks or target metadata.
- Pass the resolved target linker or toolchain file to the native builder.
- Keep host tools out of target link search paths.

A native host success is not cross-target evidence.

## Choose static, dynamic, or framework linking

| Mode | Select when | Required proof |
|---|---|---|
| Static archive | One artifact and license policy permit it | Symbols are present once; CRT and C++ runtimes match |
| Dynamic library | The platform or update policy owns a shared library | Loader path and every transitive library work after packaging |
| Apple framework | The dependency ships as a framework | Framework search path, architecture slices, embedding, signing |

Use `rustc-link-lib=static=foo`, `dylib=foo`, or `framework=Foo`. Do not infer
the mode from a file that happens to exist first in a search directory. On
Windows, a `.lib` can be an import library; `references/windows.md` covers the
difference.

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
The `rust-crate-release` skill owns the complete package and publish gate.

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

Since Rust 1.91, rustc passes the SDK root to the linker, and a library in
`/usr/local/lib` may no longer be found implicitly. The link then fails with
`ld: library 'foo' not found`. Discover the real prefix with `pkg-config` and
emit `cargo::rustc-link-search=native=<prefix>/lib`.

## Authoritative references

- [Cargo build scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html)
- [Cargo build-script environment](https://doc.rust-lang.org/cargo/reference/environment-variables.html#environment-variables-cargo-sets-for-build-scripts)
- [Rust native link attribute](https://doc.rust-lang.org/reference/items/external-blocks.html#the-link-attribute)
- [Linux dynamic loader](https://man7.org/linux/man-pages/man8/ld.so.8.html)
- [Apple run-path dependent libraries](https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/RunpathDependentLibraries.html)
- [rust-lld default on x86_64 Linux](https://blog.rust-lang.org/2025/09/01/rust-lld-on-1.90.0-stable/)
- [lld `--warn-backrefs`](https://lld.llvm.org/ELF/warn_backrefs.html)
