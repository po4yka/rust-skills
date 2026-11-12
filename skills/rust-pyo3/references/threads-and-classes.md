# Threads and classes

Contents:

- `#[pyclass]` borrow rules
- Thread-safe class state
- Python objects held by Rust
- Rust threads that call Python
- Single initialization
- Free-threaded audit

The facts are for pyo3 0.30.1 (2026-11-12). The borrow and free-threaded results
were measured with CPython 3.13 and 3.14t on x86_64 Linux.

## `#[pyclass]` borrow rules

A `#[pyclass]` must be `Send` and `Sync`: Python can drop or read it on any
thread. PyO3 guards the Rust value with a runtime borrow flag, like a `RefCell`.
A `&self` method takes a shared borrow; a `&mut self` method takes an exclusive
borrow for the whole call. A second call that overlaps an exclusive borrow raises
`RuntimeError: Already borrowed`. Overlap happens when:

- the `&mut self` method calls `py.detach` and another Python thread calls in;
- the `&mut self` method calls Python code that calls back into the same object;
- two threads call in at once on a free-threaded interpreter.

`#[pyclass(unsendable)]` drops the `Send` and `Sync` requirement and panics when
another thread uses the object. Do not use it for a type that Python code can
share.

## Thread-safe class state

Make the class `frozen` and put the mutable state behind atomics or a lock. A
`frozen` class has only `&self` methods, so no call takes the exclusive borrow:

```rust
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::prelude::*;

#[pyclass(frozen)]
struct Stats {
    hits: AtomicU64,
    names: Mutex<Vec<String>>,
}

#[pymethods]
impl Stats {
    #[new]
    fn new() -> Self {
        Self { hits: AtomicU64::new(0), names: Mutex::new(Vec::new()) }
    }

    fn hit(&self) -> u64 {
        self.hits.fetch_add(1, Ordering::Relaxed) + 1
    }

    fn add_name(&self, name: String) {
        // The guard lives only inside this method, and no Python call runs under it.
        let mut names = self.names.lock().unwrap_or_else(|e| e.into_inner());
        names.push(name);
    }
}
```

Never hold a `std::sync::Mutex` guard across a call into Python. That call can
detach, and on a GIL build another thread then holds the GIL while it waits on the
lock: neither thread can continue. Copy the data out and drop the guard before the
call.

## Python objects held by Rust

`Bound<'py, T>` lives only while the thread is attached. Store `Py<T>` in a
struct, a channel, or a static, and call `.bind(py)` to use it:

```rust
use pyo3::prelude::*;
use pyo3::types::PyList;

#[pyclass(frozen)]
struct Sink {
    target: Py<PyList>,
}

#[pymethods]
impl Sink {
    #[new]
    fn new(target: Bound<'_, PyList>) -> Self {
        Self { target: target.unbind() }
    }

    fn push(&self, py: Python<'_>, value: i64) -> PyResult<()> {
        self.target.bind(py).append(value)
    }
}
```

A `Py<T>` dropped on a detached thread is not freed at once. PyO3 queues the
decrement and applies it at the next attach.

## Rust threads that call Python

Wrap each call in `Python::attach`. Detach the parent thread while it waits for
the children, or a child that needs to attach blocks on a GIL build:

```rust
use pyo3::prelude::*;

#[pyfunction]
fn call_in_threads(py: Python<'_>, callback: Py<PyAny>, n: usize) -> PyResult<()> {
    py.detach(|| {
        std::thread::scope(|scope| {
            let handles: Vec<_> = (0..n)
                .map(|i| {
                    let callback = &callback;
                    scope.spawn(move || Python::attach(|py| callback.call1(py, (i,)).map(drop)))
                })
                .collect();
            handles
                .into_iter()
                .map(|h| h.join().unwrap_or_else(|p| std::panic::resume_unwind(p)))
                .collect::<PyResult<()>>()
        })
    })
}
```

`Python::attach` panics during interpreter shutdown. Use `Python::try_attach`,
which returns `None` then, on a thread that can outlive the interpreter.

## Single initialization

`std::sync::OnceLock`, `LazyLock`, `once_cell`, and `lazy_static` can deadlock when
the initializer calls Python: the initializer can detach, a second attached thread
blocks on the lock, and on a GIL build the first thread cannot re-attach. Use
`pyo3::sync::PyOnceLock`:

```rust
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::PyType;

static DECIMAL: PyOnceLock<Py<PyType>> = PyOnceLock::new();

fn decimal_type(py: Python<'_>) -> PyResult<&Bound<'_, PyType>> {
    DECIMAL.import(py, "decimal", "Decimal")
}
```

## Free-threaded audit

pyo3 0.28 and later declare every module free-threading safe. Safe Rust keeps that
promise: `Send` and `Sync` on each `#[pyclass]` and the borrow flag cover the data.
Before you ship a `cp314t` wheel, search for code that used the `Python` token as
a lock:

```bash
rg -n 'unsafe|static mut|UnsafeCell|assume_attached' src/
```

Run the pytest suite under 3.14t with threads that call the same objects at once.
Add `#[pymodule(gil_used = true)]` only to buy time for that audit; it turns the
GIL back on for the whole process.
