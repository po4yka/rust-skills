---
name: rust-test-tools
description: Use when choosing, adding, or reviewing a Rust test tool beyond plain cargo test, such as loom for hand-rolled atomics and lock-free code, proptest and cargo-fuzz for parsers of untrusted bytes, cargo-careful as an extra lane beside a sanitizer for FFI code that Miri cannot run, cargo-mutants with survived-mutant triage for weak tests, golden or snapshot files for deterministic output, and a differential fuzz target for a port with a reference implementation. Not for the test-first cycle (rust-tdd) or Miri and sanitizer setup (rust-sanitizers-miri).
license: BSD-3-Clause
---

# Rust Test Tools

A green `cargo test` does not find undefined behavior (UB), atomic-ordering bugs, parser edge
cases, weak assertions, or output drift. Pick the tool by the risk that the change adds. Run it
on the crate that the change touches while you iterate. Run the full lane once before merge.

## Pick the tool

| The change adds | Run | A green run does not prove |
|---|---|---|
| Pure-Rust `unsafe`: raw pointers, `transmute`, `MaybeUninit`, `from_raw_parts` | Miri. The `rust-sanitizers-miri` skill owns the flags and the aliasing-model policy | UB freedom on paths that the tests do not reach |
| `unsafe` next to foreign code: FFI, JNI, libc, syscalls | ASan on the host, or HWASan or MTE on a device; TSan when the code shares state across threads. cargo-careful is a cheap extra lane, not a substitute. Also Miri on the pure-Rust helpers, with the foreign calls stubbed under `#[cfg(miri)]`; the stub dereferences every pointer that the foreign side stores | UB freedom: a sanitizer does not know the Rust aliasing rules, and careful checks only a few UB classes |
| Hand-rolled atomics, a spinlock, a lock-free structure, a publish flag | loom | freedom from bugs that need load buffering or more preemptions than the bound |
| A parser, a decoder, or any function that reads untrusted bytes | proptest, then cargo-fuzz | freedom from bugs that the strategy or the corpus never reaches |
| A port or a rewrite of code that has a reference implementation | a differential fuzz target | equivalence outside the inputs that the fuzzer reached |
| A refactor of tested logic, or new tests for a critical change | cargo-mutants on the diff, or on the source files under test when the diff only adds tests | that the asserted values are the correct ones |
| Output that must be deterministic: serialized records, generated code, reports, images | golden files | that the first blessed baseline is correct |
| None of the above | the normal test run | behavior that no test asserts |

Code that uses only `std::sync::Mutex` or `RwLock`, or data-parallel code (for example rayon)
with no hand-rolled atomics, does not need loom.

## Lanes and cadence

If cargo-nextest is installed, use it as the runner. It runs each test in its own process, so
one abort or segfault does not hide the rest of the suite. Nextest does not run doctests, so run
them separately. Keep `--locked` so that a test run cannot rewrite `Cargo.lock`.

```bash
cargo nextest run --locked -p <crate> --no-fail-fast
cargo test --locked -p <crate> --doc

# Without nextest.
cargo test --locked -p <crate> --no-fail-fast
```

Run the tests for `unsafe` code in a debug build at least once. Since Rust 1.78, std checks unsafe
preconditions (for example the null and alignment rules of `slice::from_raw_parts`) when debug
assertions are on. A `--release` build removes these checks.

| Lane | Command | When |
|---|---|---|
| Tests, proptest, golden files | `cargo nextest run --locked --workspace` and `cargo test --locked --workspace --doc` | every pull request |
| cargo-careful | `cargo +nightly careful test --locked -p <ffi-crate> --no-fail-fast` | pull requests that touch `unsafe` or FFI crates |
| Miri, sanitizers | the `rust-sanitizers-miri` skill | pull requests that touch `unsafe`, and on a schedule |
| loom | `RUSTFLAGS="--cfg loom" cargo test --locked --release --test 'loom_*'` | pull requests that touch hand-rolled atomics |
| cargo-fuzz | `cargo +nightly fuzz run <target> -- -max_total_time=900` for each `cargo fuzz list` entry | nightly or weekly schedule, not every pull request |
| cargo-mutants | `--in-diff` run on demand, full run on a schedule | after a refactor, and weekly |

The `cargo-workflows` skill owns nextest profiles and the GitHub Actions rules (actions pinned to
a commit SHA, node24 action majors).

## Review gate

Before you approve a change, confirm each item that applies:

- [ ] New pure-Rust `unsafe` has a Miri run when a nightly toolchain with the `miri` component is
      installed; otherwise the report names it as not checked by Miri. This includes `unsafe` helpers inside an FFI
      crate, with the foreign calls stubbed under `#[cfg(miri)]`, and the stub dereferences
      every pointer that the foreign side stores (the `rust-sanitizers-miri` skill has the
      stub rules). A careful run alone is not UB evidence.
- [ ] New `unsafe` across FFI has an ASan run on the host, or a HWASan or MTE run on a device,
      and a TSan run when it shares state across threads.
- [ ] Every new hand-rolled atomic or lock-free primitive has a loom test that calls the crate's
      own type. The loom lane selects only the loom targets.
- [ ] Every new parser or decoder has a never-panics property, a roundtrip property where a
      roundtrip exists, and committed proptest regression files.
- [ ] Every fuzz crash is a committed, minimized regression test.
- [ ] A port with a reference implementation has a differential fuzz target.
- [ ] A refactor of tested logic has a cargo-mutants run on the diff. Each missed mutant has a
      test or a recorded exclusion.
- [ ] Deterministic output has committed golden files. Each fixture change is a reviewed,
      deliberate commit.

## cargo-careful

cargo-careful rebuilds the standard library with debug assertions and runs code that Miri cannot
run (foreign calls, system calls). It is a cheap extra lane, not a UB proof: it does not check
aliasing, general reads of uninitialized memory, use-after-free, or data races. A pure-Rust
`unsafe` helper inside an FFI crate still needs a Miri run. The foreign paths still need an ASan
run on the host, or a HWASan or MTE run on a device; the `rust-sanitizers-miri` skill owns that
setup.

Read [references/cargo-careful.md](references/cargo-careful.md) when you set up the lane (nightly
and `rust-src`), need the list of checks, or a flag from `target.<triple>.rustflags` is missing
in the careful run.

## loom

loom runs a test body under every thread interleaving that the preemption bound allows, and
it models the C11 memory orderings. A stress test samples a few schedules. loom enumerates
them. Know its limits before you trust a result:

- loom checks only the operations on its own types. Gate the atomics and a shared `UnsafeCell`
  to `loom::sync::atomic` and `loom::cell::UnsafeCell` under `cfg(loom)`, and spawn threads with
  `loom::thread::spawn`. A data race on a `std` type is invisible to loom, so the run can pass.
- loom treats `SeqCst` loads and stores as `AcqRel`. Code that needs `SeqCst` accesses can
  fail under loom and still be correct. loom models `fence(SeqCst)` correctly.
- loom does not explore load-buffering executions. A green loom run can hide such a bug.
- The cost grows exponentially with the number of atomic operations and the preemption bound.
  Test one primitive per test, with two or three threads.
- loom's scheduler is not fair. Under `cfg(loom)`, every spin or retry loop must call
  `loom::thread::yield_now()` (or `loom::hint::spin_loop()`). Otherwise the model fails with
  "Model exceeded maximum number of branches" (`LOOM_MAX_BRANCHES`, default 1000).

Declare loom under `[target.'cfg(loom)'.dependencies]`, because the library itself imports it,
and add a `check-cfg` entry for `cfg(loom)`. Do not use a `loom` Cargo feature: `--all-features`
turns it on, and every ordinary test that touches the primitive then panics. Make the loom test call the crate's own type, not a
copy of the algorithm. Select only the loom targets (`--test 'loom_*'`). With `--tests` or a bare
`cargo test`, every other test that touches the primitive runs outside `loom::model` and panics
with "cannot access Loom execution state from outside a Loom model". Gate such tests with
`#[cfg(not(loom))]` if they must share a run.

Read [references/loom.md](references/loom.md) when you set up loom in a crate, gate a `static`
atomic or an `UnsafeCell`, need a worked example with its failure output, or must bound a slow
run.

## proptest

Write properties for any function that takes bytes, text, or a configuration value and
produces a parsed or validated result. Assert invariants, not single examples.

```rust
use proptest::prelude::*;

proptest! {
    // Total function: no panic for any byte string.
    #[test]
    fn parse_never_panics(buf in prop::collection::vec(any::<u8>(), 0..1024)) {
        let _ = Header::parse(&buf);
    }

    // Roundtrip: serialize a parsed header and get the consumed prefix back.
    #[test]
    fn parse_then_serialize_roundtrips(buf in prop::collection::vec(any::<u8>(), 0..4096)) {
        if let Ok(hdr) = Header::parse(&buf) {
            let mut out = Vec::new();
            hdr.write_to(&mut out);
            prop_assert_eq!(&out, &buf[..hdr.len()]);
        }
    }

    // Structured roundtrip: generate a valid value, encode it, and decode it back.
    #[test]
    fn decode_roundtrips_valid_input(value in arb_valid_message()) {
        let decoded = decode(&value.encode()).expect("valid input must decode");
        prop_assert_eq!(decoded, value);
    }

    // Text: "(?s).*" also generates '\n'. ".*" and any::<String>() never do.
    #[test]
    fn text_parser_never_panics(s in "(?s).*") {
        let _ = parse_document(&s);
    }
}
```

- Random bytes seldom get past a magic number or a checksum. The structured strategy reaches
  the deeper code, so write one for every format with such a check.
- A line-based parser tested with `".*"` or `any::<String>()` never sees a newline (probe on
  proptest 1.11.0). Use `"(?s).*"`.
- proptest saves each failing case and runs it first on the next run. A test in `src/` saves to
  `proptest-regressions/` at the crate root. An integration test saves to
  `tests/<name>.proptest-regressions`. Commit these files.
- For a deeper local run, raise the case count:
  `PROPTEST_CASES=10000 cargo test --locked -p <crate> parse_`.

A new parser without a never-panics property is incomplete.

## cargo-fuzz

proptest finds the bugs that a strategy can reach. A coverage-guided fuzzer also finds the
bugs that only a mutated corpus reaches, above all in binary protocol and container decoders.

```bash
# Setup, once per crate. Building and running a target needs nightly.
cargo install --locked cargo-fuzz
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
cargo +nightly fuzz run parse_header -- -max_total_time=600
cargo fuzz list

# Reproduce a crash from a saved artifact, then shrink it.
cargo +nightly fuzz run parse_header fuzz/artifacts/parse_header/crash-<id>
cargo +nightly fuzz tmin parse_header fuzz/artifacts/parse_header/crash-<id>
```

- Fuzz the outermost entry point that takes untrusted bytes: a frame or header decoder, an
  archive reader, a decompressor, a document parser.
- A length field that drives an allocation is the usual out-of-memory crash. Cap the length in
  the parser, not in the fuzz target.
- A recursive parser needs a nesting-depth limit. Deep nesting overflows the stack. The
  report shows `AddressSanitizer: stack-overflow` in the default ASan build, or
  `has overflowed its stack` without ASan. Cap the depth in the parser, not in the fuzz target.
- Turn every crash into a regression test. Shrink it with `tmin`, commit the input (for example
  under `tests/regressions/`), and add a test that feeds it to the entry point.

## Differential testing

When a change ports or rewrites code that has a reference implementation (a C library, the
previous Rust version, a model of the spec), run a differential fuzz target. Feed the same bytes
to both and compare the results. A port that is memory-safe and passes its own tests can still
disagree with the reference.

```rust
// fuzz/fuzz_targets/decode_matches_reference.rs
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let ours = my_crate::decode(data).ok();
    let reference = reference_impl::decode(data).ok();
    assert_eq!(ours, reference, "decoders disagree on {data:?}");
});
```

- Compare acceptance and the value. Compare the error kind too when callers depend on it.
- Seed `fuzz/corpus/<target>/` with non-ASCII text and invalid UTF-8: a lone continuation byte
  (`0x80`), an overlong encoding (`0xC0 0xAF`), and a truncated 4-byte sequence. Ports often
  differ on non-ASCII and invalid UTF-8 input.

## cargo-mutants

cargo-mutants changes the code (it replaces a function body with a default value, flips a
comparison, or deletes a call) and reruns the tests for each change. A mutant that survives
marks code that the tests run but do not check. It also exposes a new test that never calls the
changed function; the `rust-tdd` skill owns that rule.

```bash
cargo install --locked cargo-mutants

# Fastest useful loop: only the lines that the branch changes.
git diff origin/main...HEAD > /tmp/pr.diff
cargo mutants --test-tool nextest --cargo-arg=--locked --in-diff /tmp/pr.diff --package <crate> -j2 --output target/

# One whole crate.
cargo mutants --test-tool nextest --cargo-arg=--locked --package <crate> -j2 --output target/
```

Without cargo-nextest, drop `--test-tool nextest`; cargo-mutants then runs `cargo test`.

- A diff that only adds or changes tests gives no mutants, because `--in-diff` matches only the
  code under test. For new tests of existing code, run
  `cargo mutants --test-tool nextest --cargo-arg=--locked --file <source-file>` (or
  `--package <crate>`).
- cargo-mutants runs cargo without `--locked`. Pass `--cargo-arg=--locked`, or set
  `additional_cargo_args = ["--locked"]` in `.cargo/mutants.toml`, not both: cargo rejects a
  repeated `--locked`.
- Results go to `<output>/mutants.out/`. Exit code 2 means some mutants survived. Exit code 4
  means the tests fail before any mutation, so fix the suite first.

Triage `mutants.out/missed.txt`. It is the gate, not a score: cargo-mutants defines no
threshold.

1. For each missed mutant, read the function and the change. `mutants.out/diff/` holds each
   change as a diff.
2. If a test must catch the change, write a test that asserts the exact value or side effect.
3. If the code cannot be tested in a useful way (`Display` or `Debug` output, logging, FFI
   glue), exclude it with `exclude_re` in `.cargo/mutants.toml` or with `#[mutants::skip]`.
   Record the reason next to the exclusion. Do not write a meaningless test to raise the count.

Do not block every pull request on a full run: it takes minutes to hours, and some mutants are
equivalent to the original code.

Read [references/mutation-testing.md](references/mutation-testing.md) when you write
`.cargo/mutants.toml`, pick `-j` or `--dir`, need the full flag or exit-code table, suspect a
false positive (for example a doctest-only behavior under nextest), or set up the scheduled CI
workflow.

## Golden files

A golden test compares output with a committed file. Use it for output that another party
reads: serialized records, exported reports, generated code, protocol frames, rendered images.
Put the fixtures in `tests/golden/` of the crate that owns the output, and the test in
`tests/golden_contracts.rs`. Cargo builds each `.rs` file directly under `tests/` as a test
binary, and it skips a subdirectory that has no `main.rs`.

```rust
use std::path::Path;

/// Compares `actual` with `tests/golden/<name>`. `BLESS_GOLDENS=1` rewrites the file.
fn assert_golden(name: &str, actual: &str) {
    // env! resolves at compile time, so the path does not depend on the working directory.
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden").join(name);
    if std::env::var("BLESS_GOLDENS").as_deref() == Ok("1") {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, actual).unwrap();
        return;
    }
    let expected = std::fs::read_to_string(&path).unwrap_or_else(|error| {
        panic!("missing golden {}: {error}; bless it with BLESS_GOLDENS=1", path.display())
    });
    assert_eq!(actual, expected, "golden mismatch for {}", path.display());
}
```

```bash
cargo nextest run --locked -p <crate> --test golden_contracts                  # compare
BLESS_GOLDENS=1 cargo nextest run --locked -p <crate> --test golden_contracts  # bless
git diff -- tests/golden/                                                      # review
```

- Never set the bless variable in CI. A missing fixture must fail the run, and the helper
  panics for that reason.
- Bless only an intended output change. Read the fixture diff before you commit. Never bless to
  turn a red run green.
- Make the output deterministic before you compare it. Replace timestamps, generated IDs, ports,
  temporary paths, and host names with placeholders. Iterate a `HashMap` or `HashSet` in sorted
  order, or use a `BTreeMap`: std hash iteration order changes from one process to the next.
- Do not build a golden file or an `insta::assert_debug_snapshot!` from `Debug` (`{:?}`)
  output. std does not keep that format stable, and Rust 1.98 escapes more characters in
  strings and chars. Serialize with the real output format instead.
- Text: compare byte for byte. Add `**/tests/golden/** -text` to the root `.gitattributes` (or
  `tests/golden/** -text` to a `.gitattributes` in the crate directory), so that a checkout
  with `core.autocrlf` does not rewrite the line endings. A pattern with a slash is anchored
  to the directory of its `.gitattributes` file.
- Binary: compare the bytes from `std::fs::read`. For a PDF or an archive, remove the embedded
  timestamps first.
- Raster images: compare decoded pixels, exactly or with a stated per-channel tolerance. Do not
  compare encoded PNG bytes: another encoder version or setting gives other bytes for the same
  pixels.
- If the crate already uses `insta`, use its macros and `cargo insta review`. Do not add a
  second golden mechanism.

## Related skills

These skills own the adjacent topics, when they are installed:

- `rust-sanitizers-miri`: Miri flags and model policy; `#[cfg(miri)]` stubs for foreign calls;
  ASan, TSan, MSan, and HWASan.
- `memory-model`: the choice of atomic orderings that a loom test checks.
- `rust-unsafe`: SAFETY contracts and the `unsafe` audit surface.
- `rust-tdd`: the test-first cycle, and tests that call the changed code.
- `cargo-workflows`: nextest profiles and CI workflow rules.
