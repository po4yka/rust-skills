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

- `prompts.jsonl`: four prompts per skill. Three are positives that the skill owns. One is a
  near-miss: it shares surface terms with the skill but belongs to a sibling, or to no skill
  (`"expected": "none"`, 2 prompts). Each row has `id`, `skill`, `kind`, `prompt`, `expected`,
  `accepted_alternates`, and `source`. The initial prompts were written from the skill bodies at catalog
  commit `5d5f470`, blind to the descriptions. Later additions use the same method.
  Each `source` names the source section; a later move into `references/` does not update it.
- `negative-cases.md`: phrases a description must not claim. `scripts/validate-skills.py`
  enforces it on every run.
- `run.py`: the runner.

```bash
python3 evals/routing/run.py --lint        # schema, coverage, and blindness; no key
python3 evals/routing/run.py --dry-run     # print the first request; no key
python3 evals/routing/run.py --provider anthropic --model <id> --runs 2
python3 evals/routing/run.py --provider openai --model <id> --runs 2 --truncate 150
python3 evals/routing/run.py --provider claude-cli --model <id> --runs 2   # subscription, no key
python3 evals/routing/run.py --provider codex-cli --runs 2                 # subscription, no key
```

`claude-cli` and `codex-cli` call `claude -p` and `codex exec` on a subscription login, from the
isolated login homes of the cross-agent outcome runner (below). The CLIs run with no tool, with
all skills, commands, plugins, apps, and hooks off, so the listing in the prompt is the only one
they see. A batch that fails counts its prompts as wrong, and the result says how many failed.

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

Run the suite from a clean checkout that has a plugin manifest at its root. The CLI loads a
plugin only from a manifest at the target, and this repository has none, because Codex installs
no bundle while a root manifest names another plugin. Without the manifest the CLI runs one arm
with no plugin, loads no skill, and still reports a score (measured with Claude Code 2.1.316 on
2026-11-02). Write the manifest only in the clean checkout and never commit it:
`scripts/validate-skills.py` fails while it exists. The clean checkout also keeps out the local
`checks/target/` build cache, which holds hard links that the CLI refuses.

```bash
git worktree add --detach ../rust-skills-eval HEAD
cd ../rust-skills-eval
mkdir -p .claude-plugin
printf '%s\n' '{"name": "rust-skills", "description": "rust-skills catalog for the plugin evaluation", "skills": ["./skills"]}' \
  > .claude-plugin/plugin.json
claude plugin eval . --eval-dir evals/plugin --trust-plugin --threshold 0.8 \
  --max-cost-usd 20 --no-publish --json eval-results.json
```

The CLI prints `Ablation: defaulting to with-without` when it loads the plugin. The `Plugin eval`
workflow writes the same manifest, runs the same command on `workflow_dispatch` with pinned model
IDs, and fails when the result names no plugin.

What a green result proves: on that client, model, and catalog commit, a natural request loads
the skill and the answer carries its verifier. What it does not prove: behavior on Codex, Cursor,
or another client; behavior with all 51 skills installed when the client truncates its listing
(the suite loads the whole plugin, so it measures the full listing); or that six cases represent
51 skills.

## `outcome/`: the work itself

Nine cases: one per bundle, and two more testing cases, for `rust-port` and `rust-review`. Each
case is a small std-only crate with one planted defect that one skill owns: a guard in a `match`
scrutinee, `Relaxed` publication, a bug in a shared helper with a copy elsewhere, a `feat` commit
that is a major bump, an allocation on every header, and a C ABI that returns a pointer into a
dropped `CString`. The port case asks for a Python module in Rust; its own tests miss its floor
division, half-to-even rounding, insertion order, and code-point padding. The review case asks for
a review of a library module whose defects range from undefined behavior to a getter name. `cases.toml` maps each case to its skill.

- `case.yaml` holds the natural request, which never names a skill, and most graders: a `regex`
  on a file the agent changed, a `tool_used` limit, the `skill-fired` indicator, and judged
  criteria on one file. `graders/*.md` hold the judged criteria on the trace or the final answer.
  Each judged criterion has a PASS line and a FAIL line taken from the owning skill's rules and
  verifier table.
- `scaffold.sh` builds the workspace from `files/` (and `next/`, for the case that needs git
  history). The operator sets `CARGO_NET_OFFLINE=true`; case files set no environment
  overrides. The workflow and cross-agent runner enforce this offline Cargo setting.
  The pinned evaluation CLI rejects non-`EVAL_*` keys in `execution.env`.
- `probe/*.rs`, where a portable test can show the defect, proves it: the gate requires the probe
  to fail on the fixture. `solution/` is one correct fix; the gate lays it over the fixture and
  requires `cargo test` with every probe to pass, so a probe fails only on the defect. A case
  with a probe or with a fixture that fails or hangs must have one. The scaffold never copies
  `probe/` or `solution/` into the agent's workspace.

```bash
python3 evals/outcome/check.py --lint      # structure only; no cargo
python3 evals/outcome/check.py             # also builds every fixture offline; check.sh runs this
CARGO_NET_OFFLINE=true claude plugin eval . --eval-dir evals/outcome --trust-plugin --scaffold \
  --allow-tools Bash Write Edit --concurrency 4 --max-cost-usd 40 --no-publish \
  --json eval-results.json
```

`--scaffold` runs `scaffold.sh` from this repository, and `--allow-tools` lets the agent run cargo
and edit the workspace. The command sets no `--threshold`: the result is a measurement, and the
number to record is the delta between the arms, not a pass mark. Run it from a clean checkout with
the plugin manifest, as for `plugin/`; a local `files/target/` also holds hard links, which the CLI
refuses. Each case runs
three times in each arm. `--max-cost-usd` stops the next run from starting; it does not stop a run
already in flight.

What a green gate proves: every case parses, every file a grader reads exists in the workspace,
every fixture builds offline on the pinned toolchain, `cargo test` on it does what `cases.toml`
says (pass, fail, or hang), and every probe fails on the fixture and passes on the reference
fix. What
a recorded run proves: on that client, model, judge, and catalog commit, the plugin arm scored as
reported against the no-plugin arm on these nine tasks. What it does not prove:

- that the judge is right. The judged graders read files and traces; spot-check a sample of the
  verdicts in the JSON before you trust a delta;
- anything about a skill without a case, or about another client or model family;
- that a delta is real when it is one grader wide. Three runs per arm on nine cases is a small
  sample; repeat a run before you change a skill because of it;
- that a client loads the skill on its own in a crowded listing. The `skill-fired` indicator
  reports that for each run, outside the score.

### Claude Code and Codex on subscriptions

`claude plugin eval` runs Claude only, on the key or login of the caller. `cross_agent.py` runs
the same cases on Claude Code and on Codex, each with the catalog and without it, through their
subscription logins, and grades all four configurations with one blind judge. Use one output
directory for every step; the default is outside `$HOME`, because Claude reads memory files in
every parent of its working directory.

```bash
CLAUDE_CONFIG_DIR=~/.claude-eval claude auth login     # once: a login home with nothing else in it
echo '{"syncClaudeAiPlugins": false, "syncClaudeAiSkills": false}' > ~/.claude-eval/settings.json
CODEX_HOME=~/.codex-eval codex login                     # once
OUT=/Users/Shared/rust-skills-evals/outcome-<date>
uv run --with pyyaml python3 evals/outcome/cross_agent.py preflight --out "$OUT"
uv run --with pyyaml python3 evals/outcome/cross_agent.py probe --out "$OUT"
uv run --with pyyaml python3 evals/outcome/cross_agent.py run --out "$OUT"
uv run --with pyyaml python3 evals/outcome/cross_agent.py grade --out "$OUT"
uv run --with pyyaml python3 evals/outcome/cross_agent.py report --out "$OUT"
```

- Isolation. Each agent runs from its own login home, so the user's skills, plugins, hooks,
  memory files, and MCP servers reach no run. Both agents get one snapshot of the catalog, taken
  in `$OUT/catalog` before the first run: Claude through `--plugin-dir`, Codex in
  `$HOME/.agents/skills` of a per-run home. The snapshot keeps the repository, with its graders
  and reference fixes, out of every agent's reach.
- The probe. `probe` turns off every plugin that the Claude account syncs into the login home,
  then asks each configuration twice which skills it can load. It fails unless the catalog is
  present only in the skills arm, the two Claude arms match exactly outside the catalog, Codex
  names nothing outside the catalog and its built-in `.system` set, and no unexpected plugin, MCP
  server, or memory file loads. `run` refuses to start without a passing probe in `$OUT`. What
  stays in both arms alike: Claude's built-in skills and the skills that the account syncs, and
  Codex's built-in skills.
- Routes. The children get a built environment with no API key, base-URL override, or
  cloud-provider route, and a neutral git identity with signing off. `preflight` refuses a shell
  that has a route. Cost fields are the CLIs' estimates; they do not measure subscription quota.
- Grading. The runner scores the `regex` and `tool_used` graders itself; `tool_used` sees shell
  commands only. One Claude judge scores the judged criteria of each run in one call, under a
  label derived from the seed and the run, from a record with the skill loads removed, and with
  paths, agent and model names, and catalog skill names redacted. The judge sees the final diff
  of the workspace rather than each edit, because Codex reports an edit by path only.
- Restart. `run` and `grade` skip finished work. A run that ends in an error, or stalls on a
  usage limit, is retried on the next `run`; a timeout is a result. Ctrl-C stops every running
  agent. `run` refuses an output directory whose catalog, CLI versions, or models changed.
- Re-grade. After a grader changes, `grade --regrade <name>,<name>` judges only those graders
  again on the recorded runs, with no new agent run. Each verdict records a hash of its grader
  definition (`revision`). A grader is judged again only when that hash differs from the
  current definition, so a rerun of the same command resumes and a second change starts a new
  re-grade. A verdict from a grade file without `revision` is always judged again. Each judge
  verdict names the `judge_model` that gave it, so a re-grade with another `--judge-model`
  does not change the record of the verdicts it keeps. The grade
  file keeps every replaced verdict, oldest first, in a list under `superseded`, so each result
  stays comparable with the ones before it.

Differences between the arms that the runner does not remove: Codex runs in its
`workspace-write` sandbox and Claude runs with an allowlist of tools; neither agent honors the
`max_turns` of a case, only its `timeout_seconds`; the judge is a Claude model; a redacted skill
name ("a guideline") appears mostly in the skills arm; and the style of a final answer can still
hint at its agent. Read the report with those in mind.

Add a case when a skill gains a rule that a task can exercise: a fixture that compiles, a defect
that the fixture's own tests miss or show only as a symptom, a probe when one is portable, and
graders that a reader can check against the skill text. Keep the fixture on the standard library, so the case runs offline.
