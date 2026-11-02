# Routing fix, 2026-11

Measured by this repository on 2026-11-02. It tests a change of four descriptions against the
routing misses of `research/outcome-baseline-2026-11.md`, on the same cases, agents, and runner.

## The change

The baseline showed Claude Code loading the skill that owns a case in 10 of 18 runs. Three cases
caused the misses:

| Case | Owning skill | Claude, baseline | Cause in the descriptions |
| --- | --- | ---: | --- |
| ffi-swift-c-abi | rust-swift-ffi | 1/3 | Only design terms; no symptom of a broken Swift boundary |
| production-cow-allocations | rust-copy-on-write | 0/3 (rust-hot-path 3/3) | `rust-copy-on-write` itself sent every profiled allocation site to `rust-hot-path` |
| language-guard-in-match | rust-borrow-semantics | 0/3 | Only the mechanism ("drop scope of a temporary or lock guard"), not the hang a user sees |

Each description now starts with the symptom that a user reports. The copy-on-write and hot-path
boundary moved to "input that most calls return unchanged", and a negative routing case keeps that
phrase out of `rust-hot-path`. Words that are not routing phrases were cut to stay inside the
description ratchet; the total fell from 22,304 to 22,295 characters.

## Method

- Catalog snapshot `c9a9a7b`; runner `evals/outcome/cross_agent.py` at the same commit.
- Claude Code 2.1.316 with `claude-opus-5-5`; Codex CLI 0.166.0 with the default model of the
  ChatGPT login. Subscription logins in isolated homes, as in the baseline.
- The skills arms only (`--configs claude-skills,codex-skills`), on the three cases, three runs
  each: 18 runs. The no-skill arms do not read descriptions, so the baseline still covers them.
- The metric is routing: the owning skill appears among the skills that a run loaded. The runs
  were not graded; the outcome scores of these cases were at or near the ceiling in every arm.
- The probe passed twice before the runs (see Isolation).

## Result

Owning skill loaded:

| Case | Claude, baseline | Claude, after | Codex, baseline | Codex, after |
| --- | ---: | ---: | ---: | ---: |
| ffi-swift-c-abi | 1/3 | 3/3 | 3/3 | 3/3 |
| production-cow-allocations | 0/3 | 3/3 | 3/3 | 3/3 |
| language-guard-in-match | 0/3 | 0/3 | 2/3 | 3/3 |
| **Total** | **1/9** | **6/9** | **8/9** | **9/9** |

Claude no longer loads `rust-hot-path` for the copy-on-write case. Codex now also loads a related
skill in most runs (`rust-panic-safety` and `rust-unsafe` for the FFI case, `rust-unsafe` for the
copy-on-write case); the owning skill is always among them.

## The case that did not move

In `language-guard-in-match`, Claude loads no skill at all, before and after. It runs one
command, reads `src/lib.rs`, sees the guard held through the `match`, and fixes it in 23 to 36
seconds. The model knows this rule, and nothing in the task makes it look for help, so no
description can route it. It still fixed the bug in every baseline run (12 of 12 graders). Two
options remain, and neither is in this change: accept that a skill is not loaded when the model
needs no help, or reach the rule from a skill that the task does load, such as
`rust-compiler-errors` or `rust-lints` (`clippy::significant_drop_in_scrutinee`).

## Isolation

The probe refused this measurement twice before it passed, and each refusal found a leak that a
plain run would have hidden:

1. The ChatGPT login had prefetched about 50 curated plugins (build-ios-apps, slack, github,
   work-pets, ...) into the Codex login home, and Codex listed their skills in both arms. Every
   Codex run now disables `plugins`, `remote_plugin`, `plugin_discovery_prefetch`, and
   `skill_search`.
2. The claude.ai account syncs its plugins into the Claude login home on its own schedule; the
   second probe saw `design@synced` in one arm only. The login home's `settings.json` now sets
   `syncClaudeAiPlugins` and `syncClaudeAiSkills` to false, and `preflight` requires both.

Effect on the baseline: the Codex plugin cache appeared when the baseline run started, so its
skills may have been listed during the baseline Codex runs. No baseline Codex run read a file
from that cache, and both Codex arms would have seen the same list. The Claude baseline probe
passed twice with the synced plugins turned off.

## What this does not prove

- Anything beyond these three cases and two agents. `evals/routing/` measures selection over the
  whole catalog; it needs an API key and was not run for this change.
- That the change keeps every other routing decision. The routing-case and negative-case lints
  pass, and Codex shows every routing phrase of every bundle, but no agent ran the other cases.
- Stability: three runs per case and agent.

## Raw data

`/Users/Shared/rust-skills-evals/routing-2026-11-02/` on the machine that ran it; not committed.
