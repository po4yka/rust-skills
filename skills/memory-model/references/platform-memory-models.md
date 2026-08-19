# Platform Memory Models Reference

Deep reference for the `memory-model` skill: happens-before, platform tables,
C++ equivalence, sequential consistency, compare-and-swap, and a quick
selection guide.

## Happens-before relation

A **happens-before** (HB) relation between operation A and operation B means:
the effects of A are guaranteed to be visible when B executes.

You establish HB in three ways:

1. **Sequenced-before** — program order inside a single thread.
2. **Synchronizes-with** — a release store synchronizes-with an acquire load
   that reads the value written by that store.
3. **Transitivity** — if A HB B and B HB C, then A HB C.

```text
Thread 1:                    Thread 2:
x.lock() = 42;  <--------------------------------------
flag.store(true,             while (!flag.load(
  Release);      - sync-with -  Acquire)) {}
                             assert(x.lock() == 42);  // HB guarantees this
```

Consequences you must respect:

- A release store publishes only the writes that come **before** it in program
  order. A write placed after the store is not published by it.
- An acquire load covers only the reads that come **after** it in program
  order. A read placed before the load is not covered.
- The relation is per-atomic. A release on atomic A does not synchronize with
  an acquire on atomic B.

## Platform memory models

| Platform | Default ordering | Barrier cost | Notes |
|----------|------------------|--------------|-------|
| x86 / x86-64 | TSO (total store order) | Acquire and Release are free | SeqCst needs `mfence` or a locked instruction |
| **ARM64 (Android, Linux, iOS, Apple Silicon)** | **Weakly ordered** | **All barriers explicit** | Most permissive reordering of the common targets |
| POWER | Weakly ordered | Explicit | Weaker than ARM in some cases |
| RISC-V | RVWMO | Defined per instruction | Fence granularity is per access type |

ARM64 implications:

- Acquire and release cost real instructions. The compiler emits the ordered
  load and store forms (`ldar`, `stlr`), or an explicit `dmb` barrier.
- SeqCst is never cheaper than acquire-release, and it is more expensive on
  some targets. Measure it on the target before you keep it.
- A defect can hide on x86, because x86 gives acquire-release semantics for
  free, and then surface on an ARM64 phone or an Apple Silicon machine.
- Apple Silicon uses the same ARM64 memory model as an ARM64 phone. Use a
  macOS ARM64 machine as a second reproduction host when one is available.
- Always test on a device or validate with Miri:
  `cargo +nightly miri test --locked`.

## C++ / Rust ordering equivalence

Use this table when you read literature, standards text, or C++ source.

| C++ | Rust | Notes |
|-----|------|-------|
| `memory_order_relaxed` | `Ordering::Relaxed` | |
| `memory_order_acquire` | `Ordering::Acquire` | |
| `memory_order_release` | `Ordering::Release` | |
| `memory_order_acq_rel` | `Ordering::AcqRel` | Read-modify-write only |
| `memory_order_seq_cst` | `Ordering::SeqCst` | |
| `memory_order_consume` | (use `Acquire`) | Consume is deprecated in practice |
| `atomic_thread_fence(acquire)` | `fence(Ordering::Acquire)` | |
| `atomic_signal_fence` | `compiler_fence(Ordering::*)` | Compiler barrier only |

Rust has no `Ordering::Consume`. Map C++ consume code to `Acquire`.

## SeqCst total order

`Ordering::SeqCst` establishes one total order across all SeqCst operations in
all threads. Every thread observes those operations in the same order.

Use SeqCst only when correctness depends on several **different** atomics being
observed in a consistent global order. The classic case is Dekker-style
mutual exclusion, where two threads each store to their own flag and then load
the other flag. Acquire-release is not enough there, because a store-load pair
on two different atomics can be reordered.

If you cannot name the second atomic that needs the shared order, you do not
need SeqCst. Benchmark the cost on a weakly ordered target before you keep it.

## CAS (compare-and-swap) in Rust

```rust
use std::sync::atomic::{AtomicUsize, Ordering};

let val = AtomicUsize::new(0);

// Strong CAS: never fails spuriously. Use for a single attempt.
match val.compare_exchange(0, 42, Ordering::AcqRel, Ordering::Relaxed) {
    Ok(prev) => { /* swapped; prev == 0 */ }
    Err(actual) => { /* failed; actual is the current value */ }
}

// Weak CAS: may fail spuriously. Use it only inside a retry loop, where it is
// cheaper than the strong form on ARM64, because it maps to one LL/SC attempt.
// Feed the observed value back into the next attempt. Do not retry with the
// same expected value, because a racing writer then spins the loop forever.
let mut current = val.load(Ordering::Relaxed);
loop {
    let next = current + 1;
    match val.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Relaxed) {
        Ok(_) => break,
        Err(actual) => current = actual,
    }
}

// `fetch_update` wraps the same loop. Prefer it when the new value is a pure
// function of the old value.
let _ = val.fetch_update(Ordering::AcqRel, Ordering::Relaxed, |v| Some(v + 1));
```

CAS ordering rules:

- The **failure** ordering must not be stronger than the success ordering.
- The failure ordering cannot be `Release` or `AcqRel`, because the failure
  path performs a load only. `Relaxed`, `Acquire`, or `SeqCst` are valid.
- Use the success ordering that publishes the data the successful writer
  produced. Use the failure ordering that covers the data the loser then reads.
  `Relaxed` on failure is correct when the loser only retries.

## Quick selection guide

```text
Counter or sequence number only (statistics, unique ids):
    -> Relaxed for every operation

Stop or shutdown flag with no dependent data:
    -> Relaxed (a few iterations of delay is acceptable)
    -> Prefer Acquire/Release when promptness or future dependent state matters

One writer, one reader, flag plus dependent data:
    -> Release on the store, Acquire on the load

Read-modify-write that both consumes and publishes state:
    -> AcqRel

Reference count:
    -> Relaxed on increment
    -> AcqRel on decrement (so the thread that sees zero sees all prior writes)
    -> Acquire on an optional final load or fence before the destructor

Lock word in a hand-written mutex or spinlock:
    -> AcqRel on the acquire attempt, Release on the unlock

Global order required across several different atomics:
    -> SeqCst on all of them (benchmark on a weakly ordered target first)
```

## Verification tools

| Tool | Finds | Command |
|------|-------|---------|
| Miri | Data races and undefined behaviour on the executed paths | `cargo +nightly miri test --locked` |
| loom | Illegal interleavings and reorderings of atomics in a model | Run the loom-gated tests; see `rust-test-tools` |
| Device test | Real hardware reordering on a weakly ordered CPU | `cargo test --locked` on the ARM64 host or device |

Miri executes one interleaving per run. Loom enumerates the legal
interleavings and the legal reorderings, so use loom for any lock-free
structure. Neither tool replaces a test on a weakly ordered device.
