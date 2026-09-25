---
name: memory-model
description: Use when choosing or reviewing atomic orderings (Ordering::Relaxed, Acquire, Release, AcqRel, SeqCst) or declaring global state (static mut, const vs static, OnceLock, LazyLock, thread_local), including happens-before edges, fences, compare-exchange or fetch_update loops, lock-free code, and a data race seen only on ARM64. Triggers on "global variable", "lazy_static", "once_cell".
license: BSD-3-Clause
---

# Memory Model

Assume a weakly ordered target (ARM64, RISC-V, POWER). These CPUs reorder
memory accesses that x86 keeps in order. An ordering bug can pass every test on
x86 and fail on a phone or on an Apple silicon Mac.

## Core rules

1. **Derive the ordering from the data it publishes.** Name the writes that the
   reader must see, then pick the weakest ordering that publishes them. Do not
   start from `SeqCst`: it hides the missing reasoning, and it does not repair
   an unpaired or misplaced access.
2. **Ordering is a property of a pair.** A `Release` store synchronizes
   with an `Acquire` load of the same atomic that reads the stored value.
3. **An atomic that publishes nothing needs only `Relaxed`.** Counters and
   unique ids are the usual case.
4. **Prefer a lock, `OnceLock`, or a channel over hand-rolled publication.**
   To publish non-atomic data through a flag you need `UnsafeCell` and
   `unsafe`. Treat that code as a lock-free structure: it needs a loom test and
   an unsafe review (the `rust-unsafe` skill, when it is installed).
5. **A pass on x86 proves nothing about ordering.** The compiler also reorders
   `Relaxed` accesses, so a `Relaxed` bug can appear on x86 after an unrelated
   optimization change. Use the checks in [Verification](#verification).

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `Relaxed` used for publish/subscribe | Use `Release` on the store and `Acquire` on the load. |
| `SeqCst` used everywhere "to be safe" | Derive the ordering from the data dependency. Keep `SeqCst` only for a named multi-atomic order. |
| `Release` on one atomic paired with `Acquire` on a different atomic | Pair the operations on the same atomic, or build an explicit synchronization chain. A `SeqCst` fence alone does not connect different atomics. |
| `static mut` used for shared data | Use `Mutex`, `RwLock`, `OnceLock`, `LazyLock`, or an atomic. |
| `const` used for shared state with interior mutability | Declare it `static`. A `const` is inlined, so every use site mutates a fresh copy. |
| Non-atomic data guarded only by an atomic flag | Guard the payload with a lock. Hand-rolled `UnsafeCell` publication needs a loom test and an unsafe review. |
| `Relaxed` decrement in a reference count | Use `AcqRel`, or `Release` plus an `Acquire` fence before the destructor. |
| `compare_exchange` on a pointer or index that can be freed and reused (ABA) | Pack a generation counter with the value, or use epoch-based reclamation. |
| Side effect in an `update` or `try_update` closure | Keep the closure free of side effects. It runs again after each lost race. |
| `compiler_fence` used to order memory between threads | Use `fence` or an ordered atomic. `compiler_fence` emits no CPU barrier. |
| ThreadSanitizer reports a race on fence-based code | Do not strengthen the ordering to silence it. TSan does not support `fence`, so the report can be false. Check with Miri or loom. |
| ARM64 assumed to behave like x86 | Run Miri and loom, and test on a weakly ordered host. |

## Verification

Match the check to the risk. Each check misses a class of bugs.

```bash
# Miri: data races and UB on the executed paths, one schedule per seed.
MIRIFLAGS="-Zmiri-many-seeds=0..16" cargo +nightly miri test --locked <test_filter>

# loom: all interleavings of a loom-instrumented test.
RUSTFLAGS="--cfg loom" cargo test --locked --release --test <loom_target>

# Hardware: the normal suite on an aarch64 host or device.
cargo test --locked
```

- **Miri** runs, when a nightly toolchain with the `miri` component is
  installed, for any change that adds or edits an atomic operation that a test
  reaches. Without it, report the atomic change as not checked by Miri. Each
  seed is one schedule, and Miri emulates only some weak memory effects, so a
  pass is evidence, not proof. Miri model flags and CI setup live in the
  `rust-sanitizers-miri` skill, when it is installed.
- **loom** runs for a lock-free structure, a hand-written lock, or publication
  through `UnsafeCell`. It checks only code built on its types: `loom::sync`
  atomics, `loom::thread`, and `loom::cell::UnsafeCell` for the payload. A
  payload in `std::cell::UnsafeCell` is invisible to loom, so gate the cell type
  with `cfg(loom)` too. Setup lives in the `rust-test-tools` skill, when it is
  installed. Know its two limits. It treats `SeqCst` loads and stores as
  `AcqRel`, so a failure in `SeqCst` code can be a false alarm (`fence(SeqCst)`
  is modelled). It does not explore load buffering, so a pass is not proof. A
  `LOOM_MAX_PREEMPTIONS` bound also limits what a pass covers.
- **A weakly ordered host** runs the suite before you ship a lock-free
  structure. An Apple silicon Mac qualifies. A finite run that does not fail
  proves only that this run did not fail.

## Review checklist

Check each item before you approve a diff that touches atomics.

- [ ] Every `Release` store has a matching `Acquire` load of the same atomic.
- [ ] Every ordering is the weakest one that is still correct, with a comment
      that names the data it publishes.
- [ ] No `SeqCst` remains without a stated multi-atomic ordering requirement.
- [ ] Non-atomic shared data is guarded by a lock, not by the flag alone.
- [ ] Reference-count decrements use `AcqRel`, or `Release` plus an `Acquire`
      fence.
- [ ] Every compare-exchange and `update` failure ordering is `Relaxed`,
      `Acquire`, or `SeqCst`, and is chosen for what the losing thread reads.
- [ ] Every CAS on a pointer or index is safe against ABA.
- [ ] New code uses `update` or `try_update`, not `fetch_update`, unless the
      MSRV is below 1.95.
- [ ] Busy-wait loops call `std::hint::spin_loop()` or are replaced by blocking.
- [ ] The change has a Miri run, or the report says it is not checked by Miri
      because no nightly `miri` component is installed. A lock-free change also
      has a loom test.

## Global state

A global is shared state, so every rule above applies to it. Choose the
declaration form first. Each form fails in a different way.

| Form | Use it for | Cost |
|------|------------|------|
| `const NAME: T` | A compile-time value with no identity: a limit, a table of `&str`. | Inlined at every use site. No address. No state. |
| `static NAME: T` | Shared state with a `const` initializer: an atomic, a `Mutex`. | One address for the process. `T` must be `Sync`. |
| `static NAME: OnceLock<T>` | A value written once at start-up by its owner. | One atomic load per read. `get` returns `Option<&T>`. |
| `static NAME: LazyLock<T>` | A value computed on first use from a fixed initializer. | One atomic load per read. Derefs to `&T`. |
| `thread_local! { static NAME: T }` | Per-thread scratch: a buffer, a recursion depth, an RNG. | No synchronization. One value per thread. |

Five rules decide the choice. Each one is a compile error or a silent bug.

1. **A `static` needs `Sync`.** `static BAD: RefCell<u32>` is rejected with
   `error[E0277]: RefCell<u32> cannot be shared between threads safely` and the
   note `shared static variables must have a type that implements Sync`. Put the
   value in a `Mutex` or an `RwLock`, or use an atomic.
2. **A `const` has no single address.** The compiler inlines the value at every
   use site, so interior mutability in a `const` mutates a fresh temporary and
   discards it. `const HITS: AtomicUsize` incremented three times reads back
   `0`. The same declaration as a `static` reads back `3`. rustc 1.93 and later
   warns with `const_item_interior_mutations`, and clippy warns with
   `clippy::declare_interior_mutable_const`. Neither is an error, so this ships.
3. **`OnceLock` and `LazyLock` differ on panic.** When the initializer panics,
   `OnceLock::get_or_init` leaves the cell empty and the next call retries.
   `LazyLock` poisons for the life of the process: every later deref panics with
   `LazyLock instance has previously been poisoned`. Use `LazyLock` for an
   initializer that cannot fail. Use `OnceLock` when the value arrives from
   outside `main`, or when the first attempt can fail.
4. **A `static` is never dropped.** Process exit runs no `Drop` on a `static`,
   so a flush-on-drop writer in a global loses its last buffer. Flush it
   explicitly before `main` returns.
5. **`thread_local!` destructors have holes.** A destructor runs when its thread
   exits, but std documents that on Unix with pthread-based TLS it does not run
   for a value on the main thread. Never put required cleanup in thread-local
   state.

Do not rewrite a `static mut` to an atomic without reading its type. An atomic
replaces a `static mut` that holds an integer or a `bool`. A `static mut` that
holds a `Vec` or a `String` needs `OnceLock` or `LazyLock` plus a `Mutex`. On
edition 2024 the `static_mut_refs` lint is deny-by-default, so every reference
to the static stops the build. The `cargo-workflows` skill, when it is
installed, has the two exact messages and the edition-2024 migration steps.

`LazyLock` is stable since 1.80.0 and `OnceLock` since 1.70.0. A workspace on a
newer toolchain needs no `lazy_static` or `static_init` dependency. Keep
`once_cell` while `rust-version` stays below 1.80.0, or while a global
initializer returns a `Result`. `OnceLock::get_or_try_init` is still unstable on
1.98.1. It fails with `error[E0658]` under the feature gate `once_cell_try`,
issue 109737.

```rust,run
use std::cell::Cell;
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex, OnceLock};

// One address, computed on first deref from a fixed initializer.
static TABLE: LazyLock<Mutex<HashMap<u32, u64>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

// One address, written once at start-up by the owner of the value.
static CONFIG: OnceLock<String> = OnceLock::new();

// One value per thread. The `const` block skips the lazy-init check per access.
thread_local! {
    static DEPTH: Cell<u32> = const { Cell::new(0) };
}

fn main() {
    CONFIG.set(String::from("prod")).expect("set exactly once");
    TABLE.lock().expect("TABLE poisoned").insert(1, 42);
    DEPTH.set(DEPTH.get() + 1);
    let len = TABLE.lock().expect("TABLE poisoned").len();
    println!("{:?} {} {}", CONFIG.get(), len, DEPTH.get());
}
```

## Orderings

| Ordering | Valid on | Guarantee |
|----------|----------|-----------|
| `Relaxed` | load, store, read-modify-write | Atomicity and one modification order per atomic. No order for other memory. |
| `Acquire` | load, read-modify-write, fence, compiler_fence | When it reads the value of a `Release` store, every write before that store is visible after it. |
| `Release` | store, read-modify-write, fence, compiler_fence | Publishes every earlier write to an `Acquire` load that reads this value. |
| `AcqRel` | read-modify-write, fence, compiler_fence | `Acquire` on the read half, `Release` on the write half. |
| `SeqCst` | all | Acquire and release, plus one total order over all `SeqCst` operations. |

An invalid ordering panics at run time: a `load` with `Release` or `AcqRel`, a
`store` with `Acquire` or `AcqRel`, a `fence` or `compiler_fence` with
`Relaxed`, and a compare-exchange or `update` failure ordering of `Release` or
`AcqRel`. The rustc lint `invalid_atomic_ordering` is deny-by-default and
rejects these calls at compile time when the ordering is a literal. It cannot
see an ordering that arrives through a variable, so the panic remains the last
line of defence.

## Choosing an ordering

```text
Use case                                                  Ordering
Counter, unique id, or statistic                          Relaxed
Stop flag or progress counter; reader uses nothing else   Relaxed
Stop flag or progress counter; reader then reads state    Release store, Acquire load
Publish data from one thread to another                   Release store, Acquire load
Read-modify-write that both consumes and publishes        AcqRel
Reference count                                           Relaxed increment;
                                                          Release or AcqRel decrement;
                                                          Acquire (load or fence) before the destructor
Lock word of a hand-written mutex or spinlock             Acquire on the lock CAS (Relaxed on failure);
                                                          Release on unlock
Global order across several different atomics             SeqCst on every participating access
```

The lock row matches the std futex mutex:
`compare_exchange(UNLOCKED, LOCKED, Acquire, Relaxed)` to lock and
`swap(UNLOCKED, Release)` to unlock. `SeqCst` is needed only when correctness
depends on two different atomics being seen in one global order. Read
[references/platform-memory-models.md](references/platform-memory-models.md)
when you must justify `SeqCst` with a Dekker-style argument, port C++ atomics,
need the formal happens-before rules, or need the per-target barrier and
compare-exchange cost.

## Pattern 1: counter or unique id (Relaxed)

```rust
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_ID: AtomicU64 = AtomicU64::new(0);

// Hand out a unique id. No other memory is published with it.
fn next_id() -> u64 {
    NEXT_ID.fetch_add(1, Ordering::Relaxed)
}
```

`fetch_add` with `Relaxed` is still atomic, so every increment is counted. Only
the order against other memory is dropped. The counter stops being `Relaxed`
when the reader uses it to index a buffer that the writer filled: that buffer is
dependent data.

## Pattern 2: publish/subscribe (Release store, Acquire load)

One thread writes data, then stores a flag. The other thread loads the flag,
then reads the data. The `Release`/`Acquire` pair creates the happens-before
edge that makes the data visible.

```rust,run
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::thread;

static DATA: AtomicU64 = AtomicU64::new(0);
static READY: AtomicBool = AtomicBool::new(false);

fn main() {
    thread::scope(|s| {
        s.spawn(|| {
            // Publisher: every write the reader needs comes before the Release store.
            DATA.store(42, Ordering::Relaxed);
            READY.store(true, Ordering::Release);
        });
        s.spawn(|| {
            // Subscriber: the Acquire load that reads `true` makes DATA == 42 visible.
            while !READY.load(Ordering::Acquire) {
                std::hint::spin_loop();
            }
            assert_eq!(DATA.load(Ordering::Relaxed), 42);
        });
    });
}
```

- Put every published write before the `Release` store. A write after the
  store is not published.
- Put every dependent read after the `Acquire` load. A read before the load is
  not covered.
- Call `std::hint::spin_loop()` in a busy-wait. It is a CPU hint, not a yield
  to the scheduler. Block on a channel, a `Condvar`, or `thread::park` when the
  wait is not short and bounded.

## Pattern 3: stop flag and progress counter

A stop flag that only ends a loop can be `Relaxed`. The worker can see the flag
a few iterations late, and loop teardown accepts that delay. Use
`Release`/`Acquire` as soon as the signaller writes state that the worker reads
after it stops, such as a reason or a new configuration. In review, ask for
`Release`/`Acquire` unless a comment states that the flag publishes nothing.
The dependency is easy to add later and easy to miss.

A polled progress counter follows the same rule: `Relaxed` when the reader only
displays the number, `Release`/`Acquire` when the reader then reads the state
that the number refers to. A progress callback or a channel needs no ordering
choice. The `ffi-error-progress-cancel` skill, when it is
installed, covers cancellation and progress across a foreign function interface.

## Pattern 4: reference counting

```rust
use std::sync::atomic::{AtomicUsize, Ordering};

// Increment: no data is published, and the object is already alive.
count.fetch_add(1, Ordering::Relaxed);

// Decrement: AcqRel, so the thread that observes zero also observes every
// write made by every other owner before it dropped its reference.
if count.fetch_sub(1, Ordering::AcqRel) == 1 {
    // This thread holds the last reference. Destroy the object here.
}
```

The destructor reads the object, so the decrement must acquire the writes of
all other owners. std `Arc` uses a `Release` decrement and a `fence(Acquire)` on
the zero path. Both forms are correct.

## Compare-exchange and update loops

```rust,run
use std::sync::atomic::{AtomicUsize, Ordering};

fn main() {
    let val = AtomicUsize::new(0);

    // Strong CAS: one attempt, no spurious failure. The failure ordering is
    // chosen independently of the success ordering (Rust 1.64 and later).
    assert_eq!(val.compare_exchange(0, 1, Ordering::Relaxed, Ordering::Acquire), Ok(0));

    // Weak CAS: it can fail spuriously, so use it only in a loop that feeds the
    // observed value back into the next attempt.
    let mut current = val.load(Ordering::Relaxed);
    loop {
        match val.compare_exchange_weak(current, current + 1, Ordering::AcqRel, Ordering::Relaxed) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }

    // `update` (1.95+) writes that loop and returns the previous value.
    assert_eq!(val.update(Ordering::AcqRel, Ordering::Relaxed, |v| v + 1), 2);

    // `try_update` (1.95+) stops without a write when the closure returns None.
    assert_eq!(val.try_update(Ordering::AcqRel, Ordering::Relaxed, |v| v.checked_sub(10)), Err(3));
    assert_eq!(val.load(Ordering::Relaxed), 3);
}
```

- **Failure ordering.** It can be `Relaxed`, `Acquire`, or `SeqCst`. `Release`
  and `AcqRel` are invalid, because a failed exchange writes nothing. Since Rust
  1.64 the failure ordering can be stronger than the success ordering. Do not
  weaken a failure ordering only to match the success ordering.
- **Choose each ordering for its own path.** The success ordering covers what
  the winner publishes or consumes. The failure ordering covers what the loser
  reads next. `Relaxed` on failure is correct when the loser only retries.
- **Weak or strong.** Use `compare_exchange_weak` only inside a retry loop.
  Read
  [references/platform-memory-models.md](references/platform-memory-models.md#platform-memory-models)
  when you choose between the weak and strong form on an LL/SC target or in a
  hot loop.
- **`fetch_update` is being renamed.** Use `update` (the closure always returns
  a value) or `try_update` (the closure returns `Option`). Both are stable since
  1.95. `try_update` has the same arguments and result as `fetch_update`, so
  rename the call. The std source marks `fetch_update` deprecated since 1.99.0:
  on 1.98 only the allow-by-default `deprecated_in_future` lint reports it, and
  Rust 1.99 (due 2026-10-01) makes it a `deprecated` warning that fails a
  `-D warnings` gate. Keep `fetch_update` only while `rust-version` is below
  1.95.

## Fences

Prefer an ordered atomic operation over a separate `fence`, because the pairing
of a fence is not visible at the access site. A fence synchronizes only through
an atomic access. Read
[references/platform-memory-models.md](references/platform-memory-models.md#fences)
when you write or review a `fence` or `compiler_fence`.

## Related skills

Use these skills when they are installed: `rust-send-sync` for `Send` and `Sync`
bounds before any ordering question, `rust-async-internals` for tokio task,
cancellation, and runtime behavior, and `rust-performance` to measure the
barrier cost before you keep a stronger ordering.
