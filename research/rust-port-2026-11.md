# rust-port, first measurement, 2026-11

Measured by this repository on 2026-11-02. It is the first run of the outcome case
`testing-port-python-report`, which came with the new `rust-port` skill.

## Setup

| Item | Value |
| --- | --- |
| Catalog snapshot | `e0ccad8` (45 skills, with `rust-port`) |
| Runner | `evals/outcome/cross_agent.py`, same commit |
| Claude Code | 2.1.316, model `claude-opus-5-5`, claude.ai subscription login |
| Codex CLI | 0.166.0, the default model of the ChatGPT login |
| Judge | `claude-opus-5-5`, one call per run, blind labels |
| Runs | 1 case x 3 runs x 4 configurations = 12 agent runs, 12 judged runs |

The task: port `report.py` to `src/lib.rs` with its tests, and keep its results. The six Python
tests pass for a direct translation. Four behaviors that they do not cover change in one: floor
division of a negative total, rounding of halves to even, first-seen order, and padding by code
points. The probe passed twice before the runs. All 12 runs ended with a final answer.

## Result

| Grader | claude-skills | claude-none | codex-skills | codex-none |
| --- | ---: | ---: | ---: | ---: |
| floor-division | 3/3 | 3/3 | 3/3 | 3/3 |
| rounds-half-to-even | 3/3 | 3/3 | 3/3 | 3/3 |
| order-width-and-parsing | 3/3 | 3/3 | 3/3 | 3/3 |
| compared-with-original | 3/3 | 3/3 | 3/3 | 1/3 |
| porting-notes | 3/3 | 0/3 | 3/3 | 0/3 |
| tests-ported-first | 1/3 | 3/3 | 3/3 | 0/3 |
| **Total** | **16/18** | **15/18** | **18/18** | **10/18** |

The owning skill loaded in 3 of 3 runs for both agents. Median run time: claude-skills 181 s,
claude-none 180 s, codex-skills 154 s, codex-none 87 s.

## Findings

1. Every configuration kept all four hidden behaviors in the code, with and without the skill.
   Both models know these traps; the graders on the code do not separate the arms.
2. The skill changes the process, and most for Codex: 18 of 18 against 10 of 18. Without it,
   Codex merged the six Python tests into four, did not run `report.py` on new inputs in two of
   three runs, and took the expected values "from its own reasoning". With it, Codex ported the
   tests one for one, recorded Python's outputs, and wrote `PORTING.md` in every run.
3. Claude compared with the original in every run, with or without the skill. Without the skill
   it wrote no porting notes. With the skill it wrote them in every run and built a recorded
   golden replay of 71 to 89 cases, but in two runs it wrote the implementation before the
   tests, or ran no test until after several more edits. The skill says "port the tests first";
   Claude with the skill followed the comparison part of the procedure more closely than that
   step.
4. The process graders separate the arms; the behavior graders do not. A harder case would hide a
   trap that the models do not know, such as Python's `splitlines` separators or JavaScript's
   default sort.

## What this does not prove

- Anything about a one-grader difference, such as 16 against 15 for Claude: three runs per arm.
- That the judge is unbiased: it is a Claude model, and it saw no agent or arm label.
- Anything about other source languages: the case ports Python only.

## Raw data

`/Users/Shared/rust-skills-evals/port-2026-11-02b/` on the machine that ran it; not committed.
