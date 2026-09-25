# loom setup and a worked example

Deep reference for the loom section of `SKILL.md`, for loom 0.7.

Contents:

- Dependency and lint setup
- Statics and `UnsafeCell` under `cfg(loom)`
- Worked example: a publish flag
- Commands and search bounds

## Dependency and lint setup

Declare loom as a normal dependency under `cfg(loom)`, because the library itself imports it:

```toml
[target.'cfg(loom)'.dependencies]
loom = "0.7"

[lints.rust]
unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)'] }
```

- A `[target.'cfg(loom)'.dev-dependencies]` entry works only when every loom test is a unit
  test inside the same crate. With a loom test under `tests/`, the library build fails with
  E0433 (``cannot find module or crate `loom` in this scope``).
- Do not use a `loom` Cargo feature. `--all-features` turns it on, and then every ordinary test
  that touches the primitive panics outside `loom::model`.
- Put the lint entry in `[workspace.lints.rust]` when members use `[lints] workspace = true`.
  Cargo checks custom cfg names since 1.80. The entry keeps a `-D warnings` gate green.

## Statics and `UnsafeCell` under `cfg(loom)`

- loom atomics have no `const fn new`, so a `static` atomic cannot switch to loom. Put the
  atomics in a type that the test creates inside `loom::model`, or declare the static with
  `loom::lazy_static!` under `cfg(loom)`.
- `loom::cell::UnsafeCell::get` returns a tracked `ConstPtr`, not `*mut T`, so access the cell
  through `with` and `with_mut`. Give the `cfg(not(loom))` build a wrapper with the same two
  methods.

## Worked example: a publish flag

Gate the atomics in the library, and make the loom test call the crate's own type:

```rust
// src/lib.rs
#[cfg(loom)]
use loom::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
#[cfg(not(loom))]
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

/// Publishes one value from a writer thread to reader threads.
#[derive(Default)]
pub struct Mailbox {
    value: AtomicUsize,
    ready: AtomicBool,
}

impl Mailbox {
    pub fn new() -> Self {
        Self { value: AtomicUsize::new(0), ready: AtomicBool::new(false) }
    }

    pub fn publish(&self, value: usize) {
        self.value.store(value, Ordering::Relaxed);
        self.ready.store(true, Ordering::Release);
    }

    pub fn take(&self) -> Option<usize> {
        self.ready.load(Ordering::Acquire).then(|| self.value.load(Ordering::Relaxed))
    }
}
```

```rust
// tests/loom_mailbox.rs
#[cfg(loom)]
#[test]
fn reader_sees_published_value() {
    use loom::sync::Arc;
    use loom::thread;
    use my_crate::Mailbox;

    loom::model(|| {
        let mailbox = Arc::new(Mailbox::new());
        let writer = {
            let mailbox = Arc::clone(&mailbox);
            thread::spawn(move || mailbox.publish(42))
        };
        if let Some(value) = mailbox.take() {
            assert_eq!(value, 42);
        }
        writer.join().unwrap();
    });
}
```

If you change the `Release` store to `Relaxed`, loom fails this test with `left: 0, right: 42`
(loom 0.7.2, Rust 1.98.1).

## Commands and search bounds

```bash
RUSTFLAGS="--cfg loom" cargo test --locked --release --test 'loom_*'

# Bound the search when a run takes too long.
LOOM_MAX_PREEMPTIONS=3 RUSTFLAGS="--cfg loom" cargo test --locked --release --test 'loom_*'
```

`RUSTFLAGS` replaces the rustflags in `.cargo/config.toml`, so add any flag that the build
needs to the same variable.
