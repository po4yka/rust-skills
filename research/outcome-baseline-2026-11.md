# Outcome baseline, 2026-11

Measured by this repository on 2026-11-02. It is the first run of the `evals/outcome/` suite and
the baseline that later catalog changes compare against. It was run with
`evals/outcome/cross_agent.py`, on subscription logins, not on API keys.

## Setup

| Item | Value |
| --- | --- |
| Catalog snapshot | `8a82b15` (all 44 skills) |
| Runner | `evals/outcome/cross_agent.py` at `51de962`, plus the bounded-diff fix of this commit |
| Claude Code | 2.1.316, model `claude-opus-5-5`, claude.ai subscription login |
| Codex CLI | 0.166.0, the default model of the ChatGPT login (the CLI does not report it) |
| Judge | `claude-opus-5-5`, one call per run, blind labels |
| Toolchain | Rust 1.99.1 |
| Runs | 6 cases x 3 runs x 4 configurations = 72 agent runs, 72 judged runs |
| Isolation | separate login homes; probe passed twice before the run (see below) |

Configurations: `claude-skills` (catalog through `--plugin-dir`), `claude-none`, `codex-skills`
(catalog in `$HOME/.agents/skills`), `codex-none`. Every run used the same prompt. All 72 runs
ended with a final answer: no timeout, no error.

The probe turned off two plugins that the Claude account synced into the login home
(`design@synced`, `engineering@synced`). In the first probe they appeared in one Claude arm only.
After that, both Claude arms saw the same 40 built-in and account skills, and both Codex arms
saw the same 4 built-in skills.

## Result

Scored graders passed (the `skill-fired` indicator is not scored):

| Case | claude-skills | claude-none | codex-skills | codex-none |
| --- | ---: | ---: | ---: | ---: |
| build-release-bump | 17/18 | 15/18 | 15/18 | 15/18 |
| concurrency-relaxed-publication | 12/12 | 11/12 | 9/12 | 10/12 |
| ffi-swift-c-abi | 13/18 | 14/18 | 15/18 | 12/18 |
| language-guard-in-match | 12/12 | 12/12 | 11/12 | 12/12 |
| production-cow-allocations | 9/9 | 9/9 | 9/9 | 9/9 |
| testing-bug-fix-test-first | 11/12 | 12/12 | 9/12 | 9/12 |
| **Total** | **74/81** | **73/81** | **68/81** | **67/81** |
| Total without `owned-name-with-release` (see defects) | 74/78 | 72/78 | 68/78 | 67/78 |

Graders that separate the arms:

| Grader | claude-skills | claude-none | codex-skills | codex-none |
| --- | ---: | ---: | ---: | ---: |
| build-release-bump / names-the-api-diff | 3/3 | 0/3 | 0/3 | 0/3 |
| concurrency-relaxed-publication / names-the-verifier | 3/3 | 2/3 | 0/3 | 1/3 |
| ffi-swift-c-abi / honest-boundary-evidence | 2/3 | 3/3 | 3/3 | 0/3 |
| ffi-swift-c-abi / no-panic-crosses-an-export | 2/3 | 1/3 | 3/3 | 3/3 |
| testing-bug-fix-test-first / regression-tests-kept | 3/3 | 3/3 | 0/3 | 0/3 |
| build-release-bump / non-exhaustive-is-not-an-escape | 2/3 | 3/3 | 3/3 | 3/3 |
| testing-bug-fix-test-first / red-before-fix | 2/3 | 3/3 | 3/3 | 3/3 |

The other 20 graders gave the same count in every arm, most of them 3/3.

Routing, the owning skill loaded in the skills arm:

| Case | claude-skills | codex-skills |
| --- | ---: | ---: |
| build-release-bump | 3/3 | 3/3 |
| concurrency-relaxed-publication | 3/3 | 3/3 |
| ffi-swift-c-abi | 1/3 | 3/3 |
| language-guard-in-match | 0/3 | 2/3 (once `rust-pattern-semantics`) |
| production-cow-allocations | 0/3 (`rust-hot-path` 3/3) | 3/3 |
| testing-bug-fix-test-first | 3/3 | 3/3 |
| **Total** | **10/18** | **17/18** |

Median run time: claude-skills 79 s, claude-none 54 s, codex-skills 54 s, codex-none 44 s.

## Findings

1. The catalog adds about one grader in 80 for each agent on this suite. Both agents already
   solve most planted defects without a skill: four of six cases score full or almost full in
   every arm. The suite has a ceiling problem, not only the catalog.
2. The clearest effect of a skill is a verifier that the model does not know to name. With
   `rust-crate-release`, Claude named `cargo semver-checks` against the v1.4.2 baseline in 3 of 3
   runs; no other arm did in any run.
3. Codex used the skills it loaded. In one `memory-model` run it turned off the offline setting,
   fetched `loom`, wrote a loom model, and showed that the model catches the stale read with the
   old orderings. The grader did not credit it (defect 2).
4. Claude does not load the owning skill reliably: 10 of 18 runs, against 17 of 18 for Codex.
   It never loaded `rust-borrow-semantics` for a `match` scrutinee deadlock, and it chose
   `rust-hot-path` over `rust-copy-on-write` for "the heap profile names an allocation site".
   These are routing problems in the descriptions, and `evals/routing/` does not show them,
   because there the question forces a choice.
5. A skills arm can score lower on single graders (`non-exhaustive-is-not-an-escape`,
   `red-before-fix`, one `honest-boundary-evidence`). Each is one run of three. The judge's
   evidence names a real fault in each, but three runs cannot separate a skill effect from noise.

## Defects found in the suite

1. `ffi-swift-c-abi / owned-name-with-release` is a false negative. In 11 of 12 runs, across all
   arms, the agent stored the name as a `CString` in the handle and returned a pointer that is
   valid until `tally_free`. That design is sound for a handle-scoped name, but the criteria
   accept only an `into_raw` handoff with a release function or a caller buffer. The judge
   passed the same design once. Fix the criteria before the next run; the totals above also show
   the result without it.
2. `concurrency-relaxed-publication / names-the-verifier` and
   `testing-bug-fix-test-first / regression-tests-kept` reward a sentence in the final answer
   over the action. Codex ran loom (finding 3) and failed for not writing "x86 proves nothing";
   Codex fixed the bug test first and failed for not quoting the red line. Accept an executed
   check, with its result, as the evidence.
3. `production-cow-allocations` scores 9/9 in every arm and does not discriminate. Make the
   defect harder to find, or drop the case's weight in the comparison.

## Runner defects found during the run

- One Codex run copied a cargo registry into its workspace (1.7 GB). The workspace diff for the
  judge grew to 1.8 GB and stalled grading. The diff is now bounded: source files first, binary
  and large files counted, a size budget. The grades of the other 71 runs are unaffected; their
  diffs are identical under both versions.
- The Codex `workspace-write` sandbox did not stop network access: one run downloaded crates
  after it set `CARGO_NET_OFFLINE=false`. The suite's offline setting is a default, not a wall.

## What this baseline does not prove

- Anything about a single grader difference: three runs per arm.
- That the judge is unbiased. It is a Claude model; it saw no agent or arm label, but the style of
  an answer can still hint at its agent. A sample of the verdicts above was read against the
  files and the traces; the defects listed are what that reading found.
- The Codex model ID: the CLI did not report it.
- Behavior on another client, model, or effort level.

## Raw data

The runs, traces, grades, and `report.md` are in
`/Users/Shared/rust-skills-evals/outcome-2026-11-02/` on the machine that ran them. They are not
committed: they hold full agent transcripts.
