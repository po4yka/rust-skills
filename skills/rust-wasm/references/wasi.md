# WASI builds and components

Use this file when you build for `wasm32-wasip1` or `wasm32-wasip2`, select
async I/O for WASI, ship a WebAssembly component, or compile C or C++ for a
WASI target. The capability
and WIT pinning rules in `SKILL.md` apply to every command here.

## Build and run Preview 1

Build Preview 1 only for a host that implements its imports:

```bash
cargo build --locked --release --target wasm32-wasip1
wasm-tools validate target/wasm32-wasip1/release/<binary>.wasm
wasmtime run --dir ./fixtures target/wasm32-wasip1/release/<binary>.wasm
```

## Build and run a WASI 0.2 component

Build a WASI 0.2 component for a component-aware host:

```bash
cargo build --locked --release --target wasm32-wasip2
wasm-tools validate target/wasm32-wasip2/release/<binary>.wasm
wasm-tools component wit target/wasm32-wasip2/release/<binary>.wasm
wasmtime run target/wasm32-wasip2/release/<binary>.wasm
```

Use native `wasm32-wasip2` and `wit-bindgen` tooling for new components. Do not
introduce `cargo-component` without a project-specific requirement; it is being
deprecated in favor of native Cargo builds.

## Select async I/O for WASI

Select the executor and I/O library that supports the exact WASI preview and
runtime. Do not assume a native epoll, kqueue, socket, or thread implementation
exists. Run the I/O path under the shipping runtime.

## Compile C or C++ for WASI

Rust links WASI programs against its bundled `wasi-libc`, so pure Rust needs no
C toolchain. When a build script compiles C or C++ through the `cc` crate,
install wasi-sdk and set `WASI_SDK_PATH` to its directory. `cc` then uses
`$WASI_SDK_PATH/bin/<target>-clang`, which already selects the WASI sysroot.

This needs `cc` 1.2.39 or later. An older `cc` ignores `WASI_SDK_PATH` and runs
the system `clang`, which fails with errors such as `'stdio.h' file not found`.
Run `cargo update -p cc`, or set `CC_<target>`, for example
`CC_wasm32_wasip2=$WASI_SDK_PATH/bin/wasm32-wasip2-clang`.

For C++, also set `WASI_SYSROOT=$WASI_SDK_PATH/share/wasi-sysroot`. `cc` links
libc++ and libc++abi only when it is set, and Rust 1.96+ makes the missing C++
runtime symbols a link error.
