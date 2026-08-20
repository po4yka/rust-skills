---
name: rust-tdd
description: Use when you start a Rust behavior change, reproduce a bug, refactor code that must keep its behavior, or review whether tests were written first. Covers a red-green-refactor-lint cycle with cargo and cargo-nextest, single-test runs, unit through end-to-end placement, hand-written fakes, a fault-injection queue, async tests with tokio, golden-contract tests with a safe bless procedure, and a subagent split that separates test design from implementation.
license: BSD-3-Clause
---

# Rust TDD

## Purpose

This skill is **rigid**. Follow every step exactly. Do not skip RED. Do not write
implementation before a failing test exists.

The value of TDD is not the test file. The value is that the test failed first, for the
reason you predicted. A test written after the implementation only proves that the code
does what the code does.

## The cycle

Repeat this cycle for every behavior change:

1. **RED** — Write exactly one failing test. Run it. Confirm that it fails, and that it
   fails for the expected reason. A compile error is not a valid RED. Make the test
   compile, then let the assertion fail.
2. **GREEN** — Write the minimum implementation that makes the test pass. Run the test
   again. Do not add code that no test requires.
3. **REFACTOR** — Clean up the test and the implementation. Run the crate tests to confirm
   that nothing broke.
4. **LINT** — Run the format and lint gate before you call the cycle complete.

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
```

`--all-targets` includes tests, benches, and examples. The lint gate applies to test code
too. See the `rust-lints` skill for the lint set and for allow-with-reason policy.

Never batch multiple behaviors into one cycle. One test, one behavior, one cycle.

### RED is a prediction, not a formality

Before you run the failing test, write down the expected failure in one sentence: which
assertion fails, and with which value. Then run it.

| Observed result | What it means | Action |
|---|---|---|
| Fails as predicted | The test controls the behavior you target | Go to GREEN |
| Passes immediately | The behavior already exists, or the test asserts nothing | Fix the test, or delete it and pick a real gap |
| Fails, but not as predicted | You do not understand the code yet | Stop. Read the code. Rewrite the test. |
| Does not compile | Not a RED yet | Add the minimal signature or stub, then re-run |

## Variants of the cycle

### New feature

Start from the smallest observable behavior of the public API. Add one test per behavior.
Grow the API only when a test needs it.

### Bug fix

1. Write a test that reproduces the bug from the public API. Run it. It must fail with the
   reported symptom.
2. Find the root cause. Fix it at the single place that all callers route through, not at
   the call site named in the report.
3. Run the reproduction test. It must pass.
4. Search for sibling callers of the fixed function. Add a test for any caller that has the
   same defect.

Never delete or weaken the reproduction test after the fix. It is the regression guard.

### Refactor

A refactor must not change behavior, so it needs no new RED. It needs proof that the
behavior is already pinned.

1. Run the existing tests. They must pass before you touch anything.
2. If coverage of the target code is thin, write characterization tests first. Assert the
   current behavior, including the parts you find ugly. Commit them separately.
3. Refactor in small steps. Run the tests after each step.
4. If a test needs an edit to keep compiling, the change is not a pure refactor. Split the
   commit: behavior change with its own RED, then refactor.

## Run one test at a time

Use `cargo nextest` as the default runner. It runs each test in its own process, so a panic
or an abort in one test does not take the run down, and per-test isolation removes a whole
class of shared-state flakes.

```bash
# Single test by substring
cargo nextest run --locked -p <crate> <name_substring>

# Single test by exact name (filterset syntax)
cargo nextest run --locked -p <crate> -E 'test(=module::tests::exact_name)'

# Single integration test file: tests/<file>.rs
cargo nextest run --locked -p <crate> --test <file>

# Single crate
cargo nextest run --locked -p <crate>

# Full workspace
cargo nextest run --locked --workspace

# Show stdout and stderr of passing tests
cargo nextest run --locked -p <crate> <name_substring> --no-capture
```

The built-in runner stays useful for two cases that nextest does not cover:

```bash
# Doc tests — nextest does not run them
cargo test --locked --doc -p <crate>

# Exact single test with the libtest harness
cargo test --locked -p <crate> -- --exact module::tests::exact_name --nocapture
```

Always pass `--locked`. It makes the run fail instead of silently editing `Cargo.lock`, so
a green test run means the same dependency set that CI will use. See the
`cargo-workflows` skill for the full command set.

## Test placement

Pick the cheapest layer that can observe the behavior. Escalate only when the behavior
genuinely needs real I/O, a real peer, or a real host runtime.

| What you test | Location | Command |
|---|---|---|
| Internal logic of one module | `#[cfg(test)] mod tests` in the same file | `cargo nextest run --locked -p <crate> <name>` |
| Public API of one crate | `tests/*.rs` in that crate | `cargo nextest run --locked -p <crate> --test <file>` |
| Documented usage of the public API | `///` doc comment examples | `cargo test --locked --doc -p <crate>` |
| Wiring between crates | integration tests of the crate that owns the composition | `cargo nextest run --locked --workspace` |
| FFI boundary behavior | tests inside the boundary crate, plus one test on the host-language side | boundary crate tests, then the host test runner |
| Network or process end-to-end | `tests/*.rs` behind `#[ignore]` or a cargo feature | `cargo nextest run --locked -p <crate> --run-ignored all` |

Unit tests in `#[cfg(test)] mod tests` can reach private items. Integration tests in
`tests/` can only reach the public API, which is exactly why they catch API design
problems that unit tests hide. Write the public-API test when the behavior is part of the
contract.

## Test names

Use `snake_case`. Name the behavior and the condition, not the function under test.

```rust
// Good — states behavior and condition.
#[test]
fn start_returns_error_when_transport_is_already_running() { /* ... */ }

// Bad — names the method, asserts nothing in particular.
#[test]
fn test_start() { /* ... */ }
```

When a test asserts a panic, always pin the message:

```rust
#[test]
#[should_panic(expected = "capacity must be non-zero")]
fn new_rejects_zero_capacity() {
    Buffer::new(0);
}
```

`#[should_panic]` without `expected` passes on any panic, including an unrelated
`unwrap()` on a different line. See the `rust-panic-safety` skill for what may panic at
all.

## Test doubles: hand-written fakes

Write fakes by hand. Do not add a mocking crate.

Reasons: a mocking crate adds implicit behavior that no reader of the test can see, makes
tests brittle to harmless refactors, and hides design problems that a hand-written fake
makes obvious. When a fake is hard to write, the seam is wrong. Fix the seam.

Conventions:

- Define the seam as a trait in the production crate. The fake implements the trait.
- Name the fake `Fake` + trait name, for example `FakeTransport` for `Transport`.
- Record call counts and the last arguments in public fields, so the test can assert them.
- Make return values configurable before the test runs.
- Put shared fakes in one place: a `test_support` module gated by `#[cfg(test)]`, a
  `tests/common/mod.rs` for integration tests, or a small `dev-dependencies`-only crate in
  the workspace when several crates need the same fake.

```rust
pub trait Transport: Send + Sync {
    fn start(&self) -> Result<(), TransportError>;
    fn send(&self, frame: &[u8]) -> Result<usize, TransportError>;
}

#[derive(Default)]
pub struct FakeTransport {
    pub start_calls: AtomicUsize,
    pub send_calls: AtomicUsize,
    pub last_frame: Mutex<Option<Vec<u8>>>,
    pub faults: FaultQueue<TransportFault>,
}

impl Transport for FakeTransport {
    fn start(&self) -> Result<(), TransportError> {
        self.start_calls.fetch_add(1, Ordering::Relaxed);
        match self.faults.take(&TransportFault::Start) {
            Some(FaultOutcome::Error) => Err(TransportError::Io),
            Some(FaultOutcome::Timeout) => Err(TransportError::Timeout),
            Some(FaultOutcome::Panic) => panic!("simulated fault: transport start"),
            _ => Ok(()),
        }
    }

    fn send(&self, frame: &[u8]) -> Result<usize, TransportError> {
        self.send_calls.fetch_add(1, Ordering::Relaxed);
        *self.last_frame.lock().unwrap() = Some(frame.to_vec());
        match self.faults.take(&TransportFault::Send) {
            Some(FaultOutcome::Error) => Err(TransportError::Io),
            _ => Ok(frame.len()),
        }
    }
}
```

Create a fresh fake in every test. Never share mutable fake state between test functions.

## Fault injection for error paths

Error paths need tests as much as happy paths, and ad-hoc `if cfg!(test)` branches in
production code are not tests. Drive failures from the fake through one queue.

The queue has four parts:

- `FaultQueue<T>` — ordered queue of faults, matched by a target enum `T`.
- `FaultSpec<T>` — target, outcome, scope, and an optional message or payload.
- `FaultScope` — `OneShot` fires once and is consumed. `Persistent` fires on every
  matching call until you clear it.
- `FaultOutcome` — the failure mode to simulate.

The full `FaultQueue` implementation, the outcome-to-failure-mode mapping, and the
cleanup rules are in `references/fault-injection.md`.

Use it from the test:

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransportFault {
    Start,
    Send,
    Stop,
}

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
    assert!(matches!(error, ServiceError::Transport { .. }));
    assert_eq!(transport.start_calls.load(Ordering::Relaxed), 1);
}
```

Default to `OneShot`. Use `Persistent` only when the test exercises repeated calls to the
same target, such as a retry or a polling loop. For cancellation and progress faults across
an FFI boundary, see the `ffi-error-progress-cancel` skill.

## Async tests

Use `#[tokio::test]` for async behavior. Do not call a blocking executor entry point such
as `block_on` inside a test body — it hides the real scheduling and turns timing bugs into
passes.

For code that waits on time, start the test with paused time so that the runtime
auto-advances instead of sleeping in real time:

```rust
#[tokio::test(start_paused = true)]
async fn retry_backs_off_before_the_second_attempt() { /* ... */ }
```

`start_paused` needs the tokio `test-util` feature. Enable it in `dev-dependencies` only,
so it never reaches a release build:

```toml
[dev-dependencies]
tokio = { version = "1", features = ["macros", "rt-multi-thread", "test-util"] }
```

Never synchronize a test with a sleep. Use a channel. When you must assert an intermediate
state while an operation is in flight, gate the fake with two `oneshot` channels: one that
signals that the fake was reached, one that releases it.

```rust
#[tokio::test]
async fn state_is_starting_while_transport_start_is_in_flight() {
    let (started_tx, started_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let transport = Arc::new(FakeTransport::gated(started_tx, release_rx));
    let service = Arc::new(Service::new(Arc::clone(&transport)));

    let task = tokio::spawn({
        let service = Arc::clone(&service);
        async move { service.start().await }
    });

    // The fake reached start() and now blocks.
    started_rx.await.expect("transport start was never called");
    assert_eq!(service.state(), State::Starting);

    // Release the fake and let the operation finish.
    release_tx.send(()).expect("task dropped the release channel");
    task.await.expect("task panicked").expect("start must succeed");
    assert_eq!(service.state(), State::Running);
}
```

Clean up at the end of every async test: abort or await every `JoinHandle` you spawned, and
clear the fault queue. A leaked task keeps running under the next test and produces a
failure with a stack trace that points at innocent code.

## Golden contract tests

A golden test compares produced output against a committed fixture. Use it for output that
another party parses: serialized records, exported reports, generated code, protocol
frames. See the `rust-test-tools` skill for the wider dynamic-test toolkit.

Golden fixtures live in `tests/golden/` inside the crate that owns the contract. Cargo
compiles every `.rs` file directly under `tests/` as its own test binary, and ignores
subdirectories that hold no `main.rs`. Keep the fixtures in the subdirectory and give the
test binary a different name, for example `tests/golden_contracts.rs`.

Golden tests are read-only by default. Blessing is an explicit, opt-in action behind one
environment variable:

```rust
fn assert_golden(name: &str, actual: &str) {
    // CARGO_MANIFEST_DIR is resolved at compile time, so the path does not depend on the
    // working directory of the test process.
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden").join(name);

    if std::env::var_os("BLESS_GOLDENS").is_some() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, actual).unwrap();
        return;
    }

    let expected = std::fs::read_to_string(&path).unwrap_or_else(|error| {
        panic!("missing golden {}: {error}. Re-run with BLESS_GOLDENS=1", path.display())
    });
    assert_eq!(actual, expected, "golden mismatch for {}", path.display());
}
```

```bash
# Read-only, the default in CI and in every normal run
cargo nextest run --locked -p <crate> --test golden_contracts

# Deliberate bless of a changed contract
BLESS_GOLDENS=1 cargo nextest run --locked -p <crate> --test golden_contracts
```

Rules for blessing:

1. Bless only when the contract change is intended.
2. Run `git diff` on the fixture files and read every changed line.
3. Explain the contract change in the commit message.
4. Never bless to make a red build green.

Scrub volatile fields before comparison. Timestamps, generated identifiers, ephemeral
ports, temporary paths, and host names make a golden fixture fail on the second run.
Replace them with deterministic placeholders.

## Subagent strategy

For a non-trivial feature, split the cycle across contexts so that the test does not
inherit the bias of the implementation you already planned.

1. **A subagent writes the failing test.** Give it the behavior and the public API only,
   not your implementation sketch.
2. **The main context implements.** Read the test the subagent wrote. Write the minimum
   code that makes it pass.
3. **The main context refactors.** Clean up the test and the implementation together.

This prevents the "write the test and the implementation in the same breath" anti-pattern,
where the test encodes the implementation you already wrote instead of the behavior the
caller needs.

## Rules

1. **Never skip RED.** Every test must fail before you write the implementation.
2. **One test at a time.** Do not start the next test until the current cycle is complete.
3. **Run format and clippy before every commit.** `--all-targets` covers test code too.
4. **Test and implementation land in one commit.** Never commit a test without its
   implementation, or an implementation without its test.
5. **Hand-written fakes only.** No mocking crate. Put shared fakes in one place.
6. **Fault queue for error paths.** Use `FaultSpec` plus `FaultQueue`, not ad-hoc error
   flags scattered over the fakes.
7. **Golden contracts are read-only by default.** Bless deliberately, review the diff,
   explain it in the commit message.
8. **`snake_case` test names that state the behavior**, not the method name.
9. **Prefer unit tests.** Escalate to integration or end-to-end only when the behavior
   needs real I/O or a real peer.
10. **Always pass `--locked`.** A test run that edits `Cargo.lock` proves nothing about CI.
11. **Delete no test to make a build green.** A failing test is information. Fix the code
    or fix the assertion, and say which one you did.

## Common mistakes

| Mistake | Fix |
|---|---|
| Adding a mocking crate | Write a `Fake*` type behind the trait, in the shared test-support module |
| Skipping RED | Run the test first. If it passes, the test does not cover your change. |
| Treating a compile error as RED | Add the minimal signature or `todo!()` stub, then let the assertion fail |
| Several behaviors in one test | Split into separate `#[test]` functions, one behavior each |
| `block_on` inside an async test | Use `#[tokio::test]`, and `start_paused = true` for time-dependent logic |
| `thread::sleep` to wait for async work | Synchronize with a `oneshot` channel |
| `#[should_panic]` without `expected` | Pin the panic message so an unrelated panic cannot pass the test |
| Blessing goldens without review | Run `git diff` on the fixture files before you commit |
| Volatile fields in a golden fixture | Scrub timestamps, identifiers, ports, and paths to placeholders |
| Testing private internals directly | Test through the public API. If you cannot reach it, add a seam trait. |
| Duplicated helpers in each test file | Move them to `tests/common/mod.rs` or the test-support module |
| Hard-coded ports or fixed temp paths | Bind port 0 and read back the assigned port. Use a unique directory per test. |
| `FaultScope::Persistent` when `OneShot` is enough | Default to `OneShot`. Use `Persistent` only for repeated-call scenarios. |
| Dropping `--locked` because the build failed | Fix the lock file in its own commit |
| Reproduction test deleted after the fix | Keep it. It is the regression guard. |

## Definition of done

Before you call a cycle complete, confirm all of the following:

- The test failed first, for the reason you predicted.
- The implementation contains no code that no test requires.
- `cargo nextest run --locked -p <crate>` is green for the crate you changed.
- `cargo test --locked --doc -p <crate>` is green when you changed a documented API.
- `cargo fmt --all -- --check` is clean.
- `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings` is clean.
- No `todo!()`, no `unimplemented!()`, no `#[ignore]` added to hide a failure.
- Changed golden fixtures are reviewed and explained.

## Related skills

- `rust-test-tools` — proptest, loom, cargo-mutants, cargo-fuzz, and golden-test tooling.
- `rust-lints` — the clippy lint set behind the LINT step.
- `cargo-workflows` — the full cargo command set and lockfile policy.
- `rust-panic-safety` — what may panic, and how to test panic behavior.
- `rust-debugging` — what to do when a test fails and you cannot see why.
- `rust-sanitizers-miri` — undefined behavior that a passing test suite will not report.
- `ffi-error-progress-cancel` — error, progress, and cancellation contracts across FFI.

## References

- `references/testing-anti-patterns.md` — test-double, async, golden, structural, and
  flaky-test anti-patterns, with a triage table.
- `references/fault-injection.md` — the full `FaultQueue` implementation, the outcome
  mapping table, and the scope rules.
