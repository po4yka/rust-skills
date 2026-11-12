---
name: rust-sanitizers-miri
description: Use when running Miri or a sanitizer (ASan, ThreadSanitizer or TSan, MSan, HWASan) on Rust code with MIRIFLAGS or -Zsanitizer, choosing between Stacked Borrows and Tree Borrows, reading a Miri or ASan report, stubbing FFI that Miri cannot execute, enabling Android MTE (SEGV_MTESERR, SEGV_MTEAERR) or Xcode sanitizers, running UBSan on a C dependency, or wiring these checks into CI. Not for writing or reviewing unsafe code itself; use rust-unsafe.
license: BSD-3-Clause
---

# Rust Sanitizers and Miri

## 1. Select the tool

Select the tool from the bug class. Each tool finds its own class and misses
the others.

| Bug class | Tool | Does not find it |
|---|---|---|
| Aliasing breach, invalid value, provenance error in Rust | Miri | ASan, HWASan, MTE: they do not model Rust rules |
| Heap overflow, use-after-free, double free at runtime | ASan, HWASan or MTE | Miri, when the path reaches foreign code |
| Data race between threads | TSan, or Miri with `-Zmiri-many-seeds` | ASan |
| Read of uninitialized memory | Miri, or MSan with every object instrumented | ASan |
| Integer overflow or null dereference in a C or C++ dependency | UBSan: clang `-fsanitize=undefined` on that dependency | Miri (does not run C); rustc (has no UBSan option) |
| Memory error inside a C or C++ dependency | ASan, HWASan or MTE | Miri |

Miri knows the Rust rules but cannot execute foreign code. Sanitizers execute
foreign code but do not know the Rust aliasing model. For a crate that has
`unsafe` code and FFI, run both.

Read `references/miri-ub-patterns.md` ("Coverage decision table", "Sanitizer
comparison") when you decide which tool runs on each crate of a workspace, or
when you need overhead figures.

A green run does not prove the absence of undefined behaviour (UB). Every tool
checks only the paths that the tests execute. A clean Miri run says nothing
about a stubbed or skipped path. A clean sanitizer run says nothing about
uninstrumented code or about the Rust aliasing rules.

## 2. Review gates

Apply these gates before you approve a change that adds or edits `unsafe`.

- [ ] A test exercises the new `unsafe` path.
- [ ] `cargo +nightly miri test --locked` passes on that test, or the test has
      `#[cfg_attr(miri, ignore)]` and a comment that gives the reason.
- [ ] The strict-provenance job passes, or the code exposes provenance on
      purpose and runs in the separate job (section 9).
- [ ] Raw-pointer code also passes under `-Zmiri-tree-borrows`.
- [ ] Byte-parsing code passes under `-Zmiri-symbolic-alignment-check`.
- [ ] Each new `#[cfg(miri)]` stub keeps the signature, the return domain and
      any stored pointer of the real function.
- [ ] An ASan, HWASan or MTE run covers every path that Miri skips.
- [ ] New concurrency is covered by TSan, by Miri with `-Zmiri-many-seeds`, or
      by `loom`.

## 3. Failure triage

Miri messages below were measured on nightly 2026-11-09. Match on the quoted
fragment. Tags and allocation ids change with the program, the toolchain, the
seed and the flags.

| Symptom | Probable cause | Next action |
|---|---|---|
| Miri: `unsupported operation: can't call foreign function` | The test reaches code that Miri cannot interpret | Apply section 7 |
| Miri: `not available when isolation is enabled` | The test reads a host resource, for example `SystemTime::now` or a file | Add `-Zmiri-disable-isolation` to that job, or inject the value in the test |
| Miri: `allocN has been freed, so this pointer is dangling` | A pointer kept across a reallocation or a drop | Re-derive the pointer after each operation that can reallocate |
| Miri: `in-bounds pointer arithmetic failed` | `add` or `offset` past the end of the allocation | Check the length before the arithmetic |
| Miri: `constructing invalid value` ... `expected a valid enum tag` or `expected a boolean` | A transmute or read produced a value that no variant or `bool` uses | Decode with `TryFrom` and return an error |
| Miri: `accessing memory based on pointer with alignment` ... `is required`, only on some seeds | A misaligned read through a raw pointer | Use `read_unaligned` or `from_le_bytes`; add `-Zmiri-symbolic-alignment-check` |
| Miri: `memory is uninitialized` or `encountered uninitialized memory` | A read of `MaybeUninit` before every byte was written | Write every byte first, or use a zero-filled buffer |
| Miri: `does not exist in the borrow stack` (SB) or `is forbidden` (TB) | An aliasing violation | Section 6, section 8, and `references/miri-ub-patterns.md` |
| Miri: ``integer-to-pointer casts and `ptr::with_exposed_provenance` are not supported`` | The code rebuilds a pointer from an integer under `-Zmiri-strict-provenance` | Keep the original pointer, or use `with_addr` or `map_addr`. If exposure is required, move the test to the separate job |
| Miri: `dangling pointer (it has no provenance)` | A pointer made from an integer that was never exposed | Keep the original pointer, or use `with_addr` |
| Miri: `memory leaked: allocN` | An allocation that no static can reach: `Box::leak`, `mem::forget`, or a pointer held only by a thread still running at exit or by foreign state | Store an intended process-lifetime value in a static (`OnceLock` or `LazyLock`), which Miri does not report, or add `-Zmiri-ignore-leaks` to that job only |
| Miri passes, ASan fails | The defect is in foreign code that Miri stubbed or skipped | Debug with ASan and read the allocation stack |
| ASan passes, Miri fails | An aliasing or provenance breach that did not corrupt memory on this run | Fix it. It is UB, and the optimizer can act on it later |
| MSan reports uninitialized reads in a C or C++ dependency | That object was built without MSan | Rebuild it with clang `-fsanitize=memory`, or use Miri |
| TSan reports a race inside an atomics-based structure | An ordering is too weak, or the code synchronizes with a `fence` that TSan does not model | Confirm with Miri `-Zmiri-many-seeds` or `loom` before you change an ordering; see the `memory-model` skill |
| ``mixing `-Zsanitizer` will cause an ABI mismatch in crate`` | A crate or std was built without the sanitizer | Add `-Zbuild-std`; for doctests, set `RUSTDOCFLAGS` to the `RUSTFLAGS` value |
| Doctests fail to link with undefined `__asan_*` symbols | `RUSTDOCFLAGS` lacks the `-Zsanitizer` flag | Set `RUSTDOCFLAGS` to the `RUSTFLAGS` value |
| rustc aborts while it expands a proc macro under a sanitizer | `--target` is missing, so the proc macro was instrumented | Pass `--target "$HOST"` |

## 4. Run a sanitizer on the host

`-Zsanitizer` is unstable as of Rust 1.99.1, so every sanitizer run needs
nightly.

```bash
rustup toolchain install nightly --component rust-src
HOST="$(rustc +nightly -vV | sed -n 's/^host: //p')"

# AddressSanitizer (Linux, macOS)
RUSTFLAGS="-Zsanitizer=address" RUSTDOCFLAGS="-Zsanitizer=address" \
    cargo +nightly test --locked -Zbuild-std --target "$HOST"

# ThreadSanitizer (Linux, macOS)
RUSTFLAGS="-Zsanitizer=thread" RUSTDOCFLAGS="-Zsanitizer=thread" \
    cargo +nightly test --locked -Zbuild-std --target "$HOST"

# MemorySanitizer (Linux; every linked object must be instrumented)
RUSTFLAGS="-Zsanitizer=memory -Zsanitizer-memory-track-origins" \
RUSTDOCFLAGS="-Zsanitizer=memory -Zsanitizer-memory-track-origins" \
    cargo +nightly test --locked -Zbuild-std --target "$HOST"
```

Rules (build failures measured on nightly 2026-11-09,
`x86_64-unknown-linux-gnu`; ASan defaults on nightly 2026-05-15,
`aarch64-apple-darwin`):

- Pass `-Zbuild-std`. The prebuilt standard library is not instrumented.
  Without the rebuild, TSan and MSan stop with
  ``mixing `-Zsanitizer` will cause an ABI mismatch in crate``, and ASan builds
  but leaves std unchecked.
- Never silence that error with `-Cunsafe-allow-abi-mismatch=sanitizer`. The
  mixed build misses errors in the uninstrumented crates and can report false
  positives.
- Pass `--target`, also for the host. Then Cargo keeps `RUSTFLAGS` off build
  scripts and proc macros. An instrumented proc macro can abort rustc.
- Set `RUSTDOCFLAGS` to the same `-Zsanitizer` value, or every doctest fails
  to build (section 3).
- On macOS, set `ASAN_OPTIONS=detect_stack_use_after_return=1:detect_leaks=1`.
  Without it, ASan misses `stack-use-after-return` and does not check leaks.
  Linux enables both by default, so an intentional leak fails a Linux ASan
  run. Set `detect_leaks=0` only for that job.
- Build every C and C++ dependency with clang `-fsanitize=memory` for an MSan
  run. Otherwise do not trust an MSan report.
- Expect TSan false positives on `std::sync::atomic::fence` and on
  synchronization in inline assembly. TSan does not model either one.

## 5. Run Miri

```bash
rustup +nightly component add miri
cargo +nightly miri test --locked                  # whole suite
cargo +nightly miri test --locked <test_filter>    # one test
```

Nightly and cache rules:

- Keep secrets out of any Miri job that writes a `target/` cache a pull request
  can read. Miri nightlies before 2026-09-22 wrote every environment variable
  into `target/`. If such a job ran with secrets, clear the cache and rotate
  the secrets ([Rust blog, 2026-09-21](https://blog.rust-lang.org/2026/09/21/github-actions-leaking-secrets-when-miri-output-is-cached/)).
- Pin a nightly date if a Miri regression blocks the pipeline. Pin 2026-09-22 or
  later. Miri diagnostics change with the nightly.

Miri interprets every operation, so it runs much slower than a native test.
Keep the Miri test set small and deterministic. Gate a large-input or
long-running test with `#[cfg_attr(miri, ignore)]`, or shrink its input under
`cfg(miri)`.

Miri also reports data races and leaks at exit. It reports an invalid value
where the code produces it, at the `transmute` or read, not at a later use. It
emulates some weak-memory effects, so an atomic load can return
an outdated value, but that emulation is not complete.

Miri cannot execute a foreign function that has no Miri shim. This includes
every C or C++ entry point behind a `-sys` crate, JNI calls, generated UniFFI
scaffolding, and inline assembly. Miri shims a subset of the platform API,
including files (with `-Zmiri-disable-isolation`), threads, and `epoll` and
`eventfd` on Linux targets. System API support varies between targets. If a shim
is missing, try `--target x86_64-unknown-linux-gnu` before you stub.
`-Zmiri-native-lib` calls real native code, but it is experimental and unsound.
A run through it is not evidence for the FFI path.

Read `references/miri-ub-patterns.md` when a Miri run fails and you need the
shape of the defect and its fix. It shows each UB class with the message Miri
prints.

## 6. Aliasing model policy

```bash
cargo +nightly miri test --locked                                  # Stacked Borrows (default)
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked  # Tree Borrows
```

- Run the default model, Stacked Borrows (SB), first. The SB run is the gate.
- Add a Tree Borrows (TB) run as more evidence on a crate with hand-written
  raw-pointer code. Never make TB the only gate. The Miri README calls TB "even
  more experimental than Stacked Borrows", and code it accepts today "might be
  declared UB in the future".
- Treat a failure under either model as a finding.
- Fix an SB failure even when TB passes. TB accepts some patterns that SB
  rejects, for example a `&mut` reborrow that is written after a read through
  its parent raw pointer.

## 7. Stub an FFI dependency that Miri cannot execute

Run Miri over the Rust logic while the foreign call is replaced or skipped.

- Gate an `extern` block that you declare with `#[cfg(not(miri))]`, and put a
  `#[cfg(miri)]` stub with the same signature next to it. Use the built-in
  `cfg(miri)`, not a Cargo feature.
- Keep the return domain: a stub that returns a pointer returns a pointer into
  a real allocation. A stub stores each pointer that the foreign side stores,
  and dereferences it on a later call.
- Do not stub a third-party C crate or generated bindings. Exclude the crate
  (`--exclude`) or gate the tests that reach it. Gate a test that needs a live
  host runtime with `#[cfg_attr(miri, ignore)]` and a comment with the reason.
- Every path that a stub, a skip or an exclusion removes from Miri needs an ASan
  run on the host, or a HWASan or MTE run on a device. `cargo +nightly careful
  test` without `-Zcareful-sanitizer` is not a substitute.

Read `references/ffi-stubs.md` when you pick the strategy for a dependency or
write a stub. It has the strategy table, the stub example, and the commands.

## 8. A `Box` and a pointer that foreign code keeps

A `Box<T>` asserts unique access while it is live. If foreign code stores a
`*mut T` taken from the `Box`, and Rust then writes through the `Box`, a later
foreign access through the stored pointer is UB. Transfer ownership with
`Box::into_raw`, and recover it with `Box::from_raw` exactly once, after the
foreign side unregisters it and no callback can still run.

Miri sees this only when the `#[cfg(miri)]` stubs keep the pointer and read
through it on a later call. Read `references/ffi-stubs.md` ("Ownership
patterns for a `Box`") for the synchronous-borrow and `Pin` rules, and
`references/miri-ub-patterns.md` ("`Box` plus FFI aliasing") for the full stubs
and test.

## 9. Miri jobs and flag hazards

```bash
# Gate: default model and strict provenance.
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test --locked

# Byte parsers and raw-pointer crates: symbolic alignment, then Tree Borrows.
MIRIFLAGS="-Zmiri-strict-provenance -Zmiri-symbolic-alignment-check" \
    cargo +nightly miri test --locked -p my-parser
MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-strict-provenance" \
    cargo +nightly miri test --locked -p my-parser

# Concurrency: many schedules for the threaded tests.
MIRIFLAGS="-Zmiri-many-seeds=0..16" cargo +nightly miri test --locked <test_filter>

# Endianness: interpret on a big-endian target.
cargo +nightly miri test --locked -p my-parser --target s390x-unknown-linux-gnu
```

Flag hazards:

- A misaligned read passes default Miri on some seeds and fails on others. Add
  `-Zmiri-symbolic-alignment-check` to make the failure certain. It gives false
  positives when code aligns a pointer with manual integer arithmetic;
  `align_to` is fine in both modes.
- `-Zmiri-strict-provenance` rejects every deliberate exposure, including
  `with_exposed_provenance`. Run exposing code in a separate job without the
  flag. No `cfg` reports the flag, so `cfg_attr(miri, ignore)` cannot select
  these tests. Keep them out of the gate with `-- --skip <name>` or by crate
  (`--exclude`). `-Zmiri-permissive-provenance` only silences the warning.
  Miri can miss bugs on exposed pointers either way.
- Miri reports 1 CPU by default, so `cargo miri test` runs one test at a
  time and does not detect a race between two tests on a shared resource
  (measured on nightly 2026-11-09). Add `-Zmiri-num-cpus=4` or
  `-- --test-threads=4` for that job. `RUST_TEST_THREADS` does not reach the
  program under isolation. `cargo miri nextest run` runs each test in its own
  process and never detects such a race.

Read `references/miri-flags-and-ci.md` when you need another flag, for
example `-Zmiri-seed=N` to reproduce one failing seed. It has the full
MIRIFLAGS table.

## 10. Read an ASan report

Read `references/miri-ub-patterns.md` ("ASan error names") when you map an
ASan error name to its usual Rust cause.

Triage order:

1. Read frame `#0`. It names the access, not always the defect.
2. Read the allocation and free stacks that ASan prints below the access.
3. Find the `unsafe` block on the path between them. That block owns the bug.
4. If the path is pure Rust, write a Miri test for it. Miri names aliasing and
   provenance defects more exactly than ASan.

## 11. On-device sanitizers: Android and iOS

On Android arm64, use HWASan or MTE. Xcode instruments only the code that
Xcode compiles. A prebuilt Rust static library gets no ASan or TSan
instrumentation from the scheme setting. Run a host sanitizer build for the
Rust code itself.

Read `references/platform-sanitizers.md` when you build for a device. It has the
platform requirements, the HWASan build and `wrap.sh`, the MTE manifest modes
and stack-MTE rebuild, the tombstone check, and the Xcode commands.

## 12. CI integration

Read `references/miri-flags-and-ci.md` when you write the CI jobs. It has a
GitHub Actions example and the job layout rules.

Treat a Miri failure as a build failure. Miri reports UB, not style.

## Related skills

- `rust-unsafe`: unsafe patterns and the review checklist for `unsafe`
- `memory-model`: atomic orderings; an ordering change also needs a `--cfg loom` test
- `rust-debugging`: symbolication and `addr2line` for sanitizer and tombstone frames
- `rust-test-tools`: property tests and fuzzing that feed these tools
