# Evaluations

Two suites measure routing, the step where an agent decides which skill to load. Neither one
measures whether a skill's advice is correct; the compile gate in `checks/` and the review of
each skill do that. Nothing in this directory ships to consumers.

| Suite | Question it answers | Needs |
| --- | --- | --- |
| `routing/` | Given only the names and descriptions, does a model pick the right skill, or none? | An Anthropic or OpenAI key |
| `plugin/` | Installed as a plugin in a real client, does the agent load the skill on a natural request, and does its answer use the skill's verifier? | Claude Code 2.1.269 or later and an Anthropic key |

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
