# Evaluations

Two suites measure routing, the step where an agent decides which skill to load. A third one,
`outcome/`, measures what the agent produces after it loads the skill: the code it changes and
the evidence it reports, with the plugin and without it. None of them proves that a skill's
advice is correct; the compile gate in `checks/` and the review of each skill do that. Nothing in
this directory ships to consumers.

| Suite | Question it answers | Needs |
| --- | --- | --- |
| `routing/` | Given only the names and descriptions, does a model pick the right skill, or none? | An Anthropic or OpenAI key |
| `plugin/` | Installed as a plugin in a real client, does the agent load the skill on a natural request, and does its answer use the skill's verifier? | Claude Code 2.1.269 or later and an Anthropic key |
| `outcome/` | On a real task with a planted defect, does the plugin change what the agent fixes, how it fixes it, and what it claims as proof? | Claude Code 2.1.316 (the version the cases were checked against), an Anthropic key, and a Rust toolchain |

Results that need a key are never committed here. Record each run in `research/` with the date,
the catalog commit, the client version, and the exact model IDs (`docs/releasing.md`).

## `routing/`: selection from a list

- `prompts.jsonl`: 176 prompts, 4 per skill. Three are positives that the skill owns. One is a
  near-miss: it shares surface terms with the skill but belongs to a sibling, or to no skill
  (`"expected": "none"`, 2 prompts). Each row has `id`, `skill`, `kind`, `prompt`, `expected`,
  `accepted_alternates`, and `source`. The prompts were written from the skill bodies at catalog
  commit `5d5f470`, blind to the descriptions; `source` names the section each one came from at
  that commit, and a later move into `references/` does not update it.
- `negative-cases.md`: phrases a description must not claim. `scripts/validate-skills.py`
  enforces it on every run.
- `run.py`: the runner.

```bash
python3 evals/routing/run.py --lint        # schema, coverage, and blindness; no key
python3 evals/routing/run.py --dry-run     # print the first request; no key
python3 evals/routing/run.py --provider anthropic --model <id> --runs 2
python3 evals/routing/run.py --provider openai --model <id> --runs 2 --truncate 150
```

A run sends batches of 22 prompts with the full listing, asks for a first and a second choice
from a closed list of skill names plus `none`, and writes `routing-<provider>-<model>-<date>.json`
next to the runner (git ignores it). `--truncate N` keeps the first N characters of each
description, which approximates a client that keeps only a prefix. `check.sh` runs `--lint` and
the runner's unit tests.

What a green result proves: the descriptions separate the skills for that model when the model is
asked to choose. What it does not prove:

- that a client loads the skill on its own while it works. Under-triggering, where the agent never
  considers a skill, does not show up when the question forces a choice;
- anything about another model family. Run at least two providers before you trust a change;
- that a label is right. A near-miss can be defensible for the skill the model picked. Read the
  misses in the JSON file before you change a description;
- that the prompts are unbiased. One model family wrote them, from the bodies; a lint keeps them
  from sharing four consecutive words with any description, nothing more.

## `plugin/`: a real client

Six cases, one per bundle of `bundles.toml`. Each `case.yaml` holds a natural request that never
names a skill. Two graders per case:

- `skill-fired` in `case.yaml` (`tool_used: Skill` with an `input_match` on the skill name)
  records whether the agent loaded the expected skill. The CLI reports it as an indicator, not as
  part of the score, because the no-plugin arm cannot load it.
- `graders/cites-verifier.md` (an LLM rubric) passes when the answer gives the verifier command
  that the skill owns. It is scored in both arms, so the reported delta is what the plugin adds.

```bash
claude plugin eval . --eval-dir evals/plugin --trust-plugin --threshold 0.8 \
  --max-cost-usd 20 --no-publish --json eval-results.json
```

Run it from a clean checkout: the CLI refuses a plugin directory that holds hard links, and the
local `checks/target/` build cache has them. The `Plugin eval` workflow runs the same command on
`workflow_dispatch` with pinned model IDs.

What a green result proves: on that client, model, and catalog commit, a natural request loads
the skill and the answer carries its verifier. What it does not prove: behavior on Codex, Cursor,
or another client; behavior with all 44 skills installed when the client truncates its listing
(the suite loads the whole plugin, so it measures the full listing); or that six cases represent
44 skills.

## `outcome/`: the work itself

Six cases, one per bundle. Each case is a small std-only crate with one planted defect that one
skill owns: a guard in a `match` scrutinee, `Relaxed` publication, a bug in a shared helper with a
copy elsewhere, a `feat` commit that is a major bump, an allocation on every header, and a C ABI
that returns a pointer into a dropped `CString`. `cases.toml` maps each case to its skill.

- `case.yaml` holds the natural request, which never names a skill, and most graders: a `regex`
  on a file the agent changed, a `tool_used` limit, the `skill-fired` indicator, and judged
  criteria on one file. `graders/*.md` hold the judged criteria on the trace or the final answer.
  Each judged criterion has a PASS line and a FAIL line taken from the owning skill's rules and
  verifier table.
- `scaffold.sh` builds the workspace from `files/` (and `next/`, for the case that needs git
  history). `CARGO_NET_OFFLINE` is set in every case, so a run needs no registry.
- `probe/*.rs`, where a portable test can show the defect, proves it: the gate requires the probe
  to fail on the fixture. `solution/` is one correct fix; the gate lays it over the fixture and
  requires `cargo test` with every probe to pass, so a probe fails only on the defect. A case
  with a probe or with a fixture that fails or hangs must have one. The scaffold never copies
  `probe/` or `solution/` into the agent's workspace.

```bash
python3 evals/outcome/check.py --lint      # structure only; no cargo
python3 evals/outcome/check.py             # also builds every fixture offline; check.sh runs this
claude plugin eval . --eval-dir evals/outcome --trust-plugin --scaffold \
  --allow-tools Bash Write Edit --concurrency 4 --max-cost-usd 40 --no-publish \
  --json eval-results.json
```

`--scaffold` runs `scaffold.sh` from this repository, and `--allow-tools` lets the agent run cargo
and edit the workspace. The command sets no `--threshold`: the result is a measurement, and the
number to record is the delta between the arms, not a pass mark. Run it from a clean checkout, as
for `plugin/`: a local `files/target/` holds hard links, which the CLI refuses. Each case runs
three times in each arm. `--max-cost-usd` stops the next run from starting; it does not stop a run
already in flight.

What a green gate proves: every case parses, every file a grader reads exists in the workspace,
every fixture builds offline on the pinned toolchain, `cargo test` on it does what `cases.toml`
says (pass, fail, or hang), and every probe fails on the fixture and passes on the reference
fix. What
a recorded run proves: on that client, model, judge, and catalog commit, the plugin arm scored as
reported against the no-plugin arm on these six tasks. What it does not prove:

- that the judge is right. The judged graders read files and traces; spot-check a sample of the
  verdicts in the JSON before you trust a delta;
- anything about a skill without a case, or about another client or model family;
- that a delta is real when it is one grader wide. Three runs per arm on six cases is a small
  sample; repeat a run before you change a skill because of it;
- that a client loads the skill on its own in a crowded listing. The `skill-fired` indicator
  reports that for each run, outside the score.

Add a case when a skill gains a rule that a task can exercise: a fixture that compiles, a defect
that the fixture's own tests miss or show only as a symptom, a probe when one is portable, and
graders that a reader can check against the skill text. Keep the fixture on the standard library, so the case runs offline.
