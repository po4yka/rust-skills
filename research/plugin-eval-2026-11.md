# Plugin evaluation, 2026-11

Measured by this repository on 2026-11-02. It is the evaluation that `docs/releasing.md` requires
before the `v0.3.0` tag. It ran the `evals/plugin/` suite in the `Plugin eval` workflow, on an
API key.

## Setup

| Item | Value |
| --- | --- |
| Catalog commit | `a7ae986` (release branch of `v0.3.0`, 45 skills) |
| Workflow run | [41476487727](https://github.com/po4yka/rust-skills/actions/runs/41476487727) |
| Client | Claude Code 2.1.316 |
| Agent model | `claude-opus-5-5` |
| Judge model | `claude-haiku-5-5` |
| Plugin | `rust-skills`, the full catalog, from the manifest that the workflow writes |
| Ablation | `with-without`: each case also runs with no plugin |
| Runs | 6 cases, 2 runs per arm, 24 runs |
| Threshold | 0.8 per case |
| Cost and time | $2.81, 639 s |

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
| testing-miri-gate | rust-sanitizers-miri | 2/2 | 1.00 | 0.50 | 0.50 |
| All | | 12/12 | 1.00 | 0.92 | 0.08 |

All six cases pass the threshold. The job passed.

## What the result shows

- Routing works on this client and model. A natural request that names no skill loaded the
  owning skill in all 12 runs with the plugin.
- The verifier rubric is near its ceiling without the plugin. The model alone cites the verifier
  in 11 of 12 runs, so the suite shows a delta in one case only: `testing-miri-gate`, where one
  run without the plugin gave no Miri command. Two runs per arm cannot show a smaller effect.
- The arm with the plugin takes more turns: 3 to 5 against 1 to 2. The extra turns are the skill
  loads.

## An invalid run before this one

[Run 41471337092](https://github.com/po4yka/rust-skills/actions/runs/41471337092), on the
release commit `4115a45`, loaded no plugin and is not a result:

- the result names no plugin, and the ablation is `none`;
- no skill fired in its 12 runs;
- it scored 0.46 and failed the threshold.

The repository had no root manifest after #11 removed `.claude-plugin/plugin.json` for Codex, and
`claude plugin eval .` loads a plugin only from a manifest at the target. #21 fixed the workflow:
it now writes a manifest in its own checkout and fails when a result names no plugin. No other
`Plugin eval` result after #11 is recorded.

## What this does not prove

- Behavior on Codex, Cursor, or another client, or on another model.
- Behavior with a bundle plugin. The suite loads the full catalog, so it measures the full skill
  listing.
- That the skill improves the answer beyond the verifier citation. The `evals/outcome/` suite
  measures the work itself; `research/outcome-baseline-2026-11.md` has its baseline. It did not
  run for this tag.
- A stable estimate. Each arm has two runs per case.
