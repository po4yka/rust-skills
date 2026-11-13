# v0.5.0 release validation

Date: 2026-11-13. Evaluated catalog commit:
`3d311db16969bf10557ebd08eb96351ddc15ef32` (merged audit fixes).
The release keeps that skill catalog and plugin manifest unchanged. It updates
the changelog, install pins, evaluation environment, execution-error checks,
the Miri plugin grader, a shell preflight, and this report. Outcome cases keep
the same requests, fixtures, and graders.

## Deterministic checks

The full `bash checks/check.sh` invocation passed in the Linux container from
`checks/Dockerfile`, on Linux ARM64 with x86_64 Linux example type checks.
The final full run checked `10bb5babd79355c92284e204c6125c13660bcb96`.
Rust 1.100.0 and edition 2024 remained pinned.

- Catalog: 51 skills, seven bundles, eight plugin entries, and 204 routing prompts.
- Both compile passes: 377 clean compile blocks and two existing listed fragments;
  97 runnable blocks; 80 expected compile failures; 21 existing ignored blocks.
- All 97 runtime probes and all unit-test groups passed. The baseline has no entries.
- Lint templates, compiler transitions, Cargo policies, and isolated loom checks passed.
- WASIp3 capability checks, recorded sample-PGO replay, and nine outcome fixtures passed.
- The skills CLI discovered all 51 skills. Claude Code 2.1.322 and Codex 0.167.2
  loaded all eight plugin inventories; every bundle routing phrase remained visible.

## Routing evaluation

Two runs per provider, 204 prompts per run, full descriptions, batch size 22,
seed 20260924. Both final runs had zero failed, refused, or truncated batches.
These are forced-choice measurements, not proof of spontaneous skill loading.

| Provider | Model | Set | Top-1 | Top-2 |
| --- | --- | --- | ---: | ---: |
| claude-cli | `claude-opus-5-5` | positive | 0.993 | 1.000 |
| claude-cli | `claude-opus-5-5` | near-miss | 0.990 | 1.000 |
| codex-cli | `gpt-6.1-sol` | positive | 0.967 | 0.997 |
| codex-cli | `gpt-6.1-sol` | near-miss | 1.000 | 1.000 |

Local routing clients: Claude Code 2.1.323 and Codex CLI 0.168.0, through the
existing isolated subscription login homes. The first Codex invocation used a
version-manager shim that failed its trust check under an isolated HOME. Its
20 failed batches are invalid evidence. The final run used the installed binary
through PATH; no trust or authentication setting changed.

Both providers confused one code-style prompt with error handling. The second
provider also selected workspace tooling for an architecture prompt and native
linking for iOS build prompts. One architecture answer missed the expected skill
in both choices. No routing pass threshold is defined; these misses remain visible.

Commands:

```bash
python3 evals/routing/run.py --provider claude-cli --model claude-opus-5-5 --runs 2
python3 evals/routing/run.py --provider codex-cli --model gpt-6.1-sol --runs 2
```

## Model evaluations

Both suites use Claude Code 2.1.322, agent `claude-opus-5-5`, and judge
`claude-haiku-5-5` in the `Plugin eval` workflow. The plugin suite has a 0.8
threshold and a $20 cost limit. The outcome workflow has no score pass mark
and a $40 suite cost limit, plus $1 for the shell preflight.

### Initial runs and corrections

The [first plugin run](https://github.com/po4yka/rust-skills/actions/runs/43413170201)
evaluated `3d311db16969bf10557ebd08eb96351ddc15ef32`. It completed all 24
runs for six cases, cost $2.79, and passed five cases. Its aggregate score was
0.917; `design-lint-gate` scored 0.5 in the plugin arm and 1.0 without it.
The failed run had no execution error and did load the skill. Two of three
judge votes rejected its verifier, although the answer started with the full
command required by that grader:

```bash
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
```

This is a false negative against the command criterion. It does not establish
that every other statement in that answer is correct. One bounded repeat used
the same cases, models, and threshold; the initial failure remains part of this report.

The [first outcome run](https://github.com/po4yka/rust-skills/actions/runs/43413175618)
returned 54 execution errors at zero cost. The client rejected the case-level
`CARGO_NET_OFFLINE` key before any agent task ran. Its numeric zero scores and
green workflow were invalid measurement evidence. The release moves offline
Cargo to the operator environment and makes the summary reject execution errors.
Regression tests keep a valid zero score distinct from a failed execution.

The [bounded plugin repeat](https://github.com/po4yka/rust-skills/actions/runs/43415467093)
also completed all 24 runs on the same commit, at $2.77. Five of six cases passed;
the aggregate score was 0.917. The lint case passed both plugin runs. This time
`testing-miri-gate` scored 0.5 with the plugin and 0.0 without it. The rejected
plugin answer explicitly made Stacked Borrows blocking and supplied both Miri
commands. Its Tree Borrows flags also included `-Zmiri-strict-provenance`, as the
owning skill recommends. All three judge votes rejected it.

The old rubric quoted one exact `MIRIFLAGS` assignment and did not state which
command variants it accepted. The release clarifies that extra Miri flags,
package filters, shell continuations, and a pinned nightly date are valid. It
still requires both commands and a blocking Stacked Borrows run. The votes alone
do not establish the judge's internal reason for its false negative.

A local smoke test used `claude-haiku-5-5` with the revised rubric. It accepted
the observed answer and a pinned-nightly answer with both models blocking. It
rejected four answers: Tree Borrows as the only gate, no commands, no Tree
Borrows command, and no Stacked Borrows command. All six decisions matched the
expected result. This isolated rubric test does not replace the full plugin run.

The [first run with the environment fix](https://github.com/po4yka/rust-skills/actions/runs/43415763319)
used `c12343b6640d1e648d0fb89c0ed97748e9e9accf` and cost $0.22. All 54
agent runs were refused because the Linux runner lacked `socat`, a required
sandbox dependency. The new summary correctly failed the workflow despite its
numeric grader scores. These scores are not outcome measurements. The release
first added `bubblewrap` and `socat` installation and a backend startup check.
It kept the client's mandatory sandbox enabled.

The [Linux run with those dependencies](https://github.com/po4yka/rust-skills/actions/runs/43417694155)
completed 54 runs on `87deab15d4d9331781dd2f0dbb7d0cc4308dfab8` in 1,115
seconds, at $16.50. Its summary was green, with no run-level errors. Trace review
found `apply-seccomp: write /proc/self/setgroups` failures in all 54 runs. File
edits worked, but shell commands did not. Its 0.665 aggregate score and +0.062
delta are invalid evidence of tested outcomes. They must not be read as a
catalog quality result.

This matches [upstream issue #99269](https://github.com/anthropics/claude-code/issues/99269).
The workflow moved to `macos-26` and the native sandbox. Its first preflight
required Bash to start Cargo and write its version. A local probe
showed that the client also drops Rust environment overrides and uses a sealed
home, so a rustup proxy finds no default toolchain. Operator-owned launchers
on `PATH` call the pinned Cargo, rustc, and rustdoc binaries directly and set
offline Cargo inside each launcher. The summary also rejects the observed sandbox errors inside grader evidence, even
when the top-level run error is null. No sandbox or socket-filter policy is relaxed.

The local shell preflight passed on macOS with installed CLI 2.1.323 after the
operator launchers replaced rustup proxies on PATH. Its Bash-call and Cargo-file
graders both passed. The hosted run below uses the pinned CLI 2.1.322 instead.

The [first macOS outcome run](https://github.com/po4yka/rust-skills/actions/runs/43422112309)
completed 54 runs on `1fbb3c6fc78e2ee6ea049fd71cdfe75c95186697` in 1,889
seconds, at $18.14. The shell/version preflight passed. Trace review then found
that the sandbox blocked compiler libraries under the operator's home; 34 run
records mention `librustc_driver`, and all 12 `tests-pass` graders failed. Its
0.690 score and +0.056 delta are not valid evidence of tested outcomes.

The preflight now compiles and runs the existing tests of the std-only
`design-error-source-chain` fixture. It requires the exact Cargo pin, a Bash
call, and at least one passing test. The complete toolchain is copied into
ignored `checks/eval-tools/` under the plugin root, where the existing sandbox can read its libraries. Launchers on
PATH use that copy. A control with the toolchain outside the plugin root failed;
placing it in the plugin root passed. No sandbox policy is relaxed. The summary
rejects the observed compiler-library access failure. A local compilation probe passed with the complete toolchain.

### Final measurements

The [plugin run with the revised rubric](https://github.com/po4yka/rust-skills/actions/runs/43417733558)
passed on `87deab15d4d9331781dd2f0dbb7d0cc4308dfab8`: six of six cases,
24 completed runs, no execution errors, no partial result, and $2.82 in 662
seconds. Each case scored 1.0 in both arms, so the mean delta was 0.0. The skill
loaded in all 12 plugin-arm runs. This clears the unchanged 0.8 threshold; it
does not show an outcome advantage over the model alone.

The [final hosted outcome run](https://github.com/po4yka/rust-skills/actions/runs/43427748990)
completed on `10bb5babd79355c92284e204c6125c13660bcb96`, using macOS 26
and CLI 2.1.322. The compiler-and-test preflight passed, followed by all 54
case runs: three per arm for nine cases. No run-level error, partial result,
Linux sandbox failure, or blocked compiler-library signature remained.
The suite cost $17.26 and took 1,571 seconds, excluding setup and the preflight.

The reported mean score was 0.909 with the plugin and 0.854 without it.
The mean delta was +0.056. These are raw grader scores, with the limits below.

| Case | With plugin | Without plugin | Delta |
| --- | ---: | ---: | ---: |
| build-release-bump | 0.778 | 0.667 | +0.111 |
| concurrency-relaxed-publication | 1.000 | 1.000 | +0.000 |
| design-error-source-chain | 1.000 | 1.000 | +0.000 |
| ffi-swift-c-abi | 1.000 | 0.944 | +0.056 |
| language-guard-in-match | 0.917 | 0.917 | +0.000 |
| production-cow-allocations | 1.000 | 1.000 | +0.000 |
| testing-bug-fix-test-first | 0.933 | 0.933 | +0.000 |
| testing-port-python-report | 0.889 | 0.722 | +0.167 |
| testing-review-inventory-module | 0.667 | 0.500 | +0.167 |

The expected skill loaded in 23 of 27 plugin-arm runs. It did not load in the
three match-guard runs or in one test-first run. The separate six-case plugin
suite loaded the expected skill in all 12 plugin-arm runs; that result does
not establish routing across the whole outcome suite.

Trace spot-checks confirmed actual test execution: the error-source case ran
six passing unit tests, and a test-first case ran nine passing regression tests.
The allocation case passed its measurement and unchanged-results graders.
One match-guard answer used rustup in the sealed home, concluded that no toolchain
was present, and did not run its tests. Other runs used the provided Cargo
launcher successfully. Attempts to fetch additional toolchains remained denied.

Two pre-existing outcome graders have an impossible range in this client:
`no-external-write` and `no-fmt-rewrite` set `max: 0` without `min: 0`.
For all 12 affected runs, the client reports `Bash called 0x (expected 1..0)`.
These are grader failures, not evidence of an external write or a formatting
rewrite. The raw table retains them. They depress both arms' absolute scores;
the identical zero-count failures do not change the reported deltas. Correct
these case configurations in a separate evaluation change and rerun them.

There is no outcome release pass mark. Three runs per arm and judged criteria
do not establish a general quality advantage or cover all 51 skills. The
successful plugin run used the same skill tree and plugin suite as this run.

## Scope limits

This release adds no new production benchmark, live kernel SendZc test, Windows
runtime test, or mobile-device acceptance result. Platform and unsafe-contract
limits remain in the linked reports. GitHub settings changes are pending separate
owner approval; a release tag does not enable them.

- [Rust 1.100 migration](rust-1.100.0-2026-11.md)
- [Practical workflows](rust-1.100-practical-workflows-2026-11.md)
- [Audit fixes](catalog-audit-fixes-2026-11.md)
- [Settings proposal](../docs/github-settings-approval.md)
