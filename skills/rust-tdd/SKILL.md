---
name: rust-tdd
description: Use when writing Rust code test-first (TDD, red-green-refactor), reproducing a bug as a failing test, pinning behavior before a refactor, or reviewing whether tests came first. Also for hand-written fakes with a fault-injection queue, async tokio tests with paused time, and the review of a golden-contract bless. Not for loom, proptest, fuzzing, mutation testing, or golden-file mechanics; use rust-test-tools.
license: BSD-3-Clause
---

# Rust TDD

One invariant carries the whole method: the test fails first, for the reason you predicted.
A test written after the implementation only shows that the code does what the code does.
Every step below serves that invariant.

## The cycle

Repeat this cycle for each behavior. One test, one behavior, one cycle.

1. **RED** — Write one failing test. Write down the expected failure in one sentence: which
   assertion fails, and with which value. Run the test and compare.
2. **GREEN** — Write the minimum implementation that makes the test pass. Run the test
   again. Add no code that no test requires.
3. **REFACTOR** — Clean up the test and the implementation. Run the tests of the crate.

Run the format and lint gate once before each commit, not after each cycle. The
[Verification](#verification) section has the commands.

### Read the RED result

| Observed result | What it means | Action |
|---|---|---|
| Fails as predicted | The test controls the behavior you target | Go to GREEN |
| Passes | The behavior exists already, or the test asserts nothing | Fix the test, or delete it and pick a real gap |
| 0 tests ran | The filter matched nothing: a typo or a wrong module path | Fix the filter until the run reports exactly 1 test |
| Fails, but not as predicted | You do not understand the code yet | Stop. Read the code. Rewrite the test. |
| Panics with `not yet implemented` | A `todo!()` stub panicked before the assertion ran | Make the stub return a wrong but valid value, such as `Default::default()` |
| Does not compile | Not a RED yet | Add the signature with a stub body, then run again |

The test must call the changed code and assert on its result. A test that drives only a
fake, a wrapper, or a copy of the logic passes whatever the change does. The RED-to-GREEN
transition is the proof that the test depends on the change. Report the RED failure line and
the test count with the change.

## Verification

Run the gate once before each commit:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo nextest run --locked -p <crate>      # without nextest: cargo test --locked -p <crate>
cargo test --locked --doc -p <crate>       # when the crate has doctests
```

When the change touches an API that other workspace crates use, and always before merge, run
`cargo nextest run --locked --workspace` (without nextest: `cargo test --locked --workspace`)
and `cargo test --locked --workspace --doc`.

- Add `--all-features` to the clippy and test commands only when the workspace features are
  additive. Otherwise check each supported feature set. The `cargo-workflows` skill, when it
  is installed, has the feature-matrix commands.
- `--all-targets` lints test code too. The `rust-lints` skill, when it is installed, owns the
  lint set.
- For a crate that has only doctests, cargo-nextest finds no test and exits 4. Run
  `cargo test --locked --doc -p <crate>` for that crate.

What a green run does not prove:

| Green result | Does not prove | Check |
|---|---|---|
| A cargo-nextest run | That the doctests pass | `cargo test --locked --doc -p <crate>` |
| A filtered run | That any test ran | Read the test count |
| A cargo-nextest run | That the suite passes under `cargo test`, which runs the tests of one binary as threads of one process and shares statics, environment variables, and the current directory | `cargo test --locked -p <crate>` when tests touch process-global state |
| A `#[should_panic]` test | That the expected panic fired: without `expected`, any panic passes, including an `unwrap()` in the setup | Pin `expected = "<message substring>"` |
| An async test that spawns tasks | That the tasks did not panic: tokio reports a task panic only through its `JoinHandle` | Await every `JoinHandle` and check its result |
| Any test run | That `unsafe` code has no undefined behavior | The `rust-sanitizers-miri` skill, when it is installed |
| New tests pass | That the tests constrain the change | The RED-to-GREEN transition. For a critical change, `cargo mutants --in-diff <diff-file>`; the `rust-test-tools` skill, when it is installed, has the setup. |

Commit rules:

- Land each test in the same commit as the implementation it drove. Characterization tests
  of existing behavior are the exception: they pass on the current code, so they land first,
  in their own commit.
- Do not delete, weaken, `#[ignore]`, or re-bless a test to make the build green. A failing
  test is information. Fix the code or fix the assertion, and say which one you changed.
- Leave no `todo!()` or `unimplemented!()` stub in the commit.

Read [references/testing-anti-patterns.md](references/testing-anti-patterns.md) when you
review a test suite that somebody else wrote, or when a test is flaky. It has the flaky-test
triage table.

## Run one test at a time

Use cargo-nextest when it is installed (`cargo nextest --version` succeeds). It runs each
test in its own process, so an abort, a segfault, or a stack overflow in one test does not
end the run, and process-global state does not leak between tests. Otherwise use
`cargo test`.

| Goal | cargo-nextest | cargo test (libtest) |
|---|---|---|
| Tests whose name contains a substring | `cargo nextest run --locked -p <crate> <substring>` | `cargo test --locked -p <crate> <substring>` |
| One test by its exact path | `cargo nextest run --locked -p <crate> -E 'test(=module::tests::name)'` | `cargo test --locked -p <crate> -- --exact module::tests::name` |
| One integration test file `tests/<file>.rs` | `cargo nextest run --locked -p <crate> --test <file>` | `cargo test --locked -p <crate> --test <file>` |
| Show the output of passing tests | add `--no-capture` (it also runs tests serially) | add `-- --no-capture` |
| Doctests | not supported | `cargo test --locked --doc -p <crate>` |

Read the test count on every filtered run. A filter that matches nothing is a false green:
`cargo test <filter>` prints `0 passed; ... N filtered out` and exits 0. cargo-nextest prints
`error: no tests to run` and exits 4.

Write `--no-capture`. libtest deprecated the `--nocapture` spelling in Rust 1.88. The old
spelling still works without a warning, so copied commands keep it alive. `--no-capture`
needs Rust 1.88 or later; an older libtest rejects it with `Unrecognized option`. On an
older toolchain, such as an MSRV lane, set `RUST_TEST_NOCAPTURE=1`. It works on both sides
of 1.88.

Pass `--locked` to every cargo command that builds or runs code. It fails when `Cargo.lock`
is missing or would change, so a green run used the dependency set that CI uses. Commit
`Cargo.lock` for every package, libraries included; the `cargo-workflows` skill, when it is
installed, owns the lockfile policy. When `--locked` fails after a manifest edit, resolve the
lock without a build: `cargo metadata --format-version 1 > /dev/null`. Vet each new package
name in the lock diff (the `rust-security` skill, when it is installed), commit the lock with
the manifest change, and rerun with `--locked`. Do not run the tests once without `--locked`
to update the lock: that compiles and runs the build scripts and proc macros of packages that
nobody vetted.

## Variants of the cycle

### New feature

Start from the smallest observable behavior of the public API. Add one test per behavior.
Grow the API only when a test needs it.

### Bug fix

1. Write a test that reproduces the bug through the public API. Run it. It must fail with
   the reported symptom.
2. Find the root cause. Fix it at the single place that all callers route through, not at
   the call site named in the report.
3. Run the reproduction test. It must pass.
4. Search for code that repeats the defective logic outside the fixed function. Add a
   reproduction test for each copy you find.

Keep the reproduction test after the fix. It is the regression guard.

### Refactor

A refactor must not change behavior, so it needs no new RED. It needs proof that the
behavior is already pinned.

1. Run the existing tests. They must pass before you change anything.
2. If the tests cover the target code poorly, write characterization tests first. Assert the
   current behavior, including the parts you find ugly. Commit them on their own.
3. Refactor in small steps. Run the tests after each step.
4. If a test needs an edit to keep compiling, the change is not a pure refactor. Split the
   work: the behavior change with its own RED, then the refactor.

For a port or a rewrite that has a reference implementation, add a differential property or
fuzz target that feeds the same input to both, including non-ASCII and invalid UTF-8 input.
The `rust-test-tools` skill, when it is installed, has the setup.

### Keep test design independent of the implementation plan

The test must encode the behavior that the caller needs, not the implementation you have in
mind. When the harness offers an independent context, such as a subagent, give it the
behavior statement, the public API, and the test rules it needs: the predicted RED failure,
`--locked`, and the naming and fake conventions of this skill. Do not give it your
implementation sketch. Let it write the failing test, then implement against that test in the
main context. Without an independent context, write the test from the behavior statement
before you plan the implementation.

## Test placement

Pick the cheapest layer that can observe the behavior. Escalate only when the behavior
needs real I/O, a real peer, or a real host runtime.

| What you test | Location | Command |
|---|---|---|
| Internal logic of one module | `#[cfg(test)] mod tests` in the same file | `cargo nextest run --locked -p <crate> <name>` |
| Public API of one crate | `tests/*.rs` in that crate | `cargo nextest run --locked -p <crate> --test <file>` |
| Documented usage of the public API | `///` doc comment examples | `cargo test --locked --doc -p <crate>` |
| Command-line behavior of a binary | `tests/*.rs` that runs `env!("CARGO_BIN_EXE_<name>")` | `cargo nextest run --locked -p <crate> --test <file>` |
| Wiring between crates | integration tests of the crate that owns the composition | `cargo nextest run --locked --workspace` |
| FFI boundary behavior | tests inside the boundary crate, plus one test on the host-language side | boundary crate tests, then the host test runner |
| Network or process end-to-end | `tests/*.rs` with `#[ignore = "needs network"]`, or behind a cargo feature | `cargo nextest run --locked -p <crate> --run-ignored all`; libtest: `cargo test --locked -p <crate> -- --include-ignored` |

Unit tests in `#[cfg(test)] mod tests` can reach private items. Integration tests in
`tests/` can reach only the public API, so they catch API design problems that unit tests
hide. Write the public-API test when the behavior is part of the contract. Do not make an
item `pub` only for a test.

Cargo builds each binary of the package before it compiles the integration tests, and sets
`CARGO_BIN_EXE_<name>` to the path of the binary. Do not hard-code `target/debug/<name>`. That
path changes with `--target`, `--profile`, and `CARGO_TARGET_DIR`. Cargo does not build a
binary whose `required-features` are off, so the test fails with `NotFound` or runs a stale
binary from an earlier build. Enable those features for the test run.

## Test names and panic tests

Name the behavior and the condition in `snake_case`, for example
`start_returns_error_when_transport_is_already_running`, not `test_start`. This is the
catalog default, because a failure report then says what broke before anyone opens the file.

Pin the message of every panic test. `expected` matches a substring of the panic message.

```rust
#[test]
#[should_panic(expected = "capacity must be non-zero")]
fn new_rejects_zero_capacity() {
    Buffer::new(0);
}
```

Enable `clippy::should_panic_without_expect` and `clippy::ignore_without_reason` in the
workspace lint table. Both lints are pedantic, so they are off by default. With them on, the
`-D warnings` gate rejects a bare `#[should_panic]` and a bare `#[ignore]`. The `rust-lints`
skill, when it is installed, owns the lint table.

## Test doubles: hand-written fakes

Hand-written fakes are the default in this skill. A reader can see everything a fake does,
a fake survives harmless refactors, and a fake that is hard to write shows a wrong seam. When
the workspace already uses a mocking crate, follow the workspace convention.

- Define the seam as a trait in the production crate. The fake implements the trait.
- Name the fake `Fake` + trait name, for example `FakeTransport` for `Transport`.
- Record call counts and the last arguments in public fields, so the test can assert them.
- Configure return values and faults before the test runs.
- Put shared fakes in one place: a test-support module gated by `#[cfg(test)]`,
  `tests/common/mod.rs` for integration tests, or a small workspace crate that other crates
  use only as a dev-dependency.
- Create a fresh fake in every test. Shared mutable fake state makes the result depend on
  the test order.

Assert the observable result first, then the interaction. A call counter alone shows that
the code called something, not that the behavior is right.

## Fault injection for error paths

An `if cfg!(test)` branch in production code is not a test of an error path. Drive failures
from the fake through one typed queue: a `FaultQueue<T>` of `FaultSpec<T>` entries, each with
a target, a `FaultOutcome`, and a `FaultScope`. A `OneShot` fault fires once. A `Persistent`
fault fires on every matching call until you clear it.

Read [references/fault-injection.md](references/fault-injection.md) when you write a fake,
add the queue to a workspace, or pick an outcome or a scope. It has a complete
`FakeTransport`, the queue implementation, the outcome-to-failure-mode table, the scope
rules, and the check that a fault really fired.

```rust
use std::assert_matches;

#[test]
fn start_maps_transport_failure_to_service_error() {
    let transport = Arc::new(FakeTransport::default());
    transport.faults.enqueue(FaultSpec {
        target: TransportFault::Start,
        outcome: FaultOutcome::Error,
        scope: FaultScope::OneShot,
        message: Some("simulated start failure".to_owned()),
        payload: None,
    });

    let service = Service::new(Arc::clone(&transport));

    let error = service.start().expect_err("start must fail when the transport fails");
    assert_matches!(error, ServiceError::Transport { .. });
    assert_eq!(transport.start_calls.load(Ordering::Relaxed), 1);
}
```

`std::assert_matches!` (Rust 1.96) prints the value that did not match. It is not in the
prelude, so import it. Below MSRV 1.96, use `assert!(matches!(..))`, which prints only the
expression text. For cancellation and progress faults across an FFI boundary, use the
`ffi-error-progress-cancel` skill, when it is installed.

## Async tests with tokio

Use `#[tokio::test]` for code that runs on tokio. It builds a fresh current-thread runtime
for each test. Three runtime mistakes fail or hang the test for a reason that is not the
behavior:

- A tokio timer or I/O type used outside a runtime, for example in a plain `#[test]` through
  `futures::executor::block_on`, panics with `there is no reactor running`.
- A `Runtime::block_on` inside `#[tokio::test]` panics with `Cannot start a runtime from
  within a runtime`. Use `.await` instead.
- Inside `#[tokio::test]`, a blocking wait such as `futures::executor::block_on` or
  `std::sync::mpsc::Receiver::recv` blocks the only runtime thread. Spawned tasks and timers
  then cannot run, so a wait on one of them hangs the test. Use `.await` instead.

Do not synchronize a test with a sleep: the suite is slow when it passes and flaky when it
fails. Use a channel. For code that waits on a timer, use
`#[tokio::test(start_paused = true)]`, with the tokio `test-util` feature in
`dev-dependencies` only. Read [references/async-tests.md](references/async-tests.md) when a
test waits on time, or asserts a state while an operation is in flight. It has the
paused-clock rules and a gated-fake example.

## Golden contract tests

A golden test compares output that another party parses with a committed fixture:
serialized records, exported reports, generated code, protocol frames. The `rust-test-tools`
skill, when it is installed, owns the harness mechanics: fixture layout, update mode, and
byte-exact or pixel-exact comparison. These blessing rules apply to every golden test:

1. Run golden tests read-only by default, in CI and in every normal run. Put the update path
   behind one explicit switch, such as `BLESS_GOLDENS=1` or an `--update` flag.
2. Bless only an intended contract change. An unexpected golden failure means the production
   code changed behavior. Find out why before you bless.
3. Read every changed fixture line with `git diff` before you commit. Explain the contract
   change in the commit message.
4. Replace volatile fields with deterministic placeholders before comparison: timestamps,
   generated identifiers, ephemeral ports, temporary paths, host names. An unscrubbed field
   fails on the second run.

## Related skills

Each of these applies when it is installed.

- `rust-test-tools` — proptest, loom, cargo-mutants, cargo-fuzz, and golden-test mechanics.
- `rust-lints` — the lint set behind the clippy gate.
- `cargo-workflows` — the cargo command set, the lockfile policy, and feature matrices.
- `rust-panic-safety` — what may panic, and how to contain a panic at a boundary.
- `rust-debugging` — what to do when a test fails and you cannot see why.
- `rust-sanitizers-miri` — undefined behavior that a passing test suite does not report.
- `ffi-error-progress-cancel` — error, progress, and cancellation contracts across FFI.
