# Build and wheels

Contents:

- Interpreter selection
- The link mode
- abi3, abi3t, and the version floor
- Free-threaded wheels
- Linux platform tags
- Project layout
- Builds without maturin
- macOS link arguments

The facts are for pyo3 0.30.1 and maturin 1.16.0 (2026-11-12). The maturin
commands ran on x86_64 Linux with CPython 3.9, 3.13, and 3.14t. The macOS and
Windows notes come from the pyo3 0.30.1 guide and were not run.

## Interpreter selection

The `pyo3-ffi` build script picks the interpreter in this order: the active
virtual environment, `python`, then `python3`. Set `PYO3_PYTHON=/path/to/python3.x`
to override it. Print the configuration that the build found and stop:

```bash
PYO3_PRINT_CONFIG=1 cargo build
```

The output names `version`, `shared`, `target_abi`, `lib_name`, and
`build_flags` (`Py_GIL_DISABLED` for a free-threaded interpreter). maturin selects
its own interpreter: pass `-i python3.x` or `--find-interpreter` to
`maturin build`.

## The link mode

By default PyO3 links to libpython, so `cargo test`, examples, and binaries that
embed Python work. A Unix extension module must not link to libpython. Setting
`PYO3_BUILD_EXTENSION_MODULE` (any value) stops the link. maturin 1.9.4 and later
and setuptools-rust 1.12 and later set it for their own build.

The `extension-module` Cargo feature does the same, but for every target in the
crate, tests included. pyo3 0.30 marks it deprecated, without a build warning.
Remove it from `Cargo.toml`. A `cargo test` with the feature or the variable fails
at link time:

```text
error: linking with `cc` failed: exit status: 1
  = note: rust-lld: error: undefined symbol: PyEval_RestoreThread
```

Windows, Android, iOS, Cygwin, and AIX targets always link libpython (pyo3 0.30.1
`is_linking_libpython_for_target`). On Windows, pyo3 0.29 and later use
`raw-dylib`, so no import library is needed; `PYO3_USE_RAW_DYLIB=0` turns that off.

## abi3, abi3t, and the version floor

| Feature | Wheel | Loads on |
|---------|-------|----------|
| none | `cp313-cp313-<platform>` | That CPython version only |
| `abi3-py310` | `cp310-abi3-<platform>` | GIL builds of CPython 3.10 and later |
| `abi3t-py315` | `abi3t` | GIL and free-threaded CPython 3.15 and later |

- `abi3-py39` is the lowest floor in pyo3 0.30. When several `abi3-py3x` features
  are on, the lowest wins.
- The build interpreter must be at least the floor. With `abi3-py310` and a 3.9
  interpreter, the build stops:
  `error: cannot set a minimum Python version 3.10 higher than the interpreter version 3.9 (the minimum Python version is implied by the abi3-py310 feature)`.
- abi3 removes some APIs: the buffer protocol before 3.11, subclassing native
  types such as `PyException` before 3.12, and `text_signature` on classes before
  3.10. Gate version-specific code on `#[cfg(Py_LIMITED_API)]` or `#[cfg(Py_3_12)]`.
- `abi3t` wheels need maturin 1.14 or later and a 3.15 or later interpreter at
  build time. The pyo3 guide suggests `features = ["abi3", "abi3t"]` with one build
  per interpreter: `abi3` from the floor interpreter, `cp314t` from 3.14t, and
  `abi3t` from 3.15.

## Free-threaded wheels

Since pyo3 0.28, every `#[pymodule]` declares that it does not need the GIL. A
free-threaded interpreter keeps the GIL off when it imports the module.
`#[pymodule(gil_used = true)]` opts out: the interpreter then turns the GIL on and
prints `RuntimeWarning: The global interpreter lock (GIL) has been enabled to load
module '<name>'`. Use the opt-out only while you audit `unsafe` code that assumed
the GIL serialized access.

With only `abi3-py3x`, `maturin build -i python3.14t` warns
`abi3 does not yet support CPython 3.14t` and builds a version-specific wheel such
as `cp314-cp314t-manylinux_2_34_x86_64`. pip on 3.14t refuses an `abi3` wheel with
`is not a supported wheel on this platform`. Probe the result:

```bash
python3.14t -c 'import sys, mymod; print(sys._is_gil_enabled())'   # False when the module allows it
```

## Linux platform tags

`maturin develop` installs a `linux_x86_64` wheel for the host only. `maturin
build` checks the library against the manylinux policy and tags the wheel with
the newest glibc symbol version it uses. On a glibc 2.39 host a small module got
`manylinux_2_34`, which an older distribution refuses. To target an older policy:

```bash
maturin build --release --locked --compatibility manylinux2014           # fails on a new host
maturin build --release --locked --compatibility manylinux2014 --zig     # needs pip install maturin[zig]
```

The first command fails on a new host with `Your library is not manylinux_2_17
(aka manylinux2014) compliant because of the presence of too-recent versioned
symbols`. Use `--zig`, or build in a manylinux container. Inspect a wheel without
installing it:

```bash
unzip -l target/wheels/*.whl
```

## Project layout

- Pure Rust: `Cargo.toml` and `pyproject.toml` at the root. The wheel holds
  `<name>/<name>.abi3.so` and a generated `__init__.py`.
- Mixed Rust and Python: `maturin new --mixed --src` puts the Python package in
  `src/<pkg>/` and the crate in `rust/`. Name the native part privately:

```toml
[tool.maturin]
manifest-path = "rust/Cargo.toml"
python-source = "src"
module-name = "pkg._native"
```

The `#[pymodule]` must then be named `_native` (`#[pymodule(name = "_native")]`
on a module with another Rust name), and `src/pkg/__init__.py` re-exports from
`._native`. Python started inside `src/` imports the source package, which has no
`_native`, and fails with `ModuleNotFoundError: No module named 'pkg._native'`.

## Builds without maturin

From the pyo3 0.30.1 guide, not run here. Build the `cdylib` with
`PYO3_BUILD_EXTENSION_MODULE=1 cargo build --release`, then copy and rename the
library: `libname.so` to `name.so` on Linux, `libname.dylib` to `name.so` on macOS,
and `libname.dll` to `name.pyd` on Windows. Add the platform tag from
`python -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))'` to
the file name for redistribution. PyPy ignores a module without the tag.

## macOS link arguments

From the pyo3 0.30.1 guide, not run here. Without libpython, a macOS link needs
`-undefined dynamic_lookup`. maturin and setuptools-rust pass it. A manual build
adds a build script that calls `pyo3_build_config::add_extension_module_link_args()`
with `pyo3-build-config` in `[build-dependencies]`, or sets the flags in
`.cargo/config.toml`:

```toml
[target.aarch64-apple-darwin]
rustflags = ["-C", "link-arg=-undefined", "-C", "link-arg=dynamic_lookup"]
```
