# Plugin evaluation, 2026-11

Measured by this repository on 2026-11-02. It is the evaluation that `docs/releasing.md` requires
before the `v0.3.0` tag. It ran the `evals/plugin/` suite in the `Plugin eval` workflow, on an
API key.

## Setup

| Item | Value |
| --- | --- |
| Catalog commit | `5a24304`: `main` at `ab10b0b` plus a changelog edit; 46 skills, #20 included |
| Workflow run | [41480030417](https://github.com/po4yka/rust-skills/actions/runs/41480030417) |
| Client | Claude Code 2.1.316 |
| Agent model | `claude-opus-5-5` |
| Judge model | `claude-haiku-5-5` |
| Plugin | `rust-skills`, the full catalog, from the manifest that the workflow writes |
| Ablation | `with-without`: each case also runs with no plugin |
| Runs | 6 cases, 2 runs per arm, 24 runs |
| Threshold | 0.8 per case |
| Cost and time | $2.87, 653 s |

## Results

`skill-fired` is an indicator, not part of the score: the arm without the plugin cannot load a
skill. The score is the `cites-verifier` rubric, which passes when the answer gives the verifier
command that the owning skill names.

| Case | Owning skill | Skill fired | Score with plugin | Score without plugin | Delta |
| --- | --- | ---: | ---: | ---: | ---: |
| build-new-dependency | rust-security | 2/2 | 1.00 | 1.00 | 0.00 |
| concurrency-guard-across-await | rust-async-internals | 2/2 | 1.00 | 1.00 | 0.00 |
| ffi-unsatisfied-link | rust-jni | 2/2 | 1.00 | 1.00 | 0.00 |
| language-lint-gate | rust-lints | 2/2 | 1.00 | 1.00 | 0.00 |
| production-flamegraph-symbols | rust-performance | 2/2 | 1.00 | 1.00 | 0.00 |
| testing-miri-gate | rust-sanitizers-miri | 2/2 | 1.00 | 1.00 | 0.00 |
| All | | 12/12 | 1.00 | 1.00 | 0.00 |

All six cases pass the threshold. The job passed.

## What the result shows

- Routing works on this client and model. A natural request that names no skill loaded the
  owning skill in all 12 runs with the plugin.
- The verifier rubric is at its ceiling without the plugin. The model alone cited the verifier in
  12 of 12 runs, so this suite cannot show what the plugin adds to the answer. It works as a
  routing check and as a check that the skill does not make the answer worse.
- The arm with the plugin takes more turns: 3 to 6 against 1 to 2. The extra turns are the skill
  loads.

## Earlier runs

| Run | Catalog | Plugin loaded | Skill fired | With | Without | Use |
| --- | --- | --- | ---: | ---: | ---: | --- |
| [41471337092](https://github.com/po4yka/rust-skills/actions/runs/41471337092) | `4115a45`, 45 skills | no | 0/12 | 0.46 | - | Invalid |
| [41476487727](https://github.com/po4yka/rust-skills/actions/runs/41476487727) | `a7ae986`, 45 skills | yes | 12/12 | 1.00 | 0.92 | Superseded |

- **41471337092 is not a result.** It loaded no plugin, and its ablation was `none`. The
  repository had no root manifest after #11 removed `.claude-plugin/plugin.json` for Codex, and
  `claude plugin eval .` loads a plugin only from a manifest at the target. #21 fixed the
  workflow: it now writes a manifest in its own checkout and fails when a result names no plugin.
  No other `Plugin eval` result after #11 is recorded.
- **41476487727 ran before #20 merged,** so it did not see `rust-review` or the ten shorter
  descriptions. Its one difference between the arms was a single run without the plugin in
  `testing-miri-gate` that gave no Miri command. The run above did not repeat that difference, so
  read it as noise at two runs per arm.

## What this does not prove

- Behavior on Codex, Cursor, or another client, or on another model.
- Behavior with a bundle plugin. The suite loads the full catalog, so it measures the full skill
  listing.
- That a skill improves the answer. The `evals/outcome/` suite measures the work itself;
  `research/outcome-baseline-2026-11.md` and `research/review-and-routing-2026-11.md` have its
  results. It did not run for this tag.
- Routing for `rust-port` or `rust-review`. No case of this suite targets them;
  `research/review-and-routing-2026-11.md` has their routing results.
- A stable estimate. Each arm has two runs per case.
