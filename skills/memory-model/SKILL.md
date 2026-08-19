---
name: memory-model
description: Use when you write or review Rust atomic operations, lock-free data structures, or publish/subscribe flags, when you choose between Ordering::Relaxed, Acquire, Release, AcqRel and SeqCst, when you place atomic fences, when you declare or review global state, or when you diagnose a data race that appears only on weakly ordered targets such as ARM64. Covers happens-before reasoning, valid orderings per operation, counter and stop-flag and publish patterns, compare-exchange rules, the choice between const, static, OnceLock, LazyLock and thread_local!, common ordering mistakes, and verification with Miri and loom. Triggers on "global variable", "global state", "static mut", "global static", "OnceLock", "LazyLock", "thread_local", "lazy_static", "once_cell", or any memory ordering question.
license: BSD-3-Clause
---

# Memory Model

## Purpose

Use this skill to select and review memory orderings in Rust. It gives you the
happens-before rules, a decision table for each ordering, the standard atomic
patterns, and the checks that prove the code is correct.

The default assumption in this skill is a **weakly ordered target** (ARM64,
POWER, RISC-V). On these targets the hardware reorders memory accesses unless
you request a barrier. Code that passes on x86 can fail on ARM64.

## When to use

- You must pick an ordering for a new atomic operation.
- You review a diff that adds `AtomicBool`, `AtomicU64`, `AtomicUsize`, or a CAS loop.
- You must explain the difference between acquire-release and sequential consistency.
- A concurrency bug reproduces on an ARM64 device but not on an x86 developer machine.
- You must decide if `Relaxed` is safe for a counter or for a stop flag.

## Core rules

Apply these five rules before you write any atomic code.

1. **Use the weakest ordering that is correct.** Do not start from `SeqCst`.
   Start from the data dependency, then select the ordering that publishes it.
2. **Ordering is a property of a pair, not of one operation.** A `Release`
   store is useless without a matching `Acquire` load of the same atomic.
3. **Atomics order the *other* data around them.** If the atomic carries no
   dependent data, `Relaxed` is usually enough.
4. **Do not use atomics to guard non-atomic data directly.** Use `Mutex`,
   `RwLock`, or an ownership transfer. Use the atomic only as the signal.
5. **Verify, do not assume.** Run the code under Miri and loom. Test on a
   weakly ordered device.

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
   `0`. The same declaration as a `static` reads back `3`. rustc warns with
   `const_item_interior_mutations`, clippy with
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

`LazyLock` is stable since 1.80.0 and `OnceLock` since 1.70.0. A workspace on a
newer toolchain needs no `lazy_static` or `static_init` dependency. Keep
`once_cell` while `rust-version` stays below 1.80.0, or while a global
initializer returns a `Result`. `OnceLock::get_or_try_init` is still unstable on
1.97.0. It fails with `error[E0658]` under the feature gate `once_cell_try`,
issue 109737.

```rust
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
    TABLE.lock().unwrap().insert(1, 42);
    DEPTH.set(DEPTH.get() + 1);
    println!("{:?} {} {}", CONFIG.get(), TABLE.lock().unwrap().len(), DEPTH.get());
}
```

Do not rewrite a `static mut` to an atomic without reading its type. An atomic
replaces a `static mut` that holds an integer or a `bool`. A `static mut` that
holds a `Vec` or a `String` needs `OnceLock` or `LazyLock` plus a `Mutex`. On
edition 2024 the `static_mut_refs` lint is deny-by-default, so every reference
to the static stops the build. See the `cargo-workflows` skill for the two exact
messages and the edition-2024 migration steps.

## Ordering strength

```text
Relaxed  <  Release/Acquire  <  AcqRel  <  SeqCst

Stronger ordering = more synchronization = more barriers = slower
Weaker ordering   = fewer barriers = faster = needs careful analysis
```

## Ordering reference

| Order | Rust | What it means |
|-------|------|---------------|
| Relaxed | `Ordering::Relaxed` | No ordering guarantee. Atomicity only. |
| Acquire | `Ordering::Acquire` | This load sees all writes made before the matching release store. |
| Release | `Ordering::Release` | All writes before this store become visible to a matching acquire load. |
| AcqRel | `Ordering::AcqRel` | Acquire and release together. Read-modify-write operations only. |
| SeqCst | `Ordering::SeqCst` | Total order across all SeqCst operations in all threads. |

## Valid orderings by operation type

| Operation type | Valid orderings |
|----------------|-----------------|
| Atomic load (`load`) | Relaxed, Acquire, SeqCst |
| Atomic store (`store`) | Relaxed, Release, SeqCst |
| Read-modify-write (`fetch_add`, `swap`, `compare_exchange`) | All orderings |
| Fence (`fence`, `compiler_fence`) | Acquire, Release, AcqRel, SeqCst |

An invalid ordering panics at run time. A `load` with `Release` or `AcqRel`
panics. A `store` with `Acquire` or `AcqRel` panics. A `fence` or a
`compiler_fence` with `Relaxed` panics. The rustc lint
`invalid_atomic_ordering` is deny-by-default and rejects these calls at compile
time when the ordering is a literal. It cannot see an ordering that arrives
through a variable, so the panic remains the last line of defence.

## Choosing the right ordering

```text
Use case?
+-- Counter or sequence number (order irrelevant)        -> Relaxed
+-- Stop or shutdown flag with no dependent data         -> Relaxed
+-- Stop or shutdown flag that publishes prior writes    -> Release (store), Acquire (load)
+-- Publish data from one thread to another              -> Release (store), Acquire (load)
+-- Read-modify-write that both consumes and publishes   -> AcqRel
+-- Reference counting                                   -> Relaxed (increment), AcqRel or Release+fence (decrement), Acquire (zero check)
+-- Mutual exclusion or lock implementation              -> AcqRel on the lock word
+-- Global order needed across several different atomics -> SeqCst (benchmark it)
```

## Pattern 1: counter or sequence number (Relaxed)

A counter that no other data depends on needs atomicity only. `Relaxed` gives
atomicity with no barrier.

```rust
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_ID: AtomicU64 = AtomicU64::new(0);

// Hand out a unique id. No other memory is published with it.
let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);

// Statistics counters follow the same rule.
struct Telemetry {
    total_sessions: AtomicU64,
}

impl Telemetry {
    fn record_session(&self) {
        self.total_sessions.fetch_add(1, Ordering::Relaxed);
    }

    fn snapshot(&self) -> u64 {
        self.total_sessions.load(Ordering::Relaxed)
    }
}
```

`fetch_add` with `Relaxed` is still atomic. Every increment is counted. Only
the ordering against *other* memory operations is dropped.

Do not use `Relaxed` here if the reader also reads a buffer that the counter
indexes. That buffer is dependent data, so the counter must publish it with
`Release`/`Acquire`.

## Pattern 2: publish/subscribe (Release store, Acquire load)

This is the core pattern. One thread writes data, then stores a flag. The other
thread loads the flag, then reads the data. The `Release`/`Acquire` pair creates
the happens-before edge that makes the data visible.

```rust
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

struct SharedState {
    ready: AtomicBool,
    data: Mutex<Option<u64>>, // Mutex guards the non-atomic payload.
}

let state = Arc::new(SharedState {
    ready: AtomicBool::new(false),
    data: Mutex::new(None),
});

// Publisher: write the payload first, then signal with a Release store.
*state.data.lock().unwrap() = Some(42);
state.ready.store(true, Ordering::Release);

// Subscriber: observe the signal with an Acquire load, then read the payload.
while !state.ready.load(Ordering::Acquire) {
    std::hint::spin_loop();
}
let value = state.data.lock().unwrap().unwrap(); // Guaranteed to observe 42.
```

Rules for this pattern:

- The store must be the **last** operation of the publisher. Any write after
  the `Release` store is not covered.
- The load must be the **first** operation of the subscriber. Any read before
  the `Acquire` load is not covered.
- Both sides must use the **same atomic**. A `Release` on atomic A does not
  synchronize with an `Acquire` on atomic B.
- The busy-wait loop must call `std::hint::spin_loop()`. A bare loop wastes
  power and can starve the publisher on a single core.
- Prefer a channel, `Condvar`, or a task waker over a spin loop when the wait
  can be long. Spin only for waits of a few hundred nanoseconds.

## Pattern 3: stop or shutdown flag

A stop flag that only terminates a loop, and publishes nothing else, can use
`Relaxed`. The reader may observe the flag a few iterations late. That delay is
acceptable for loop teardown.

```rust
use std::sync::atomic::{AtomicBool, Ordering};

// Signal side.
stop.store(true, Ordering::Relaxed);

// Poll side: the loop body touches no data published by the signaller.
while !stop.load(Ordering::Relaxed) {
    accept_one_connection();
}
```

Use `Release`/`Acquire` instead as soon as the signaller writes any state that
the stopping thread must observe. This is the safe default in review, because
the dependency is easy to add later and easy to miss.

```rust
// Signal side: Release publishes every write made before the flag.
shutdown.store(true, Ordering::Release);

// Worker side: Acquire observes those writes together with the flag.
if shutdown.load(Ordering::Acquire) {
    return Err(Error::Cancelled);
}
```

Guidance:

- Poll the flag at a **coarse** granularity. One check per work item or per
  loop chunk is enough. A check inside the innermost arithmetic loop costs
  more than it saves.
- Share the flag as `Arc<AtomicBool>` so the signaller and the worker keep it
  alive independently.
- Return a distinct `Cancelled` error variant. Do not return `Ok` from a
  cancelled operation, and do not panic.
- For cancellation that crosses a foreign function interface, see the
  `ffi-error-progress-cancel` skill.

## Pattern 4: progress reporting

Do not build a polled `AtomicU64` progress counter by default. Push progress
through a callback or a channel instead. A push design has no ordering question
to get wrong, and it does not force the reader to spin.

Use a polled atomic counter only when the consumer already runs a loop that can
sample it. Then publish it with `Release` and read it with `Acquire`, because
the reader almost always reads other state that the counter refers to.

Keep the progress path observational. Progress must never feed back into the
computation, and the callback must be cheap and non-blocking, because it runs
on the worker thread.

## Pattern 5: reference counting

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

The decrement must not be `Relaxed`. The destructor reads the object, so it
must acquire the writes of all other owners.

## Fences

A fence orders the operations of the thread that executes it. Use a fence when
the ordering does not belong to one specific atomic access.

| Call | Effect |
|------|--------|
| `fence(Ordering::Release)` | No earlier memory operation moves after the fence. |
| `fence(Ordering::Acquire)` | No later memory operation moves before the fence. |
| `fence(Ordering::AcqRel)` | Both directions. |
| `fence(Ordering::SeqCst)` | Both directions plus participation in the SeqCst total order. |
| `compiler_fence(...)` | Blocks compiler reordering only. Emits no CPU barrier. |

Use `compiler_fence` only for signal handlers and interrupt handlers on the
same thread. It gives no protection against another core.

Prefer an ordered atomic operation over a separate fence. A fence is harder to
review, because the pairing is not visible at the access site.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `Relaxed` used for publish/subscribe | Use `Release` on the store and `Acquire` on the load. |
| `SeqCst` used everywhere "to be safe" | Derive the ordering from the data dependency. Benchmark before you keep `SeqCst`. |
| `Release` on one atomic paired with `Acquire` on a different atomic | Pair the ordering on the same atomic, or use a `SeqCst` fence. |
| Writes placed after the `Release` store | Move every published write before the store. |
| Reads placed before the `Acquire` load | Move every dependent read after the load. |
| `unsafe` mutable statics used for shared data | Use `Mutex`, `RwLock`, `OnceLock`, or an atomic. |
| `const` used for shared state with interior mutability | Declare it `static`. A `const` is inlined, so every use site mutates a fresh copy. |
| Non-atomic data guarded only by an atomic flag | Guard the payload with `Mutex`/`RwLock`, and keep the atomic as the signal. |
| `Relaxed` decrement in a reference count | Use `AcqRel` on the decrement. |
| `compare_exchange` failure ordering stronger than success ordering | Weaken the failure ordering. The failure path is a load. |
| `compare_exchange_weak` used without a retry loop | Use `compare_exchange` for a single attempt, or wrap the weak form in a loop. |
| Busy-wait loop without `spin_loop()` | Add `std::hint::spin_loop()`, or block on a channel or `Condvar`. |
| ARM64 assumed to behave like x86 TSO | Test on a weakly ordered device and run Miri. |

## Weakly ordered targets

ARM64 is weakly ordered. Plan for it:

- `Relaxed` loads and stores cost no barrier and give no ordering.
- `Acquire` and `Release` cost real instructions. The compiler emits the
  ordered load and store forms (`ldar`, `stlr`), or an explicit `dmb` barrier.
  On x86 the same orderings need no extra instruction.
- `SeqCst` is never cheaper than acquire-release, and it is more expensive on
  some targets. Measure the cost before you keep it.
- An incorrect ordering can pass every test on x86, because x86 is TSO and
  gives acquire-release semantics for free.
- Apple Silicon uses the same ARM64 memory model. A macOS ARM64 machine can
  reproduce these bugs, so run the suite there as well when it is available.

See [references/platform-memory-models.md](references/platform-memory-models.md)
for the happens-before rules, the platform table, the C++ equivalence table,
the compare-exchange rules, and the quick selection guide.

## Verification

Run these checks on any change that adds or edits an atomic operation.

```bash
# Miri detects data races and undefined behaviour in the tested code paths.
cargo +nightly miri test --locked

# Run the full suite on a weakly ordered host as well when one is available.
cargo test --locked
```

- Use **Miri** for data races and undefined behaviour. See the
  `rust-sanitizers-miri` skill.
- Use **loom** to model-check an ordering. Loom explores the legal
  interleavings and the legal reorderings of your atomics, so it finds bugs
  that Miri and hardware tests miss. See the `rust-test-tools` skill.
- Test on a real weakly ordered device before you ship a lock-free structure.

## Review checklist

Check each item before you approve a diff that touches atomics.

- [ ] Every `Release` store has a matching `Acquire` load of the same atomic.
- [ ] Every ordering is the weakest one that is still correct, with a comment
      that names the data it publishes.
- [ ] No `SeqCst` remains without a stated multi-atomic ordering requirement.
- [ ] Non-atomic shared data is guarded by a lock, not by the flag alone.
- [ ] Reference-count decrements use `AcqRel` or `Release` plus an `Acquire` fence.
- [ ] `compare_exchange` failure ordering is not stronger than success ordering,
      and is not `Release` or `AcqRel`.
- [ ] Busy-wait loops call `std::hint::spin_loop()` or are replaced by blocking.
- [ ] Stop and cancel flags are polled at a coarse granularity.
- [ ] The change is covered by a Miri run, and by a loom test if it is lock-free.

## Related skills

- `rust-sanitizers-miri` — Miri and the sanitizers detect memory-ordering and data-race defects.
- `rust-test-tools` — loom model checking for atomic ordering.
- `rust-unsafe` — the unsafe rules around raw pointers and atomic-guarded data.
- `rust-async-internals` — how async task scheduling interacts with atomics and wakers.
- `rust-performance` — measure the barrier cost before you keep a stronger ordering.
- `ffi-error-progress-cancel` — cancellation and progress across a foreign function interface.
