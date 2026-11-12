# Build and headers

Contents:

- Generated files and include paths
- Headers for downstream crates
- Builds without Cargo

The facts are for cxx-build 1.0.205.

## Generated files and include paths

`cxx_build::bridge("src/lib.rs")` writes these files under `OUT_DIR/cxxbridge/`
and adds `include/` and `crate/` to the include path:

| Path under `OUT_DIR/cxxbridge/` | Contents |
|---------------------------------|----------|
| `include/rust/cxx.h` | The `rust::` runtime types |
| `include/<prefix>/src/lib.rs.h` | Shared types and `extern "Rust"` declarations for C++ |
| `sources/<prefix>/src/lib.rs.cc` | The generated C++ side, compiled into the archive |
| `crate/<prefix>` | A symbolic link to the manifest directory |

`<prefix>` is the package `name`, or `CFG.include_prefix`. The `.rs.h` header
is also reachable as `<prefix>/src/lib.rs`. The build script prints
`cargo:rerun-if-changed=src/lib.rs` for each bridge file, and nothing for the
`.cc` and `.h` files you add.

To change the prefix, assign it before the first call to `bridge`: put
`cxx_build::CFG.include_prefix = "demo/v1";` first in `main` of `build.rs`. A
header at `include/engine.h` is then `"demo/v1/include/engine.h"`.

An empty prefix allows `#include "include/engine.h"`, but a library then risks a
name clash in a downstream crate. Keep a unique prefix for a published crate.

## Headers for downstream crates

A crate can include the headers of a direct dependency only. That dependency
must declare `links` in its `Cargo.toml`, so Cargo runs its build script first.
A transitive dependency's headers are not reachable.

| Need | Setting in the dependency's `build.rs` | Also required |
|------|---------------------------------------|---------------|
| Export an extra header directory, such as a system library's headers that a public header of the crate includes | `CFG.exported_header_dirs.push(path)` | `links` key |
| Re-export a dependency whose headers a public header of the crate includes | `CFG.exported_header_prefixes = vec!["dep-prefix"]` | `links` key |
| The same, chosen by that dependency's `links` value | `CFG.exported_header_links.push("dep-links")` | `links` key |

Export only what a public header includes. A dependency that only a `.cc` file
includes stays private.

## Builds without Cargo

The `#[cxx::bridge]` macro writes the Rust side during normal Rust compilation.
Generate the C++ side with the `cxxbridge` command from the `cxxbridge-cmd`
crate:

```bash
cargo install cxxbridge-cmd --version "=1.0.205" --locked
cxxbridge src/lib.rs --header > gen/demo/src/lib.rs.h
cxxbridge src/lib.rs > gen/demo/src/lib.rs.cc
```

The `cxxbridge-cmd` version must equal the `cxx` version in `Cargo.lock`. Every
generated symbol carries the patch number (`engine$cxxbridge1$205$total`), so a
skew fails the link with an undefined `$cxxbridge1$` symbol. Read the locked
version with `cargo tree --locked -i cxx --depth 0`, and pin the tool to it.

Link the C++ objects and the Rust code in one of two ways:

- Link with `rustc`: pass the C++ archive through `build.rs` or `-l`.
- Link with the C++ toolchain: build one Rust `staticlib` that holds every
  bridge, and link it into the C++ target.

The generated C++ calls into Rust and Rust calls into the generated C++. lld
resolves both directions in any order. A one-pass linker such as GNU ld can
need the archives in a group; the `rust-native-linking` skill, when it is
installed, owns archive order, else check the link with
`-C link-arg=-Wl,--warn-backrefs`.
