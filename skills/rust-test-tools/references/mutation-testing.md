# Mutation testing with cargo-mutants

Deep reference for the mutation-testing section of the `rust-test-tools` skill.

## What mutation testing reveals that coverage does not

Coverage tells you which lines execute during the tests. It does not tell you whether the
tests verify the behavior. A function with 100% coverage can have zero assertions.

Mutation testing injects small semantic changes (mutants). It flips operators, it
replaces return values, and it deletes calls. Then it reruns the test suite for each
mutant. If the tests still pass after a mutation, that mutant "survived". A survived
mutant means the tests execute the code but never check its correctness. Survived mutants
point directly at weak assertions, missing edge-case tests, and untested error paths.

## Running locally

```bash
cargo install cargo-mutants
```

Run each command from the repository root. If the Rust workspace is not at the repository
root, add `--dir <workspace-dir>`, or `--manifest-path <workspace-dir>/Cargo.toml` for
consistency with other Cargo commands.

### Full workspace run

```bash
cargo mutants \
  --test-tool nextest \
  --output target/
```

cargo-mutants copies the whole workspace tree to a temporary directory, then builds and
tests each mutant there. Expect a full run to take minutes to hours.

### Incremental run: only the lines that a diff changes

`--in-diff` takes a path to a diff **file**. It does not take a shell command.

```bash
# Uncommitted work.
git diff > /tmp/wip.diff
cargo mutants --test-tool nextest --in-diff /tmp/wip.diff --output target/

# The pull request against the base branch.
git diff origin/main...HEAD > /tmp/pr.diff
cargo mutants --test-tool nextest --in-diff /tmp/pr.diff --output target/
```

`--in-diff` generates mutants only for changed lines, so a focused pull request produces
10–50 mutants instead of thousands. Rules and limits:

- The diff must carry the `b/` prefix on the new filename, which is the `git diff`
  format, or no prefix at all.
- Changes to non-Rust files, and files that produce no mutants, are ignored.
- The diff is matched against the code under test, not against the test code. A diff that
  only edits tests produces no mutants, even when it removes real coverage.
- `--in-diff` runs after the other filters. `--in-diff` plus `--package foo` tests only
  the overlap.
- An incremental run is not a substitute for a full run. An edit in one region can break
  the coverage of a different region.

### Single package

```bash
cargo mutants --test-tool nextest --package <crate> --in-diff /tmp/pr.diff
```

Combine `--package` with `--in-diff` for the fastest feedback loop.

### Parallelism

`-j` / `--jobs` takes a job count. Start at `-j2` or `-j3`. Do not scale `-j` with the
core count: the Rust build and test tools already parallelize hard, and each job needs
its own target directory, which can cost 2 GB or more of temporary disk space. A high
job count also makes timeouts flaky, because each test run gets slower under load.

### Useful flags

| Flag | Purpose |
|------|---------|
| `--list` | Dry run. Print the mutants without running any test. |
| `--list --diff` | Print each mutant with the source diff it applies. |
| `--file <glob>` / `-f` | Mutate only functions in files that match the glob. |
| `--exclude <glob>` / `-e` | Exclude files that match the glob. |
| `--re <regex>` / `-F` | Only mutants whose full name matches the regex. |
| `--exclude-re <regex>` / `-E` | Drop mutants whose full name matches the regex. |
| `--in-diff <file>` | Only mutants on lines that the diff file changes. |
| `--test-tool nextest` | Use cargo-nextest as the test runner. |
| `--timeout <seconds>` | Fixed test timeout. Overrides the multiplier. |
| `--timeout-multiplier <N>` | Test timeout as a multiple of the baseline test time. |
| `--minimum-test-timeout <seconds>` | Floor for the computed test timeout. |
| `-j <N>` / `--jobs <N>` | Number of parallel mutant jobs. |
| `--output <dir>` | Parent directory for the `mutants.out` result directory. |
| `--config <file>` | Read the config from this file instead of the default path. |
| `--no-config` | Ignore the config file. |

The regex options match the full mutant name. That name contains the file path, the
trait and impl, the function name, and the replacement value, as `cargo mutants --list`
prints it. Anchor with `^` and `$` when you need a whole-name match.

## Configuration: .cargo/mutants.toml

cargo-mutants reads its config from `.cargo/mutants.toml` in the source tree root. Commit
that file, so that a developer can run `cargo mutants` with no extra options.

```toml
test_tool = "nextest"
timeout_multiplier = 5.0
minimum_test_timeout = 30
exclude_re = ["impl Debug", "impl Display", "::fmt"]
```

- `timeout_multiplier` — the test timeout as a multiple of the baseline test duration.
  The default is 5.0. Lower it to kill hangs sooner. Raise it when CI variability causes
  spurious timeouts. The multiplier has no effect when you pass `--timeout`, and it
  cannot be used with `--baseline=skip` or `--in-place`.
- `minimum_test_timeout` — a floor in seconds for the computed timeout. The default is
  20 seconds. Raise the floor on a fast suite that runs on a loaded CI machine.
- `exclude_re` and `examine_re` — lists of regular expressions over the full mutant name.
- `exclude_globs` and `examine_globs` — the same idea over file paths.

For scalar options the command line wins over the config file. For list options the two
sources are appended.

By default cargo-mutants picks packages with the same heuristics as other Cargo commands.
From the workspace root that means every workspace member is a mutation target. Prefer a
narrow name-level or file-level exclude over the removal of a whole package.

### Skip one item with an attribute

Use the attribute when the exclusion belongs to one function, not to a class of items.

```toml
# Cargo.toml — a normal dependency, not a dev-dependency.
[dependencies]
mutants = "0.0.3"
```

```rust
/// Returns true when the loop must stop.
#[cfg_attr(test, mutants::skip)] // A `false` return would hang the loop.
fn should_stop() -> bool {
    true
}
```

The `mutants` crate is tiny and the attribute emits no code. cargo-mutants does not
evaluate the `cfg_attr` condition; it honors the inner `mutants::skip` in every build.
Place the attribute on a function, on an `impl` block, or on a module. Always add a
comment that states why the item is skipped.

## Interpreting results

cargo-mutants creates a `mutants.out/` directory in the source tree root, or inside the
`--output` directory when you pass one. Each run renames an existing `mutants.out` to
`mutants.out.old`. Add `/mutants.out*` to `.gitignore`.

| File | Content |
|------|---------|
| `caught.txt` | Mutants that a test killed. Good. |
| `missed.txt` | Mutants that survived. These are the test gaps. |
| `timeout.txt` | Mutants that caused a hang or an infinite loop. |
| `unviable.txt` | Mutants that failed to compile. Not interesting. |
| `mutants.json` | Every generated mutant. Written before the tests start. |
| `outcomes.json` | Machine-readable full results plus summary counts. |
| `diff/` | One diff file per mutation, against the unmutated baseline. |
| `logs/` | One cargo log per mutation, plus the baseline log. |

The text files update while the run proceeds, so you can watch progress.

What each category means:

- **Caught** — a test failed. The suite covers this behavior adequately.
- **Missed** — every test passed in spite of the mutation. This is the actionable
  category. Each entry names the function and the change that no test detected.
- **Timeout** — the mutation caused a hang, usually in a loop or a retry path. This is
  usually not a test gap. Check for a missing timeout assertion.
- **Unviable** — the mutant did not compile. Ignore it. The type system prevented the
  mutation.

### Exit codes

Gate CI on the exit code, not on a parsed report.

| Code | Meaning |
|------|---------|
| 0 | Every viable mutant was caught. |
| 1 | Usage error, for example a bad command-line argument. |
| 2 | Some mutants survived. |
| 3 | Some tests timed out. |
| 4 | The baseline tests already fail or hang, so no mutant ran. |
| 5 | The new side of the `--in-diff` diff does not match the tree. |

Exit code 4 means your diagnosis stops here. Fix the normal test suite first.

## Triage workflow

1. Open `mutants.out/missed.txt`.
2. For each survived mutant, read the function and the mutation description. The matching
   `diff/` file shows the exact change.
3. Ask: "Must a test catch this?" If yes, write a targeted test.
4. If the mutation is in genuinely untestable code (FFI glue, logging), exclude it. Use
   `exclude_re` for a class of items and `#[mutants::skip]` for one item. Do not write a
   meaningless test.

Record the reason for every exclude. An undocumented exclude becomes permanent blindness.

## Writing mutation-resistant tests

### Assert specific values, not only "no panic"

```rust
// Weak: survives every mutation that changes the return value.
assert!(compute_ttl(input).is_ok());

// Strong: catches any change to the computed value.
assert_eq!(compute_ttl(input), Ok(Duration::from_secs(30)));
```

### Test boundary conditions

Mutants often flip `<` to `<=`, or `+1` to `-1`. Pin the boundaries on both sides.

```rust
#[test]
fn offset_boundary() {
    // Exactly at the limit: must succeed.
    assert!(validate_offset(MAX_OFFSET).is_ok());
    // One past the limit: must fail.
    assert!(validate_offset(MAX_OFFSET + 1).is_err());
}
```

### Cover error paths

Error branches often survive because no test reaches them. Write explicit tests for
malformed input, invalid state, and rejection paths.

### Assert side effects

If a function has a side effect (it increments a counter, it emits a metric, it writes a
record), assert that the effect happened. Otherwise the mutation that deletes the call
survives.

## Common false positives

Suppress these with `exclude_re` in `.cargo/mutants.toml`, or with `#[mutants::skip]`. Do
not write low-value tests for them.

- **`Display` and `Debug` impls** — a mutated format string is not a real bug.
- **Logging calls** — a changed argument to a `tracing::debug!` call does not affect
  correctness.
- **Unreachable branches** — `unreachable!()` in a match arm that the type system already
  guards.
- **Builder defaults** — the mutant survives only because every test overrides the field.

## CI workflow

Run mutation testing on a schedule, not on every pull request. A full run takes minutes to
hours.

```yaml
# .github/workflows/mutation-testing.yml — sketch
name: mutation-testing

on:
  schedule:
    - cron: "0 6 * * 1"   # weekly, Monday 06:00 UTC
  workflow_dispatch:
    inputs:
      packages:
        description: "Space-separated package names. Empty means all workspace packages."
        required: false
      in_diff:
        description: "true to mutate only the lines changed against main"
        required: false
        default: "false"

concurrency:
  group: mutation-testing-${{ github.ref }}
  cancel-in-progress: true

jobs:
  mutants:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - uses: taiki-e/install-action@v2
        with:
          tool: cargo-nextest,cargo-mutants
      - run: cargo mutants --test-tool nextest --output target/
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutants-output
          path: target/mutants.out/
          retention-days: 14
```

Key details:

- Pin the Rust toolchain in the workflow. Keep the pin in sync with `rust-toolchain.toml`.
- Install `cargo-nextest` and `cargo-mutants` from prebuilt binaries. A source install
  costs several minutes per run.
- Give the job an explicit timeout. A runaway mutant run can burn the whole CI budget.
- Upload the output directory as an artifact. The result files are the deliverable.
  Use `if: always()`, because a survived mutant makes the step exit with code 2.
- Use a concurrency group that cancels an in-progress run on the same ref.
- Discover the package list with `cargo metadata --locked` when a workflow input requests
  a subset. On a large workspace, rotate scheduled coverage over several shards so that
  each run stays inside the timeout.

Trigger a manual run from the command line:

```bash
gh workflow run mutation-testing.yml \
  -f packages="my-parser my-codec" \
  -f in_diff=true
```

## Optional: a wrapper script

On a workspace with many crates, a single wrapper script keeps CI and local runs
identical. Give it environment-variable inputs and pass extra arguments through to
`cargo mutants`:

```bash
# scripts/run-mutants.sh — pattern
#   MUTANTS_TEST_TOOL   test runner (default: nextest)
#   MUTANTS_PACKAGES    space-separated subset (default: all workspace packages)
#   MUTANTS_JOBS        parallel jobs (unset = cargo-mutants default)
# Extra CLI arguments, for example --in-diff, pass straight through.

bash scripts/run-mutants.sh                              # all crates
MUTANTS_PACKAGES="my-parser" bash scripts/run-mutants.sh # one crate
bash scripts/run-mutants.sh --in-diff /tmp/pr.diff       # incremental
MUTANTS_JOBS=2 bash scripts/run-mutants.sh               # limit parallelism
```

Filter the requested package subset against `cargo metadata --locked` inside the script.
A stale package name then fails fast instead of silently mutating nothing.
