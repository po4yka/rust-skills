---
name: rust-test-tools
description: Use when you write or review tests for unsafe code, hand-rolled atomics, lock-free primitives, untrusted parsers, FFI boundaries, deterministic export pipelines, or a generated module that needs more than basic coverage. Covers dynamic checks beyond cargo test with cargo-nextest, cargo-careful, loom, proptest, cargo-fuzz, cargo-mutants with survived-mutant triage, and golden tests for deterministic output.
license: BSD-3-Clause
---

# Rust Test Tools

## Purpose

`cargo test --locked` and `cargo nextest run --locked` are necessary but not sufficient.
They do not find these failure modes:

- Undefined behavior (UB) in `unsafe` code.
- Data races in lock-free atomics.
- Missing edge cases in parsers and decoders.
- Behavior changes that pass weak tests but break under exhaustive exploration.
- Non-deterministic output from a pipeline that promises determinism.

This skill lists the dynamic toolkit beyond Miri. It tells you when to reach for each tool.

## Tool selection decision tree

```text
Is there `unsafe` in the change?
├── FFI / UniFFI / JNI / inline asm / syscalls / libc?
│   └── YES → cargo-careful + sanitizers (ASan/TSan/MSan).
│             Miri cannot model FFI. See `rust-sanitizers-miri` for ASan/TSan invocations.
└── Pure-Rust unsafe (raw pointers, transmute, mem::* tricks)?
    └── YES → Miri (primary) + cargo-careful (cheaper continuous check).
              Use `MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-strict-provenance"`.

Is the change a custom synchronization primitive
(atomic-based flag, hand-rolled spinlock, lock-free queue, publish/subscribe pair)?
├── YES → loom with a `cfg(loom)` test.
│         Standard `Mutex` / `RwLock` does NOT need loom.
│         Data-parallel code (for example rayon) with no hand-rolled atomics does not
│         need loom either. Reach for loom only when a raw atomic crosses threads.

Is the change a parser, a decoder, or any function that reads untrusted bytes?
├── YES → proptest (input-space coverage) + cargo-fuzz (corpus-driven OOM/panic/UB hunting).

Is the change a refactor or a rewrite of well-tested logic?
├── YES → cargo-mutants on the changed file or crate. A mutation score below 80% means
│         the tests do not constrain behavior. Add tests before you merge.

Does the change affect deterministic output (rendered images, serialized documents,
generated code, report files)?
├── YES → golden tests against committed baselines. Diff at byte level where the
│         producer is deterministic.

None of the above?
└── `cargo nextest run --locked` plus standard tests are sufficient.
```

## cargo-nextest — the baseline runner

Use nextest as the default test runner. It runs each test in its own process, so a
panic or an abort in one test does not hide the rest of the suite.

```bash
cargo nextest run --locked
cargo nextest run --locked --no-fail-fast      # see every failure, not only the first
cargo nextest run --locked -p <crate>          # one crate
```

Nextest profiles (for example `default` and `ci`) live in `.config/nextest.toml`.
See the `cargo-workflows` skill for profile setup. Keep `--locked` in every command so
that a run cannot silently update `Cargo.lock`.

Nextest is also the test tool for cargo-mutants (`--test-tool nextest`).

## cargo-careful — the Miri fallback

Miri is the gold standard for UB detection in pure Rust. But Miri runs 50–400× slower
than normal tests, and Miri refuses FFI. `cargo-careful` rebuilds `std` with extra debug
assertions (alignment checks, initialization tracking, and more) and runs your tests
against that hardened `std`. The slowdown is about 2–3× versus normal tests. It finds a
large subset of what Miri finds.

```bash
# Install once.
cargo install cargo-careful

# Run for crates that mix unsafe with FFI, where Miri is unavailable.
cargo +nightly careful test -p <ffi-crate> --no-fail-fast

# Or the whole workspace.
cargo +nightly careful test --workspace --no-fail-fast
```

Use cargo-careful when:

- The crate crosses an FFI, UniFFI, JNI, or libc boundary and Miri's
  `-Zmiri-disable-isolation` is not enough.
- You want UB coverage on every pull request without the 50–400× cost of Miri.
- A test reproduces a device-only or platform-only crash and you want a host-runnable
  diagnosis path.

## loom — the concurrency model checker

`loom` explores thread interleavings exhaustively for code under `#[cfg(loom)]`. It is a
model checker, not a stress test. It proves the absence of races inside the bounded
interleaving set. A stress test only fails to find one race in a finite run.

Apply loom to:

- Any new lock-free data structure or hand-rolled spinlock.
- Atomic-based publish/subscribe flags, for example a cancellation flag that one thread
  sets and another thread polls.
- Any `Ordering::Relaxed` on a publish/subscribe pair. Each such site is a loom-test
  candidate. See the `memory-model` skill.

Declare `loom` as a dependency that only exists under the `loom` cfg. A normal
dependency entry pulls loom into every release build:

```toml
# Cargo.toml
[target.'cfg(loom)'.dependencies]
loom = "0.7"
```

Gate the primitive so that the same code compiles against `loom` types and `std` types:

```rust
// src/lib.rs — gate the real and the loom implementation of the primitive.
#[cfg(loom)]
use loom::sync::atomic::{AtomicBool, Ordering};
#[cfg(not(loom))]
use std::sync::atomic::{AtomicBool, Ordering};
```

```rust
// tests/loom_shutdown.rs
#[cfg(loom)]
#[test]
fn shutdown_flag_publishes_to_reader() {
    loom::model(|| {
        let flag = loom::sync::Arc::new(AtomicBool::new(false));
        let f2 = flag.clone();
        let writer = loom::thread::spawn(move || {
            f2.store(true, Ordering::Release);
        });
        let reader = loom::thread::spawn(move || {
            while !flag.load(Ordering::Acquire) {
                loom::thread::yield_now();
            }
        });
        writer.join().unwrap();
        reader.join().unwrap();
    });
}
```

Run:

```bash
RUSTFLAGS="--cfg loom" cargo test --locked --release --test loom_shutdown

# Bound the search space if loom takes too long.
LOOM_MAX_PREEMPTIONS=3 RUSTFLAGS="--cfg loom" cargo test --locked --release --test loom_shutdown
```

Cost is exponential in the number of atomic operations and in the preemption bound. Keep
each loom test small. Test one primitive per test.

## proptest — input-space property testing

Write a `proptest` strategy for any function that takes bytes or a configuration value
and produces a parsed or validated output. Assert invariants, not single examples.
Proptest finds edge cases that example tests miss: zero-length input, all-zero and
all-`0xFF` input, near-overflow lengths, malformed framing, and corrupt field encoding.

```rust
use proptest::prelude::*;

proptest! {
    // Total function: never panics, never triggers UB, for any byte string.
    #[test]
    fn parse_never_panics(buf in prop::collection::vec(any::<u8>(), 0..1024)) {
        let _ = Header::parse(&buf);
    }

    // Roundtrip: parse then serialize must reproduce the consumed prefix.
    #[test]
    fn parse_then_serialize_roundtrips(buf in prop::collection::vec(any::<u8>(), 0..4096)) {
        match Header::parse(&buf) {
            Ok(hdr) => {
                let mut out = Vec::new();
                hdr.write_to(&mut out);
                prop_assert_eq!(&out, &buf[..hdr.len()]);
            }
            // Parse errors are acceptable. A panic or UB is not.
            Err(_) => {}
        }
    }

    // Structured roundtrip: generate a valid value, encode it, decode it back.
    #[test]
    fn decode_roundtrips_valid_input(value in arb_valid_message()) {
        let encoded = value.encode();
        let decoded = decode(&encoded).expect("valid input must decode");
        prop_assert_eq!(decoded.fields.len(), value.fields.len());
    }

    // Truncation tolerance for a reader over `Read + Seek`.
    #[test]
    fn reader_tolerates_truncation(buf in prop::collection::vec(any::<u8>(), 0..8192)) {
        let _ = read_header_and_metadata(std::io::Cursor::new(&buf[..]));
    }

    // Text input: arbitrary Unicode must not panic the parser.
    #[test]
    fn text_parser_never_panics(s in ".*") {
        let _ = parse_document(&s);
    }
}
```

Treat any AI-generated parser without a proptest as incomplete.

## cargo-fuzz — corpus-driven fuzzing

`proptest` finds bugs that a strategy can reach. Fuzzing finds bugs that a corpus plus
coverage feedback can reach. Fuzzing reaches bugs proptest misses, above all in binary
protocol and container decoders.

```bash
# Install once. cargo-fuzz needs a nightly toolchain to build a target.
cargo install cargo-fuzz

# One-time setup per crate. Run inside the crate directory.
cargo fuzz init
cargo fuzz add parse_header
```

```rust
// fuzz/fuzz_targets/parse_header.rs
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = my_crate::wire::parse_header(data);
});
```

```bash
# Run for a fixed wall-clock budget.
cargo +nightly fuzz run parse_header -- -max_total_time=600

# List every target in the crate.
cargo fuzz list

# Reproduce a crash from a saved artifact.
cargo +nightly fuzz run parse_header fuzz/artifacts/parse_header/crash-<id>

# Shrink a crashing artifact before you turn it into a regression test.
cargo +nightly fuzz tmin parse_header fuzz/artifacts/parse_header/crash-<id>
```

Pick fuzz targets by input shape:

| Input shape | Target the entry point | Why |
|-------------|------------------------|-----|
| Binary wire format or protocol header | `parse_header`, `decode_frame` | Adversarial bytes arrive from an untrusted peer |
| Container or archive format | header reader, index reader, `open` | The file comes from the user or from a download |
| Compressed or length-prefixed payload | the decompress or unframe step | Length fields drive allocation; OOM risk is real |
| Text markup or document format | the top-level parse function | Deeply nested or malformed markup causes stack and recursion bugs |
| Configuration or project JSON | `parse_validated`, `validate_json` | The document can come from an untrusted source |

Run fuzzing nightly or weekly in CI, not on every pull request. Reduce every crash to a
minimized regression test. Commit it under `tests/regressions/` so that the bug cannot
return.

## cargo-mutants — mutation testing

`cargo-mutants` changes your source code (it replaces a function body with
`Default::default()`, it flips a comparison, it deletes a call) and reruns the tests for
each change. If the tests still pass, the mutant "survived". A survived mutant means the
tests execute the code but never check its correctness.

Coverage tells you which lines run. Mutation testing tells you which behavior the tests
actually constrain. A function with 100% coverage can have zero assertions.

A mutation score below 80% is a strong signal that the test suite rubber-stamps the code.

```bash
cargo install cargo-mutants

# Full workspace run with nextest as the test tool.
cargo mutants --test-tool nextest --output target/

# Only the lines that a diff changes. This is the fastest useful loop:
# a focused pull request gives 10–50 mutants instead of thousands.
git diff origin/main...HEAD > /tmp/pr.diff
cargo mutants --test-tool nextest --in-diff /tmp/pr.diff --output target/

# One crate, with two parallel jobs.
cargo mutants --package <crate> -j2 --output target/
```

`--in-diff` takes a path to a diff file, not a shell command. The diff must use the
`git diff` filename format (a `b/` prefix on the new name) or no prefix.

Keep `-j` low. Start at `-j2` or `-j3`. `cargo build` and `cargo test` already use
many cores, so a high job count makes the machine thrash.

If the Rust workspace is not at the repository root, add `--dir <workspace-dir>` or
`--manifest-path <workspace-dir>/Cargo.toml` to each command.

cargo-mutants writes a `mutants.out/` directory inside the `--output` directory. The
default output location is the source tree root. `mutants.out/missed.txt` lists the
mutations that no test caught. That file is the actionable one.

### Triage workflow for survived mutants

1. Open `mutants.out/missed.txt`.
2. For each survived mutant, read the named function and the mutation description.
3. Ask: "Must a test catch this?" If yes, write a targeted test.
4. If the mutation is in genuinely untestable code (FFI glue, logging, `Display`
   formatting), exclude it. Use `exclude_re` in `.cargo/mutants.toml` for a class of
   items, or `#[mutants::skip]` on one item. Do not write a meaningless test to raise
   the score.

Run cargo-mutants after a refactor, or after an AI-generated rewrite of a well-tested
module. Do not block the normal CI path on the mutation score. A full run takes minutes
to hours, and it produces false-positive mutants from equivalent transformations.

For the full flag list, the `.cargo/mutants.toml` configuration, the exit codes, the
output-file taxonomy, the patterns that make tests mutation-resistant, the known false
positives, and the CI workflow, see
[references/mutation-testing.md](references/mutation-testing.md).

## Golden tests — deterministic output verification

If a pipeline promises deterministic output (the same inputs always give the same
rendered image, the same serialized document, or the same generated file), verify that
promise with golden tests. Commit baseline artifacts. Diff each new run against them.

Drive the golden run from one script so that CI and a developer machine execute the
same steps. Give the script two modes, for example:

```bash
# Verify against the committed baselines. This must fail on any diff.
bash tools/golden/run.sh

# Regenerate the baselines after an intentional output change.
bash tools/golden/run.sh --update
```

Golden test policy:

- Every new input fixture must have a matching committed baseline.
- A baseline update needs a deliberate commit with a visual or textual diff in the
  review. Never update baselines automatically.
- Text and vector output: compare byte-exact, because the producer is deterministic.
- Raster output: compare pixel-exact, or use a perceptual-hash tolerance of 1% or less.
- Binary document output (for example PDF): compare byte-exact after you strip
  metadata timestamps.

## Cost and cadence summary

| Tool | Cost vs `cargo test --locked` | Cadence | Catches |
|------|------------------------------|---------|---------|
| `cargo nextest run --locked` | baseline | every pull request | functional regressions |
| `cargo-careful` | 2–3× | every pull request if FFI is present | uninit reads, misalignment, std debug-assert violations |
| Miri | 50–400× | nightly, and on every `unsafe` pull request | UB, aliasing, provenance (pure Rust only) |
| loom | exponential, bounded by preemptions | every pull request that touches custom atomics | data races, atomic reorderings |
| proptest | minutes | every pull request that touches parsers | edge-case parse failures, roundtrip violations |
| cargo-fuzz | hours to days | nightly or weekly | OOMs, panics, slow inputs, UB on adversarial bytes |
| cargo-mutants | minutes to hours | manual, after a refactor; weekly in CI | weak assertions, untested branches |
| golden tests | seconds to minutes | every pull request | non-deterministic or drifted output |
| ASan / TSan / MSan | 2–10× | nightly on FFI crates | use-after-free, data races, uninit reads across FFI |

## CI wiring

```yaml
# .github/workflows/dynamic-checks.yml — sketch
jobs:
  careful:
    runs-on: ubuntu-latest
    steps:
      - run: rustup default nightly
      - run: cargo install cargo-careful
      - run: cargo +nightly careful test --workspace --no-fail-fast

  loom:
    runs-on: ubuntu-latest
    # Needed only if hand-rolled atomics exist. Skip the job otherwise.
    steps:
      - run: RUSTFLAGS="--cfg loom" cargo test --locked --release --tests

  golden:
    runs-on: ubuntu-latest
    steps:
      - run: bash tools/golden/run.sh

  fuzz_nightly:
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps:
      - run: cargo install cargo-fuzz
      - run: |
          for target in $(cargo fuzz list); do
            cargo +nightly fuzz run "$target" -- -max_total_time=900
          done
```

Miri, ASan, and TSan setup lives in `rust-sanitizers-miri`. This skill covers the rest.
The scheduled mutation-testing workflow is in
[references/mutation-testing.md](references/mutation-testing.md).

## Review gate

Before you approve a change, confirm each applicable item:

- [ ] New `unsafe` in pure Rust has a Miri run. New `unsafe` across FFI has a
      cargo-careful run.
- [ ] Every new hand-rolled atomic or lock-free primitive has a loom test.
- [ ] Every new parser or decoder has a `never_panics` proptest, and a roundtrip
      proptest where a roundtrip exists.
- [ ] Every fuzz crash is reduced to a committed regression test.
- [ ] A refactor of well-tested logic has a cargo-mutants run on the changed files, and
      each survived mutant is either fixed with a test or excluded with a reason.
- [ ] Deterministic output has committed golden baselines, and any baseline change is a
      deliberate commit.

## Related skills

- `rust-sanitizers-miri` — Miri as the primary UB path; ASan, TSan, MSan, and HWASan for FFI.
- `memory-model` — atomic orderings; every Relaxed publish/subscribe site is a loom-test candidate.
- `rust-unsafe` — `#[cfg(miri)]` stubbing for FFI; `ManuallyDrop` and `from_raw_parts` caution.
- `rust-tdd` — test-first workflow that these tools reinforce.
- `rust-panic-safety` — panic boundaries that proptest and fuzzing probe.
- `rust-discipline` — allocation rules on hot paths; the `large_stack_frames` lint.
- `rust-lints` — clippy lint configuration for the workspace.
- `cargo-workflows` — workspace setup; nextest profiles (`default`, `ci`).
