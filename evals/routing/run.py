#!/usr/bin/env python3
"""Routing evaluation: does a model pick the right skill from names and descriptions alone?

The runner shows a model the catalog the way a client's skill listing does (each skill's name
and description, nothing else) and asks, for a batch of prompts, which skill it would load first
and second, or "none". It scores top-1 and top-2 accuracy on the positive set and the near-miss
set, prints a Markdown table, and writes the raw answers to a JSON file.

    python3 evals/routing/run.py --lint
    python3 evals/routing/run.py --dry-run
    python3 evals/routing/run.py --provider anthropic --model <model-id> --runs 2
    python3 evals/routing/run.py --provider openai --model <model-id> --truncate 150

--lint and --dry-run need no key, no network, and no package. A real run needs the provider's
SDK (`pip install anthropic` or `pip install openai`) and its key in the environment:
ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) for anthropic, OPENAI_API_KEY for openai.

Refusal fallbacks stay off on purpose. A fallback answers with another model, which would mix
two models into one score; a refused batch is reported as refused instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SKILLS = ROOT / "skills"
PROMPTS = HERE / "prompts.jsonl"
KEYS = {"positive", "near-miss"}
FIELDS = {"id", "skill", "kind", "prompt", "expected", "accepted_alternates", "source"}
ENV_KEYS = {"anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"), "openai": ("OPENAI_API_KEY",)}

SYSTEM = """You select agent skills for a coding agent that works on Rust code.

Each skill below has a name and a description. The agent loads a skill only when the request
needs it. For each request, choose the skill the agent should load first, and the skill it should
load second. Answer "none" when no skill fits; a second choice may also be "none". Use only the
names in the list.

Skills:
{listing}"""

USER = """Choose skills for each request. Answer for every id.

{requests}"""


def load_descriptions(truncate: int) -> dict[str, str]:
    found = {}
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        match = re.search(r"^description: (.*)$", path.read_text(encoding="utf-8"), re.M)
        if match is None:
            sys.exit(f"{path}: no description line")
        text = match.group(1)
        found[path.parent.name] = text[:truncate] if truncate else text
    return found


def load_prompts(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                sys.exit(f"{path}:{number}: not JSON: {error}")
    return rows


def grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def lint(rows: list[dict], descriptions: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for the prompt set.

    A problem breaks the method: a bad schema, an unknown skill, a prompt that names a skill, or
    uneven coverage. A warning is a prompt that shares four consecutive words with a description.
    The prompts were written blind to the descriptions; a later description edit can create the
    overlap, and then the prompt or the description needs a rewording before the next run.
    """
    problems, warnings = [], []
    seen = set()
    description_grams = {name: grams(text) for name, text in descriptions.items()}
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        where = row.get("id", "<no id>")
        if set(row) != FIELDS:
            problems.append(f"{where}: keys must be exactly {sorted(FIELDS)}")
            continue
        if row["id"] in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(row["id"])
        if row["kind"] not in KEYS:
            problems.append(f"{where}: kind must be positive or near-miss")
        if row["skill"] not in descriptions:
            problems.append(f"{where}: skill {row['skill']!r} is not in skills/")
        for name in [row["expected"], *row["accepted_alternates"]]:
            if name != "none" and name not in descriptions:
                problems.append(f"{where}: {name!r} is not in skills/")
        if row["kind"] == "positive" and row["expected"] != row["skill"]:
            problems.append(f"{where}: a positive expects its own skill")
        if row["kind"] == "near-miss" and row["expected"] == row["skill"]:
            problems.append(f"{where}: a near-miss expects a sibling or none")
        text = row["prompt"].lower()
        for name in descriptions:
            if re.search(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", text):
                problems.append(f"{where}: names the skill {name!r}")
        prompt_grams = grams(row["prompt"])
        for name, shared in description_grams.items():
            if prompt_grams & shared:
                sample = " ".join(sorted(prompt_grams & shared)[0])
                warnings.append(f"{where}: shares wording with the {name} description: {sample!r}")
        counts[(row["skill"], row["kind"])] = counts.get((row["skill"], row["kind"]), 0) + 1
    for name in sorted(descriptions):
        if counts.get((name, "positive"), 0) != 3 or counts.get((name, "near-miss"), 0) != 1:
            problems.append(f"{name}: needs 3 positives and 1 near-miss")
    return problems, warnings


def answer_schema(names: list[str]) -> dict:
    choice = {"type": "string", "enum": [*names, "none"]}
    return {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "first": choice, "second": choice},
                    "required": ["id", "first", "second"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["answers"],
        "additionalProperties": False,
    }


def build_messages(descriptions: dict[str, str], batch: list[dict]) -> tuple[str, str]:
    listing = "\n".join(f"- {name}: {text}" for name, text in descriptions.items())
    requests = "\n\n".join(f"[{row['id']}]\n{row['prompt']}" for row in batch)
    return SYSTEM.format(listing=listing), USER.format(requests=requests)


def require_key(provider: str) -> None:
    names = ENV_KEYS[provider]
    if not any(os.environ.get(name) for name in names):
        sys.exit(
            f"error: --provider {provider} needs {' or '.join(names)} in the environment. "
            f"Nothing was sent. Use --lint or --dry-run to check the set without a key."
        )


def ask_anthropic(model: str, effort: str | None, system: str, user: str, schema: dict) -> dict:
    try:
        import anthropic
    except ImportError:
        sys.exit("error: --provider anthropic needs the SDK: pip install anthropic")
    client = anthropic.Anthropic()
    params = {
        "model": model,
        "max_tokens": 16000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    if effort:
        params["output_config"]["effort"] = effort
    response = client.messages.create(**params)
    if response.stop_reason == "refusal":
        return {"refused": True, "answers": []}
    if response.stop_reason == "max_tokens":
        return {"truncated": True, "answers": []}
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def ask_openai(model: str, effort: str | None, system: str, user: str, schema: dict) -> dict:
    try:
        import openai
    except ImportError:
        sys.exit("error: --provider openai needs the SDK: pip install openai")
    client = openai.OpenAI()
    params = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "skill_choices", "schema": schema, "strict": True},
        },
    }
    if effort:
        params["reasoning_effort"] = effort
    response = client.chat.completions.create(**params)
    message = response.choices[0].message
    if getattr(message, "refusal", None):
        return {"refused": True, "answers": []}
    return json.loads(message.content)


def score(rows: list[dict], answers: list[dict[str, dict]]) -> dict:
    """Top-1 and top-2 per set, averaged over runs; a missing answer counts as wrong."""
    result = {}
    for kind in ("positive", "near-miss"):
        subset = [row for row in rows if row["kind"] == kind]
        top1 = top2 = 0
        misses = []
        for run, by_id in enumerate(answers):
            for row in subset:
                ok = {row["expected"], *row["accepted_alternates"]}
                got = by_id.get(row["id"], {})
                first, second = got.get("first"), got.get("second")
                top1 += first in ok
                top2 += first in ok or second in ok
                if first not in ok:
                    misses.append({"run": run, "id": row["id"], "expected": row["expected"], "first": first, "second": second})
        total = len(subset) * len(answers)
        result[kind] = {
            "n": len(subset),
            "top1": round(top1 / total, 3) if total else None,
            "top2": round(top2 / total, 3) if total else None,
            "misses": misses,
        }
    return result


def catalog_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", choices=sorted(ENV_KEYS))
    parser.add_argument("--model", help="exact model ID; there is no default")
    parser.add_argument("--effort", help="optional reasoning effort, passed through to the provider")
    parser.add_argument("--truncate", type=int, default=0, help="keep only the first N characters of each description (0: full)")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=22)
    parser.add_argument("--seed", type=int, default=20260924, help="shuffles the prompt order of each run")
    parser.add_argument("--prompts", type=Path, default=PROMPTS)
    parser.add_argument("--out", type=Path, help="JSON result file (default: routing-<provider>-<model>-<date>.json here)")
    parser.add_argument("--lint", action="store_true", help="check the prompt set and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the first batch request and exit")
    args = parser.parse_args()

    descriptions = load_descriptions(args.truncate)
    rows = load_prompts(args.prompts)
    problems, warnings = lint(rows, load_descriptions(0))
    if args.lint:
        for warning in warnings:
            print(f"  warning: {warning}")
        for problem in problems:
            print(f"  {problem}")
        print(f"routing prompts: {len(rows)} rows, {len(problems)} problem(s), {len(warnings)} warning(s)")
        return 1 if problems else 0
    if problems:
        sys.exit(f"error: the prompt set has {len(problems)} problem(s); run --lint")

    names = list(descriptions)
    schema = answer_schema(names)
    if args.dry_run:
        system, user = build_messages(descriptions, rows[: args.batch_size])
        print(system, "\n\n----- user -----\n", user, "\n\n----- schema -----\n", json.dumps(schema)[:400], "...", sep="")
        return 0
    if not args.provider or not args.model:
        parser.error("a run needs --provider and --model")
    require_key(args.provider)
    ask = ask_anthropic if args.provider == "anthropic" else ask_openai

    runs: list[dict[str, dict]] = []
    flags = {"refused_batches": 0, "truncated_batches": 0}
    for run in range(args.runs):
        order = rows[:]
        random.Random(args.seed + run).shuffle(order)
        by_id: dict[str, dict] = {}
        for start in range(0, len(order), args.batch_size):
            batch = order[start : start + args.batch_size]
            system, user = build_messages(descriptions, batch)
            reply = ask(args.model, args.effort, system, user, schema)
            flags["refused_batches"] += bool(reply.get("refused"))
            flags["truncated_batches"] += bool(reply.get("truncated"))
            wanted = {row["id"] for row in batch}
            by_id.update({a["id"]: a for a in reply.get("answers", []) if a.get("id") in wanted})
            print(f"run {run + 1}/{args.runs}: {min(start + args.batch_size, len(order))}/{len(order)}", file=sys.stderr)
        runs.append(by_id)

    scores = score(rows, runs)
    condition = f"first {args.truncate} characters" if args.truncate else "full"
    print(f"\nRouting evaluation: {args.provider} `{args.model}`, descriptions {condition}, {args.runs} run(s)\n")
    print("| Set | Prompts | Top-1 | Top-2 |")
    print("| --- | ---: | ---: | ---: |")
    for kind in ("positive", "near-miss"):
        s = scores[kind]
        print(f"| {kind} | {s['n']} | {s['top1']:.3f} | {s['top2']:.3f} |")
    if flags["refused_batches"] or flags["truncated_batches"]:
        print(f"\nRefused batches: {flags['refused_batches']}. Truncated batches: {flags['truncated_batches']}.")

    date = dt.date.today().isoformat()
    out = args.out or HERE / f"routing-{args.provider}-{re.sub(r'[^a-z0-9.-]', '-', args.model.lower())}-{date}.json"
    out.write_text(
        json.dumps(
            {
                "date": date,
                "catalog_commit": catalog_commit(),
                "provider": args.provider,
                "model": args.model,
                "effort": args.effort,
                "truncate": args.truncate,
                "runs": args.runs,
                "batch_size": args.batch_size,
                "seed": args.seed,
                **flags,
                "scores": scores,
                "answers": runs,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
