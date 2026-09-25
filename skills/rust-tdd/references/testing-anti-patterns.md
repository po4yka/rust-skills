# Testing Anti-Patterns

Extended reference for the `rust-tdd` skill. Read this when you review a test suite that
somebody else wrote, or when you chase a flaky test. `SKILL.md` already covers fakes, panic
tests, async synchronization, and the blessing rules; this file adds the rest.

Contents: shared resources, design of the test body, golden fixtures, flaky-test triage.

## Shared resources

**Serialize tests that share a global resource.** Tests that bind a well-known port, write a
fixed path, or set a process environment variable must not run in parallel. The mechanism
depends on the runner:

- Under `cargo test`, all tests of one binary share one process. A `static` mutex, or a
  serialization attribute such as `#[serial]` from the `serial_test` crate, serializes them.
- Under cargo-nextest, each test runs in its own process. An in-process lock therefore
  serializes nothing. Use a nextest test group with one thread.

```toml
# .config/nextest.toml
[test-groups]
serial-resource = { max-threads = 1 }

[[profile.default.overrides]]
filter = 'test(/^shared_port_/)'
test-group = 'serial-resource'
```

Prefer to remove the shared resource. A test that binds port 0 and writes into its own
directory needs no group.

**Pass configuration as a parameter, not through the environment.** In edition 2024,
`std::env::set_var` and `std::env::remove_var` are `unsafe`: on non-Windows targets, a
concurrent environment read from outside `std::env` (libc, a C library, DNS lookup through
`ToSocketAddrs`) is a data race, and under `cargo test` other tests run on other threads. Do
not wrap the call in `unsafe` to make a test compile. To give a variable to a binary under
test, use `Command::env`.

**Bind ephemeral ports.** Bind port 0 and read back the assigned port. A hard-coded port fails
on CI when another job or another test holds it.

**Give each test its own directory.** Use a fresh temporary directory per test, or a unique
subdirectory of `env!("CARGO_TARGET_TMPDIR")`. Cargo sets that variable only when it compiles
integration tests and benchmarks. Cargo never cleans that directory, so a fixed subdirectory
keeps the files of the previous run. Remove the subdirectory at the start of the test, or use
a per-run temporary directory.

**Shut down fixtures explicitly.** Send a shutdown signal to a server or fixture task and
await its `JoinHandle` before the test returns. When a `#[tokio::test]` returns, the runtime
drops every remaining task at its current `.await`, so async cleanup such as a flush or a
graceful close never runs. A child process outlives the test: `std::process::Child` never
kills the process on drop, and tokio's `Child` does so only with `kill_on_drop(true)`.

**Commit proptest regression files.** When proptest finds a failing case, it writes the seed
to a regression file. For a test in `src/`, the file is under `proptest-regressions/` at the
crate root. For an integration test in `tests/`, it is `tests/<name>.proptest-regressions`.
Commit both kinds, and never add them to `.gitignore`. Without them the failure depends on
the random seed and disappears from CI. The `rust-test-tools` skill, when it is installed,
covers property testing in depth.

## Design of the test body

**No test-only public API.** Marking an item `pub` so that a test can reach it widens the
real contract for every consumer. Move the test into a `#[cfg(test)] mod tests` in the same
file, or introduce a seam: a trait, a constructor parameter, or a returned value. Never read
a private field through `unsafe` pointer casts. A test that depends on the internal layout
breaks on every rename and every field reorder.

**No conditional logic in a test.** An `if` or a loop in a test body means that the test
asserts different things in different runs. Split it into separate test functions, or drive
a table of cases in which every case asserts the same property.

**Prefer `expect` on the value under test.** `expect("<what should have happened>")` puts the
intent next to the error value in the failure report. A test that returns `Result` and uses
`?` reports the error without the line that produced it.

## Golden fixtures

**Correct fixture directory.** Keep fixtures in `tests/golden/` inside the crate that owns
the contract. A fixture in the wrong crate makes the test read a file that no change ever
updates, so the test passes forever and proves nothing.

**One fixture, one contract.** Do not concatenate several outputs into one large fixture. A
one-byte change then produces an unreadable diff, and reviewers approve it without reading.

## Flaky test triage

| Symptom | Likely cause | Action |
|---|---|---|
| Passes alone, fails in the suite | Shared mutable state, or a leaked thread or task | Fresh fake per test, await or abort spawned tasks, clear fault queues |
| Passes under cargo-nextest, fails under `cargo test` | Process-global state: a `static`, an environment variable, the current directory | Remove the shared state, or serialize the resource |
| Fails only on CI | A timing assumption, or a busy port | Remove sleeps, bind port 0, use paused time |
| Fails every second run | An unscrubbed volatile field in a golden fixture | Scrub the field. Do not bless. |
| Fails after an unrelated test is added | Test order dependency | Remove the shared state, or serialize the resource |
| Passes, but a `--no-capture` run shows a panic message | A spawned task panicked and nobody awaited its `JoinHandle` | Await the handle and check the result |
| Times out at once under paused time | A `timeout` around a wait on a real thread or real I/O; the paused clock jumps | Wait through `spawn_blocking`, or build the fake on tokio primitives |
| Passes, but the injected fault never fired | A wrong target variant, or a consumed `OneShot` | Assert that the queue is empty at the end |
| Hangs instead of failing | A missing wake, a fake that never releases, or a blocking call on the test runtime thread | Wrap the awaited task in `tokio::time::timeout`, and check the release channel |
