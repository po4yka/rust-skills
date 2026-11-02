# rust-review and subscription routing, 2026-11

Measured by this repository on 2026-11-02, at catalog commit `2cf8285` (46 skills). Two
measurements: the first run of the outcome case `testing-review-inventory-module`, and the first
run of the routing evaluation on subscription logins (`evals/routing/run.py` with `claude-cli` and
`codex-cli`).

## Setup

| Item | Value |
| --- | --- |
| Claude Code | 2.1.316, model `claude-opus-5-5`, claude.ai subscription login |
| Codex CLI | 0.166.0, the default model of the ChatGPT login |
| Judge (outcome case) | `claude-opus-5-5`, one call per run, blind labels |
| Outcome runs | 1 case x 3 runs x 4 configurations = 12; the probe passed twice first |
| Routing runs | 184 prompts (138 positives, 46 near-misses) x 2 runs per agent, batches of 22 |

## The review case

The task: review `src/lib.rs` of a library crate that other crates are about to use, write the
review to `REVIEW.md`, and change no code. The defects run from undefined behavior
(`from_utf8_unchecked` on file bytes) and panics on file input, through a `String` error type,
`&String` and `bool` parameters, `Rc<RefCell<_>>` in a public signature, and `HashMap` order in a
report, to a `get_` getter. Default clippy is clean.

| Grader | claude-skills | claude-none | codex-skills | codex-none |
| --- | ---: | ---: | ---: | ---: |
| code-unchanged | 3/3 | 3/3 | 3/3 | 3/3 |
| no-fmt-rewrite | 3/3 | 3/3 | 3/3 | 3/3 |
| top-priority-is-ub-and-panics | 3/3 | 3/3 | 3/3 | 0/3 |
| api-and-error-findings | 3/3 | 3/3 | 3/3 | 2/3 |
| findings-have-location-rule-fix | 0/3 | 0/3 | 3/3 | 0/3 |
| already-good-and-tools | 3/3 | 0/3 | 3/3 | 0/3 |
| **Total** | **15/18** | **12/18** | **18/18** | **8/18** |

The owning skill loaded in 3 of 3 runs for both agents.

One grader was fixed after the run and judged again with `grade --regrade`: the first
`api-and-error-findings` counted a finding only below the top section, and Codex with the skill
put `Rc<RefCell<_>>` in a public signature under Must fix, which is defensible. The ranking of the
undefined behavior and the panics has its own grader. Before the fix, codex-skills scored 15/18.

Findings:

1. The skill gains the most where the model lacks the report discipline. Codex without it missed
   the undefined behavior in its top section in every run, and wrote no "already good" section;
   with it, Codex scored every grader in every run.
2. Claude found every defect with or without the skill. The skill added the "already good"
   section and the tool runs (0/3 to 3/3). It did not make every finding cite a rule that a
   reader can look up: in every Claude run, with or without the skill, some findings named a
   prose rule ("correctness"), and some fixes were prose only. The skill asks for both; Claude
   followed it less closely than Codex did.
3. No agent rewrote the code or ran `cargo fmt` without `--check`.

## Subscription routing

| Agent | Positives top-1 | Positives top-2 | Near-misses top-1 | Failed batches |
| --- | ---: | ---: | ---: | ---: |
| Claude Code, `claude-opus-5-5` | 0.996 | 0.996 | 0.957 | 0 |
| Codex CLI, default model | 0.967 | 0.993 | 0.957 | 0 |

Every prompt of the two new skills, `rust-port` and `rust-review`, routed to its skill in both
runs on both agents. The misses, each in both runs unless noted:

| Prompt | Expected | Chosen | Agents | Reading |
| --- | --- | --- | --- | --- |
| rust-discipline-p2 (a `Condvar` wait that hangs) | rust-discipline | memory-model | both | The description of `rust-discipline` does not name condition variables; its body does. A routing fix to try |
| rust-ios-build-p2, -p3 (undefined or duplicate symbols when linking a Rust staticlib into an app) | rust-ios-build | rust-native-linking | Codex | `rust-native-linking` owns link failures in general; both answers help. Consider `rust-native-linking` as an accepted alternate |
| rust-test-tools-p3 | rust-test-tools | rust-security | Codex | second choice correct |
| rust-crate-architecture-p2, rust-performance-p2 | their skills | cargo-workflows | Codex, one run each | second choice correct for rust-performance |
| rust-pattern-semantics-n1, rust-panic-safety-n1 (near-misses) | rust-discipline | rust-lints, rust-code-style | both | The labels expect `rust-discipline`; both agents agree on another skill. Review the labels |

There is no earlier subscription routing run to compare against, so this table is a baseline, not
evidence that the description trims of this change cost anything. The trims removed no token that
a routing prompt uses, except `checked-in`, which went back.

## What this does not prove

- That a difference of one or two graders is real: three runs per arm.
- That the judge is unbiased: it is a Claude model, and it saw no agent or arm label.
- That routing in a real client matches this forced choice from a list; `evals/plugin/` and the
  skill-loaded column of the outcome runs measure that.

## Raw data

`/Users/Shared/rust-skills-evals/review-2026-11-02/` (outcome runs, grades, and `routing/`) on the
machine that ran it; not committed.
