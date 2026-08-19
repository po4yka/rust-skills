# Testing Anti-Patterns

Extended reference for the `rust-tdd` skill. Read this when you diagnose test quality
problems, review a suite that somebody else wrote, or chase a flaky test.

## Test double anti-patterns

**No mocking crate.** Write fakes by hand. A mocking crate adds implicit behavior that no
reader of the test can see, makes tests brittle to harmless refactors, and hides design
problems. When a fake is painful to write, the seam is wrong. Change the trait, do not
reach for a framework.

**Fresh fake per test.** Never share mutable fake state between test functions. Construct
the fake inside the test function, or in a helper that returns a new instance. Shared state
plus parallel execution produces failures that depend on test order.

**Test the public API, not the internals.** If a test can only observe the behavior by
reading a private field, the design needs a seam — a trait, a constructor parameter, or a
returned value. Do not make an item `pub` only for a test, and never reach into a type with
`unsafe` pointer casts to inspect it. A test that depends on the internal layout breaks on
every rename and every field reorder.

**Do not assert on the fake alone.** A test that only checks `fake.calls == 1` proves that
the code called something, not that the behavior is right. Assert the observable result
first, then the interaction.

**Scope discipline in the fault queue.** Default to `FaultScope::OneShot`. Use
`Persistent` only for repeated-call scenarios such as retry or polling. A `Persistent`
fault that is never cleared causes failures in later tests when a fake is accidentally
shared. See `fault-injection.md` for the outcome mapping table.

## Async test anti-patterns

**Use `#[tokio::test]`, not a manual `block_on` in the test body.** A blocking entry point
inside the test hides the real scheduling. It masks the timing bugs that the test exists to
find.

**Do not sleep to synchronize.** `thread::sleep` and `tokio::time::sleep` as a
synchronization tool produce a suite that is slow when it passes and flaky when it fails.
Synchronize with a channel.

**Gate the fake for intermediate state.** When you must assert state while an operation is
in flight, block inside the fake with two `oneshot` channels — one that signals that the
fake was reached, one that releases it.

```rust
let (started_tx, started_rx) = oneshot::channel();
let (release_tx, release_rx) = oneshot::channel();
let transport = Arc::new(FakeTransport::gated(started_tx, release_rx));

let task = tokio::spawn({
    let service = Arc::clone(&service);
    async move { service.start().await }
});

started_rx.await.expect("start was never called");
assert_eq!(service.state(), State::Starting);

release_tx.send(()).expect("task dropped the release channel");
task.await.expect("task panicked").expect("start must succeed");
```

**Paused time for time-dependent logic.** `#[tokio::test(start_paused = true)]` lets the
runtime auto-advance virtual time, so a backoff test finishes in milliseconds instead of
seconds and does not depend on machine load.

**Clean up the harness.** Abort or await every `JoinHandle` the test spawned, and clear the
fault queue. A leaked task keeps running under the next test and produces a failure with a
stack trace that points at innocent code.

**Do not swallow a task panic.** `task.await` returns `Result<T, JoinError>`. Unwrap it
with a message, or the panic inside the task turns into a silent pass.

## Golden contract anti-patterns

**Scrub volatile fields.** Timestamps, generated identifiers, ephemeral port numbers,
temporary directory paths, host names, and archive file names must be replaced with
deterministic placeholders before comparison. An unscrubbed field makes the fixture fail on
the second run, and the usual reaction — blessing again — destroys the value of the test.

**Review before you bless.** Never set the bless environment variable and commit without
reading the diff. A golden contract is a compatibility boundary. An accidental change
breaks the consumer on the other side, and the test that should have caught it is the test
you just overwrote.

**Bless is not a fix.** If a golden fails and you did not intend a contract change, the
production code changed behavior. Find out why. Do not bless.

**Correct fixture directory.** Keep fixtures in `tests/golden/` inside the crate that owns
the contract. A fixture in the wrong crate makes the test read a file that no change ever
updates, so the test passes forever and proves nothing.

**One fixture, one contract.** Do not concatenate several outputs into one large fixture. A
single-byte change then produces an unreadable diff, and reviewers approve it without
reading.

## Rust test anti-patterns

**Serialize tests that share a global resource.** Integration tests that bind a well-known
port, write a fixed path, or set a process environment variable must not run in parallel.
Parallel execution produces port conflicts and order-dependent failures. The correct
mechanism depends on the runner:

- Under `cargo test`, all tests of one binary share one process. A `static` mutex, or a
  serialization attribute such as `#[serial]` from the `serial_test` crate, serializes
  them.
- Under `cargo nextest`, each test runs in its own process. An in-process lock therefore
  serializes nothing. Use a nextest test group instead, and give the group one thread.

```toml
# .config/nextest.toml
[test-groups]
serial-resource = { max-threads = 1 }

[[profile.default.overrides]]
filter = 'test(/^shared_port_/)'
test-group = 'serial-resource'
```

Prefer removing the shared resource over serializing access to it. A test that binds port 0
and writes into its own temporary directory needs no group at all.

**Bind ephemeral ports.** Always bind to port 0 and read back the assigned port. A
hard-coded port fails on CI when another job or another test already holds it.

**Manage the runtime explicitly for fixture lifecycles.** When a test starts an external
fixture process or a server task, build the runtime explicitly and control the startup and
shutdown order. The default `#[tokio::test]` runtime is fine for pure async logic, but it
gives you no hook to guarantee that the fixture is ready before the first request, or torn
down after the last one.

**Commit proptest regression files.** When `proptest` finds a failing case, it writes the
seed to a regression file next to the test. Commit that file. Without it the same failure
depends on the random seed and disappears from CI. See the `rust-test-tools` skill for
property testing in depth.

**Pin the panic message.** `#[should_panic]` without `expected = "..."` passes on any
panic, including an unrelated `unwrap()` in the setup lines of the same test.

**Do not use `unwrap()` on the assertion path.** Use `expect("what should have happened")`.
A bare `unwrap()` failure tells the reader the line number and nothing else.

**`--locked` in every command.** A test run that silently updates `Cargo.lock` tested a
dependency set that CI will not use.

**Do not add `#[ignore]` to a failing test.** An ignored test is a deleted test with extra
steps. Fix it, or delete it and say so.

## Structural anti-patterns

**Shared helpers in one place.** Put shared fakes and helpers in a `#[cfg(test)]`
test-support module, in `tests/common/mod.rs` for integration tests, or in a small
dev-dependency crate when several crates need them. Helper logic copied into each test file
drifts, and the copies stop agreeing about what the fake does.

**No test-only public API.** Marking an item `pub` so a test can reach it widens the real
contract for every consumer. Move the test into a `#[cfg(test)] mod tests` in the same
file, or introduce a seam.

**Unit test when possible.** Integration and end-to-end tests are slower, flakier, and
harder to debug. Escalate only when the behavior genuinely needs real I/O, a real peer, or
a real host runtime. Most logic can be tested at the unit level behind a fake.

**One behavior per test.** A test function should verify one behavior. Several unrelated
assertions in one function make the failure ambiguous: you cannot tell which behavior broke
without reading the whole body. Setup assertions that guard the preconditions are fine —
unrelated behavior assertions are not.

**No conditional logic in a test.** An `if` or a loop in a test body means the test asserts
different things in different runs. Split it into separate test functions, or drive it with
a table of cases where every case asserts the same property.

**Name the behavior.** `test_start` tells a reviewer nothing when it fails on CI.
`start_returns_error_when_transport_is_already_running` tells them what broke before they
open the file.

## Flaky test triage

| Symptom | Likely cause | Action |
|---|---|---|
| Passes alone, fails in the suite | Shared mutable state, or a leaked task | Fresh fake per test, abort spawned tasks, clear fault queues |
| Fails only on CI | Timing assumption, or a busy port | Remove sleeps, bind port 0, use paused time |
| Fails every second run | An unscrubbed volatile field in a golden fixture | Scrub the field, do not bless |
| Fails after an unrelated test is added | Test order dependency | Remove the shared state, or serialize the resource |
| Passes but the injected fault never fired | Wrong target variant, or a consumed `OneShot` | Assert that the queue is empty at the end |
| Hangs instead of failing | A missing wake, or a fake that never releases | Add a timeout around the awaited task, and check the release channel |
