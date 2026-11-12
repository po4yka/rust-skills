---
name: rust-pyo3
description: Use when exposing Rust to Python with PyO3 or building wheels with maturin, or when a PyO3 extension fails to import, link, or install. Covers pymodule, pyfunction, and pyclass on the Bound API, Python::detach, PyErr conversion, PanicException, abi3 floors, free-threaded 3.14t, and pytest against an installed wheel. Triggers on dynamic module does not define module export function, PyInit_, a libpython link error in cargo test, extension-module, PYO3_BUILD_EXTENSION_MODULE, not a supported wheel on this platform, manylinux, or Already borrowed.
license: BSD-3-Clause
---

# Rust PyO3

A PyO3 crate compiles without any check of the Python side. The module name, the
link mode, and the wheel tag fail only at `import` or `pip install`. Only an import
from an installed wheel proves them ([Verify](#verify)). The facts below are for
pyo3 0.30.1 and maturin 1.16.0, measured on 2026-11-12 with CPython 3.13 and 3.14t
on x86_64 Linux.

## Pin the versions

Read the locked version before you copy a snippet:

```bash
cargo tree --locked -i pyo3 --depth 0
```

pyo3 0.30 needs Rust 1.85 and CPython 3.9 or later. It dropped 3.8 in 0.30 and
the free-threaded 3.13t in 0.29; 3.14t and later stay supported. The `maturin new`
template of maturin 1.16.0 still writes `pyo3 = "0.29.0"` and
`requires-python = ">=3.8"`. Raise both after you scaffold a project.

These names changed in 0.26, and the old names are gone from 0.30.1:

| Old name | 0.30 name |
|----------|-----------|
| `Python::with_gil` | `Python::attach` |
| `py.allow_threads` | `py.detach` |
| `prepare_freethreaded_python` | `Python::initialize` |
| `GILOnceCell` | `pyo3::sync::PyOnceLock` |
| `PyObject` (alias) | `Py<PyAny>` |

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImportError: dynamic module does not define module export function (PyInit_x)` | The `#[pymodule]` name differs from the file name Python loads. maturin only warns: `Couldn't find the symbol PyInit_x` | Give the `#[pymodule]` the `[lib] name`, or set `#[pymodule(name = "..")]` to the last part of `module-name` in `[tool.maturin]` |
| `rust-lld: error: undefined symbol: PyEval_RestoreThread` (or another `Py*`) in `cargo test` | The deprecated `extension-module` feature, or `PYO3_BUILD_EXTENSION_MODULE` in the shell, stops the link to libpython | Remove the feature and unset the variable. maturin 1.9.4 and later set the variable for its own build |
| A Rust test panics: `The Python interpreter is not initialized` | A test calls `Python::attach` with no interpreter | Call `Python::initialize()` first in each such test |
| `ldd` on the built `.so` lists `libpython3.x.so` | A plain `cargo build` made the library | Build wheels with `maturin build`. A manylinux wheel must not link libpython |
| `cannot set a minimum Python version 3.10 higher than the interpreter version 3.9` | The build interpreter is older than the `abi3-py3x` floor | Select a newer interpreter with `-i` or `PYO3_PYTHON`, or lower the floor |
| `ERROR: <wheel> is not a supported wheel on this platform.` | The interpreter is older than the abi3 floor, is free-threaded and got an `abi3` wheel, or has an older glibc than the manylinux tag | Read the tag in the file name. Build a `cp314t` wheel for 3.14t, and set `--compatibility` |
| `Your library is not manylinux_2_17 (aka manylinux2014) compliant because of the presence of too-recent versioned symbols` | The build host glibc is newer than the requested tag | Build in a manylinux container, or pass `--zig` (`pip install maturin[zig]`) |
| `RuntimeWarning: The global interpreter lock (GIL) has been enabled to load module` | The module declares `gil_used = true` on a free-threaded interpreter | Audit the module, then remove `gil_used = true` |
| `pyo3_runtime.PanicException`, which `except Exception` does not catch | A Rust panic reached the PyO3 trampoline | Return a `PyErr` for every expected failure. A panic is a bug |
| `RuntimeError: Already borrowed` | Two calls overlap on one `#[pyclass]` value, one through `&mut self` | Use `#[pyclass(frozen)]` with atomics or a `Mutex` |
| `E0277` on a `py.detach` closure | The closure captures a `Bound` or a `Python` token | Copy the data to Rust types first, or capture a `Py<T>` |
| `E0117` on `impl From<io_crate::Error> for PyErr` | Orphan rule: both types are foreign | Wrap the error in a local newtype, or call `map_err` |
| `ModuleNotFoundError: No module named 'pkg._native'` | The source tree `pkg/` shadows the installed package | Use the `src/` layout (`maturin new --mixed --src`), and run Python outside the source tree |
| Ctrl-C has no effect during a long Rust call | Python acts on `SIGINT` only after the Rust call returns | Call `py.check_signals()?` in the loop |

## Module shape

Use the declarative `#[pymodule] mod` form. Keep the logic in plain Rust functions
that return a Rust error, and keep the module a thin adapter:

```rust
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;

#[derive(Debug)]
pub enum ParseError {
    Empty,
    BadDigit(char),
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Empty => f.write_str("empty input"),
            Self::BadDigit(c) => write!(f, "bad digit {c:?}"),
        }
    }
}

pyo3::create_exception!(fastparse, ParseFailed, PyException);

impl From<ParseError> for PyErr {
    fn from(err: ParseError) -> PyErr {
        match err {
            ParseError::Empty => PyValueError::new_err(err.to_string()),
            ParseError::BadDigit(_) => ParseFailed::new_err(err.to_string()),
        }
    }
}

pub fn parse_digits(s: &str) -> Result<u64, ParseError> {
    if s.is_empty() {
        return Err(ParseError::Empty);
    }
    s.chars().try_fold(0u64, |acc, c| {
        let digit = c.to_digit(10).ok_or(ParseError::BadDigit(c))?;
        acc.checked_mul(10)
            .and_then(|v| v.checked_add(u64::from(digit)))
            .ok_or(ParseError::BadDigit(c))
    })
}

/// The Python module `fastparse`. Its name must equal `[lib] name` in Cargo.toml.
#[pymodule]
mod fastparse {
    use pyo3::prelude::*;

    #[pymodule_export]
    use super::ParseFailed;

    #[pyfunction]
    fn parse(s: &str) -> Result<u64, super::ParseError> {
        super::parse_digits(s)
    }

    #[pyfunction]
    fn checksum(py: Python<'_>, data: Vec<u8>) -> u64 {
        // `data` is a Rust Vec, so the closure can run detached.
        py.detach(move || data.iter().map(|&b| u64::from(b)).sum())
    }
}
```

Rules:

- A `#[pyfunction]` can return `PyResult<T>` or `Result<T, E>` where
  `E: Into<PyErr>`. Map each Rust error variant to the Python exception class a
  caller catches. Use `create_exception!` for a domain error, and export it with
  `#[pymodule_export]`.
- Implement `From<E> for PyErr` only for a local `E` (`E0117` otherwise). pyo3 0.29
  removed the `From` impls for `str::Utf8Error`, `FromUtf16Error`, and
  `DecodeUtf16Error`: call `PyUnicodeDecodeError::new_err_from_utf8(py, bytes, e)`.
- Take arguments as Rust types (`&str`, `Vec<u8>`, `u64`) when the function does
  not need the Python object. PyO3 then raises `TypeError` on a bad type.
- Use `Bound<'py, T>` for a Python object during a call, and `Py<T>` to store one
  in a struct or move it to another thread. Convert with `.unbind()` and
  `.bind(py)`.

## Panics

PyO3 catches a panic at each `#[pyfunction]` and `#[pymethods]` entry and raises
`pyo3_runtime.PanicException`. That class derives from `BaseException`, not
`Exception`, so `except Exception` does not catch it, and it usually stops the
Python program. Never use a panic, `unwrap`, or `expect` for an input error. Under
`panic = "abort"` the Python process dies, so keep the default `panic = "unwind"`;
the `rust-panic-safety` skill, when it is installed, owns that policy.

## Attach and detach

A `Python<'py>` token proves that this thread is attached to the interpreter. On a
GIL build the attached thread holds the GIL; on a free-threaded build many threads
are attached at once.

- Wrap CPU-bound or blocking Rust work in `py.detach(|| ..)`. Without it, a long
  call stops every other Python thread on a GIL build, and it can stall a
  free-threaded build during a garbage collection.
- The closure must be `Ungil`, which is `Send` on stable Rust. `Bound`, `Borrowed`,
  and `Python` are not, so the compiler rejects them (`E0277`):

```rust,compile_fail,E0277
use pyo3::prelude::*;
use pyo3::types::PyString;

fn print_detached(py: Python<'_>) {
    let s = PyString::new(py, "attached only");
    py.detach(move || println!("{s:?}"));
}
```

- Call `Python::attach(|py| ..)` on a thread that Rust created before it touches
  Python. A thread that Python created through `threading` is attached already when
  it calls a `#[pyfunction]`.
- Use `pyo3::sync::PyOnceLock`, not `OnceLock` or `LazyLock`, for a value whose
  initializer calls Python: the standard types can deadlock.

Read `references/threads-and-classes.md` when you share a `#[pyclass]` between
threads, store Python objects in Rust, declare free-threaded support, or start a
Rust thread that calls back into Python.

## Build and install

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install maturin pytest
maturin develop                      # debug build, installs into the active venv
maturin develop --release            # before any timing or benchmark
maturin build --release --locked     # wheel in target/wheels/
```

- `maturin develop` needs an active venv or a `.venv` directory. Run it again
  after every Rust edit.
- Enable `abi3-py3x` (lowest is `abi3-py39`) to ship one wheel per platform for
  every CPython from that floor up. Set `requires-python` in `pyproject.toml` to
  the same floor. A free-threaded interpreter cannot load an `abi3` wheel: build a
  separate `cp314t` wheel with `maturin build -i python3.14t`.
- A wheel built on the host gets the manylinux tag of the newest glibc symbol it
  uses (`manylinux_2_34` from a glibc 2.39 host). Older distributions refuse it.

Read `references/build-and-wheels.md` when you choose the abi3 or `abi3t` floor,
build release wheels for several platforms, build without maturin, fix a macOS link
error, or print the interpreter configuration that PyO3 found.

## Verify

| Check | Command | Proves | Does not prove |
|-------|---------|--------|----------------|
| Rust logic | `cargo test --locked`, with `Python::initialize()` in each test that attaches | Error mapping and pure logic | Module name, link mode, wheel tag |
| Exports | `nm -D --defined-only target/release/lib<name>.so \| grep PyInit_` | The init symbol exists | That it matches the file name |
| Link mode | `ldd` on the `.so` in the wheel | No libpython dependency | glibc compatibility |
| Wheel tags | The wheel file name: `cp310-abi3-manylinux_2_34_x86_64` | Floor, ABI, platform | That an older system can install it |
| Binding | `pip install --force-reinstall target/wheels/<wheel>.whl` in a clean venv, then `python -m pytest tests` outside the source tree | Import, argument conversion, exception classes | Interpreters and platforms you did not test |

Run the wheel test on each interpreter you ship for (the abi3 floor, the newest
CPython, and 3.14t). Assert the
exception class in pytest (`pytest.raises(ValueError)`), and assert that a forced
panic is not an `Exception` subclass. A green `maturin develop` run proves only the
host interpreter and the debug profile.

## Related skills

Use these skills when they are installed: `rust-unsafe` (raw `pyo3::ffi` calls;
each `unsafe` block needs a `// SAFETY:` comment) and `ffi-error-progress-cancel`
(progress and cancellation across a boundary).
