---
name: rust-sanitizers-miri
description: Use when you run AddressSanitizer, ThreadSanitizer or MemorySanitizer on Rust code, when you run UBSan on a C or C++ dependency of a Rust crate, when you configure Miri to find undefined behaviour in unsafe Rust (Stacked Borrows or Tree Borrows), when you stub an FFI dependency that Miri cannot execute, when you enable HWASan on Android or MTE on Android 14+, when you enable ASan or TSan on iOS through Xcode, when you read a tombstone tagged SEGV_MTEAERR or SEGV_MTESERR, or when you wire any of these tools into CI. Triggers on "sanitizer", "miri", "ASan", "TSan", "MSan", "HWASan", "MTE", "undefined behavior", "stacked borrows", "tree borrows", or memory-safety validation questions.
license: BSD-3-Clause
---

# Rust Sanitizers and Miri

Runtime and interpreter-based safety validation for Rust: ASan, TSan and MSan
through `RUSTFLAGS`; UBSan through the C compiler on a C or C++ dependency;
Miri for undefined behaviour (UB) in unsafe code; HWASan and MTE for on-device
Android validation; ASan and TSan for iOS; and the rules to read the reports
that these tools produce.

## 1. Select the tool

Select the tool from the bug class, not from habit. Each tool finds a different
class and misses the others.

| Bug class | Tool to use | Do not use |
|---|---|---|
| Aliasing rule breach, invalid value, provenance error | Miri | ASan (does not model Rust rules) |
| Heap overflow, use-after-free, double free at runtime | ASan, HWASan or MTE | Miri, if the path reaches FFI |
| Data race between threads | TSan, or Miri with `-Zmiri-seed` | ASan |
| Read of uninitialized memory | MSan or Miri | ASan |
| Integer overflow or null deref in a C or C++ dependency | UBSan, built with clang `-fsanitize=undefined` | Miri (does not execute C or C++), `RUSTFLAGS` (rustc has no UBSan option) |
| UB inside a C or C++ dependency | ASan, HWASan or MTE | Miri (cannot interpret C or C++) |
| Type or lifetime error | `cargo check --locked`, Clippy | any sanitizer |

Full overhead and requirement comparison: `references/miri-ub-patterns.md`.

Two rules follow from the table:

- Miri sees Rust semantics but cannot execute foreign code.
- Sanitizers execute foreign code but do not know the Rust aliasing model.

Run both. Neither one replaces the other.

## 2. Sanitizers in Rust

Rust sanitizers need the nightly toolchain and a supported target.

```bash
# Install nightly and the standard-library source.
rustup toolchain install nightly
rustup component add rust-src --toolchain nightly

# AddressSanitizer (Linux, macOS)
RUSTFLAGS="-Z sanitizer=address" \
    cargo +nightly test --locked -Zbuild-std \
    --target x86_64-unknown-linux-gnu

# ThreadSanitizer (Linux)
RUSTFLAGS="-Z sanitizer=thread" \
    cargo +nightly test --locked -Zbuild-std \
    --target x86_64-unknown-linux-gnu

# MemorySanitizer (Linux; needs a fully instrumented build)
RUSTFLAGS="-Z sanitizer=memory -Zsanitizer-memory-track-origins" \
    cargo +nightly test --locked -Zbuild-std \
    --target x86_64-unknown-linux-gnu
```

Rules:

- Always pass `-Zbuild-std`. It rebuilds the standard library with the
  sanitizer. Without it the results are incomplete and misleading.
- Always name an explicit `--target`. `-Zbuild-std` needs one.
- MSan reports false positives if any linked object is not instrumented. Build
  every dependency, including C and C++ dependencies, with MSan, or do not
  trust an MSan report.
- Run sanitizers on the host target in CI, even for a crate that you ship to a
  device. The host run is faster and catches the same parser and decoder bugs
  in your dependencies.

## 3. Read the ASan report

```text
==12345==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000050
READ of size 4 at 0x602000000050 thread T0
    #0 0x401234 in my_crate::parser::parse_record src/parser.rs:87
    #1 0x401567 in my_crate::reader::read_next src/reader.rs:42
```

Map the ASan error class back to the Rust construct that produced it.

| ASan error | Likely Rust cause |
|---|---|
| `heap-buffer-overflow` | `unsafe` slice or pointer access past the end of a buffer |
| `use-after-free` | Raw pointer used after a `Vec` reallocation moved the buffer |
| `stack-use-after-return` | Reference to a local returned out of the function |
| `heap-use-after-free` | Use after `drop()`, or a second `Box::from_raw` on one pointer |
| `double-free` | Ownership transferred to FFI and also dropped on the Rust side |
| `alloc-dealloc-mismatch` | Allocated by one allocator, freed by another across the FFI boundary |

Triage order:

1. Read frame `#0`. It names the access, not always the defect.
2. Read the allocation and free stacks that ASan prints below the access.
3. Find the `unsafe` block on the path between them. That block owns the bug.
4. Write a Miri test for the same path if the path is pure Rust. Miri gives a
   more exact diagnosis than ASan for aliasing and provenance defects.

## 4. On-device sanitizers: Android and iOS

Use HWASan or MTE on Android, and ASan or TSan on iOS, to validate a Rust
library that you cross-compile into a mobile app.

| Platform | Tool | Requirement |
|---|---|---|
| Android ARM64 | HWASan | Android 10 and later; `-Z sanitizer=hwaddress` |
| Android ARM64 | MTE | Android 14 and later, supporting SoC; manifest setting only |
| Android ARM or x86 emulator | ASan | `-Z sanitizer=address` |
| iOS device or Simulator | ASan, TSan | Xcode scheme Diagnostics, or `-enableAddressSanitizer` |

MTE needs no Rust code change and no rebuild. It is a manifest setting. A tag
mismatch raises `SIGSEGV` with `si_code = SEGV_MTEAERR` in async mode or
`SEGV_MTESERR` in sync mode.

Full build commands, the cost table, manifest activation, tombstone analysis
and the rollout order: `references/platform-sanitizers.md`.

## 5. Miri: the UB interpreter

Miri interprets Rust MIR and checks every operation against the Rust
memory model. It finds defects that no runtime sanitizer can find, because it
knows the language rules and not only the machine behaviour.

```bash
# Install Miri. Miri needs nightly.
rustup +nightly component add miri

# Run the whole test suite under Miri.
cargo +nightly miri test --locked

# Run one test.
cargo +nightly miri test --locked test_name

# Strict provenance. Recommended for CI.
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test --locked

# Allow file I/O, the clock and randomness.
MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri test --locked
```

Miri runs about 100 times slower than a native build. Keep the Miri test set
small and deterministic. Do not run integration tests that read large files
under Miri.

> **FFI limitation.** Miri cannot execute `extern "C"` or `extern "system"`
> functions that have no Miri shim, foreign code inside a `-sys` crate,
> JNI calls, UniFFI ABI calls, libc syscalls, or inline assembly. Section 6
> gives the strategy for each case.

### What Miri detects

- **Dangling pointers.** Use after free, and use after a reallocation moved the
  buffer.
- **Invalid values.** An enum discriminant that no variant uses, a `bool` that
  is not 0 or 1, a reference to unaligned data, a null reference.
- **Uninitialized memory.** A read of `MaybeUninit` before initialization, and a
  read of a partly initialized buffer.
- **Aliasing violations.** A breach of Stacked Borrows or Tree Borrows rules.
- **Data races.** Miri has its own concurrency model. It interleaves threads at
  yield points and reports an unsynchronized access to shared state. This model
  is independent of the aliasing model.
- **Memory leaks.** Miri reports a leak at the end of the run unless you pass
  `-Zmiri-ignore-leaks`.

Worked examples of each class, with the exact Miri message and the correct
pattern, are in `references/miri-ub-patterns.md`.

## 6. Stub an FFI dependency that Miri cannot execute

The goal is to run Miri over your Rust logic while the foreign call is replaced
or skipped. Select the strategy from the shape of the dependency.

| FFI situation | Strategy |
|---|---|
| `extern "C"` block that you declare in your own crate | Gate the block with `#[cfg(not(miri))]`. Add a `#[cfg(miri)]` stub with the same signature. |
| Inline `asm!` or `global_asm!` | Add a pure-Rust fallback behind `#[cfg(miri)]`. Keep both paths under one test. |
| Third-party crate that links C or C++ | You cannot stub it. Exclude the crate from the Miri invocation, or gate the tests that reach it. |
| Generated FFI scaffolding, for example a UniFFI or JNI binding layer | Do not stub the generated code. Gate the tests that cross the boundary. |
| Test that needs a live host runtime, for example a JVM, a GPU driver or a database | Gate the test with `#[cfg_attr(miri, ignore)]`. Do not stub. |
| Platform syscall through `libc` with a simple return value | Stub it behind `#[cfg(miri)]` and return the success value. |

### Stub a foreign function that you declare

```rust
#[cfg(not(miri))]
unsafe extern "C" {
    fn platform_specific_call(fd: i32) -> i32;
}

#[cfg(miri)]
unsafe fn platform_specific_call(_fd: i32) -> i32 {
    0 // Deterministic success value for the interpreter.
}
```

The stub must keep the same signature, the same safety contract and the same
return domain as the real function. If the real function returns a pointer that
the caller dereferences, the stub must return a pointer into a real allocation.
A stub that returns a null pointer moves the defect instead of removing it.

### Skip the test instead of stubbing

```rust
// Pure Rust logic. This runs under Miri.
#[test]
fn parses_record_header() {
    // No foreign call on this path.
}

// This path reaches foreign code. Miri cannot interpret it.
#[test]
#[cfg_attr(miri, ignore)]
fn round_trips_through_ffi_boundary() {
    // Skipped under Miri; covered by ASan and by the normal test run.
}
```

### Exclude a whole crate

Select the FFI-free crates explicitly, or exclude the FFI crates from the
workspace run:

```bash
# Select the crates that Miri can interpret.
cargo +nightly miri test --locked -p my-core -p my-parser -p my-model

# Or run the workspace and exclude the crates that reach foreign code.
cargo +nightly miri test --locked --workspace \
    --exclude my-ffi --exclude my-render-backend
```

### Stubbing rules

- Never let a stub hide the UB that you want to find. A stub that always
  returns `0` on a function whose error path frees a buffer removes the very
  test you need.
- Keep the stub next to the real declaration, in the same module. A stub in a
  distant file drifts out of sync with the signature.
- Cover the FFI path with a sanitizer run. The stub removes Miri coverage, so
  ASan or HWASan must cover that path instead.
- Do not add a `miri` feature flag. Use the built-in `cfg(miri)`. Miri sets it
  automatically, and a feature flag can be enabled by accident in a normal
  build.

## 7. Stacked Borrows and Tree Borrows

Miri checks aliasing with one of two models. Stacked Borrows is the default.
Tree Borrows is the alternative.

```bash
# Default: Stacked Borrows.
cargo +nightly miri test --locked

# Tree Borrows.
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked
```

| Model | Shape | Use it for |
|---|---|---|
| Stacked Borrows | Each allocation carries a stack of borrow tags. A use pops every tag above it. | The default check. Run it first. |
| Tree Borrows (PLDI 2025) | Reborrows form a tree instead of a stack. | Raw pointer code that interacts with `Box` or with FFI, where the stack model is too coarse. |

Run both models on any crate that contains hand-written raw pointer code. A
violation that one model reports may not appear under the other. A run that is
clean under only one model is not evidence.

## 8. Aliasing assumptions travel through `Box`

Severity: warning, whenever you mix `Box<T>` with raw-pointer FFI.

`Box<T>` carries `Unique<T>` semantics. The compiler assumes that the `Box`
exclusively owns the data and that no other pointer aliases it. This becomes
the LLVM `noalias` attribute. If you take a `*mut T` out of a `Box`, hand it to
foreign code, and the foreign code stores that pointer while the `Box` is still
live, both the `Box` and the raw pointer claim unique access.

Failure mode:

```rust
let mut boxed = Box::new(MyStruct::new());
let raw: *mut MyStruct = &mut *boxed as *mut _;
unsafe { ffi_register(raw); } // Foreign code stores `raw`.
boxed.field = 42;             // Load through the Box. LLVM may reorder it
                              // past the store made through `raw`.
// `raw` and `boxed` now alias. Tree Borrows reports this.
```

Correct patterns:

- Use `Box::into_raw` to transfer ownership to the foreign side. Never use the
  original `Box` again. Recover it with `Box::from_raw` exactly once.
- If the foreign side must only borrow the pointer, hold the value in
  `Pin<Box<T>>`. The address is then stable and the code does not rely on the
  `noalias` assumption being false.
- Run `MIRIFLAGS="-Zmiri-tree-borrows"` on this code. The tree model reports
  this aliasing violation.

See the pointer provenance and Stacked Borrows sections of
`references/miri-ub-patterns.md` for the exact Miri messages.

## 9. MIRIFLAGS reference

| Flag | Effect |
|---|---|
| `-Zmiri-disable-isolation` | Allow I/O, the clock and randomness |
| `-Zmiri-strict-provenance` | Reject integer-to-pointer casts that have no provenance |
| `-Zmiri-symbolic-alignment-check` | Check alignment symbolically, not only on the concrete address |
| `-Zmiri-num-cpus=N` | Report N CPUs to the program |
| `-Zmiri-seed=N` | Seed the randomized thread scheduler |
| `-Zmiri-ignore-leaks` | Do not report memory that is still allocated at exit |
| `-Zmiri-tree-borrows` | Use Tree Borrows instead of Stacked Borrows |

Recommended combinations:

```bash
# Development: permissive, fast to get running.
MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri test --locked

# CI: strict.
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test --locked

# Concurrency: randomized schedule. Change the seed on each run.
MIRIFLAGS="-Zmiri-disable-isolation -Zmiri-seed=42 -Zmiri-num-cpus=4" \
    cargo +nightly miri test --locked

# Code with intentional leaks, for example a process-lifetime global.
MIRIFLAGS="-Zmiri-ignore-leaks -Zmiri-disable-isolation" \
    cargo +nightly miri test --locked
```

## 10. CI integration

```yaml
- name: Miri
  run: |
    rustup toolchain install nightly
    rustup +nightly component add miri
    # Select only the crates that contain no foreign code.
    cargo +nightly miri test --locked \
      -p my-core -p my-parser -p my-model
  env:
    MIRIFLAGS: "-Zmiri-disable-isolation -Zmiri-strict-provenance"

- name: Miri (Tree Borrows)
  run: cargo +nightly miri test --locked -p my-core
  env:
    MIRIFLAGS: "-Zmiri-disable-isolation -Zmiri-tree-borrows"

- name: ASan
  run: |
    rustup toolchain install nightly
    rustup component add rust-src --toolchain nightly
    RUSTFLAGS="-Z sanitizer=address" \
    cargo +nightly test --locked -Zbuild-std \
    --target x86_64-unknown-linux-gnu

- name: TSan
  run: |
    RUSTFLAGS="-Z sanitizer=thread" \
    cargo +nightly test --locked -Zbuild-std \
    --target x86_64-unknown-linux-gnu
```

CI rules:

- Pin the nightly date if a Miri regression blocks the pipeline. Miri tracks
  nightly and its diagnostics change.
- Run the Miri job and the sanitizer jobs in parallel. They share no artifacts.
- Keep the sanitizer jobs on the host target. Cross-compiled sanitizer runs
  need a device or an emulator and belong in a nightly or on-demand job.
- Treat a Miri failure as a build failure. Miri reports real UB, not style.

## 11. Review gates

Apply these gates before you approve a change that adds or edits `unsafe`.

- [ ] The change has a test that exercises the new `unsafe` path.
- [ ] `cargo +nightly miri test --locked` passes on that test, or the test is
      gated with `#[cfg_attr(miri, ignore)]` and the reason is written in a
      comment.
- [ ] `MIRIFLAGS="-Zmiri-strict-provenance"` passes. A provenance failure means
      a pointer was made from an integer.
- [ ] Raw-pointer code that touches `Box` or FFI also passes under
      `-Zmiri-tree-borrows`.
- [ ] Any new `#[cfg(miri)]` stub has the same signature and the same return
      domain as the real function.
- [ ] Any path that Miri skips is covered by an ASan or HWASan run.
- [ ] New concurrency is covered by TSan, or by Miri with `-Zmiri-seed` and
      `-Zmiri-num-cpus`, or by `loom`.

## 12. Failure triage

| Symptom | Probable cause | Next action |
|---|---|---|
| Miri: "unsupported operation: can't call foreign function" | The test reaches code that Miri cannot interpret | Apply section 6 |
| Miri: "pointer must be in-bounds at offset ..." | The pointer was derived before a reallocation | Re-derive the pointer after every operation that can reallocate |
| Miri: "enum value has invalid tag", or a validation error on a `bool` | A transmute produced an enum discriminant or a `bool` that no valid value uses | Use `TryFrom` and validate the value |
| Miri rejects an integer-to-pointer cast under `-Zmiri-strict-provenance`, or reports "no exposed tags" without it | The code rebuilt a pointer from an integer address | Keep the original pointer, or expose the provenance deliberately with `ptr::with_exposed_provenance` |
| Miri reports a leak on a global | The value lives for the process lifetime by design | Add `-Zmiri-ignore-leaks` to that job only |
| Miri passes, ASan fails | The defect is in foreign code that Miri stubbed or skipped | Debug with ASan and read the allocation stack |
| ASan passes, Miri fails | The defect is an aliasing or provenance rule breach that did not corrupt memory on this run | Fix it. It is real UB and the optimizer may act on it later. |
| MSan reports uninitialized reads in a dependency | Not every object was built with MSan | Rebuild every dependency with MSan, or use Miri instead |
| TSan reports a race inside an atomics-based structure | A memory ordering is too weak, or the structure is unsound | See the `memory-model` skill |
| Sanitizer build fails to link | `-Zbuild-std` or `--target` is missing | Add both |

## Related skills

- `rust-unsafe` — unsafe Rust patterns and the review checklist for `unsafe`
- `rust-debugging` — GDB and LLDB debugging, symbol resolution, `addr2line`
- `memory-model` — atomics, memory ordering, lock-free data structures
- `rust-test-tools` — test harnesses, property tests and fuzzing
- `rust-security` — supply chain safety and memory-safe development
- `cargo-workflows` — toolchain pinning, workspace and profile configuration
- `rust-jni` — JNI boundary design; JNI calls cannot run under Miri
- `uniffi-boundary` — UniFFI boundary design; the generated scaffolding cannot
  run under Miri
- `rust-android-build` — Android target setup for the cross-compiled builds in
  section 4
