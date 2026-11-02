#!/usr/bin/env python3
"""Run the catalog validator after an agent edits a catalog file.

A PostToolUse hook for the coding agents that work in this repository. Claude
Code runs it from .claude/settings.json and Codex from .codex/hooks.json, after
every file edit. It reads the hook event on stdin and finds the edited paths:

  Claude Code sends `tool_input.file_path` for Edit, Write, and MultiEdit.
  Codex sends an apply_patch body in `tool_input.command`, with one
  `*** Add File:`, `*** Update File:`, `*** Delete File:`, or `*** Move to:`
  line per file.

When a path is a catalog file, it runs scripts/validate-skills.py (well under a
second). On failure it writes the problems to stderr and exits 2: both clients
show that text to the model next to the tool result, so the agent fixes the
problem in the same turn. Every other case exits 0 and prints nothing. The
hook never blocks on its own failure: a bad event or a crash in the validator
exits 0, because a broken hook must not stop an edit.

Test it by hand:

    echo '{"tool_input": {"file_path": "skills/rust-tdd/SKILL.md"}}' | python3 scripts/agent-hook.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate-skills.py"

# The files that scripts/validate-skills.py reads. An edit to any other file
# cannot change its verdict.
CATALOG_PREFIXES = ("skills/",)
CATALOG_FILES = {
    "README.md",
    "AGENTS.snippet.md",
    "bundles.toml",
    "tests/routing-cases.md",
    "evals/routing/negative-cases.md",
    "scripts/catalog-ceilings.toml",
    "scripts/validate-skills.py",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "plugin.json",
}
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)
MAX_LINES = 40


def edited_paths(event: dict) -> list[str]:
    """Every path the tool call edited, as the event gives it."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    paths = []
    if isinstance(tool_input.get("file_path"), str):
        paths.append(tool_input["file_path"])
    if isinstance(tool_input.get("command"), str):
        paths.extend(PATCH_PATH.findall(tool_input["command"]))
    return paths


def catalog_paths(paths: list[str], cwd: Path) -> list[str]:
    """The paths, relative to this checkout, that the validator reads."""
    found = []
    for raw in paths:
        path = Path(raw)
        path = (path if path.is_absolute() else cwd / path).resolve()
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue  # another checkout or a file outside this repository
        if relative in CATALOG_FILES or relative.startswith(CATALOG_PREFIXES):
            found.append(relative)
    return found


def failures(stdout: str) -> list[str]:
    """The problem lines that validate-skills.py prints after its FAIL line."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("FAIL:")), None)
    if start is None:
        return []
    return [line.strip() for line in lines[start + 1 :] if line.strip()]


def main() -> int:
    try:
        return check(json.load(sys.stdin))
    except Exception:  # noqa: BLE001 - a broken hook must not stop an edit
        return 0


def check(event: object) -> int:
    if not isinstance(event, dict):
        return 0
    cwd = Path(event["cwd"]) if isinstance(event.get("cwd"), str) else Path.cwd()
    touched = catalog_paths(edited_paths(event), cwd)
    if not touched:
        return 0
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)], cwd=ROOT, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode == 0:
        return 0
    problems = failures(result.stdout)
    if not problems:
        return 0  # not a verdict the hook can report; check.sh still runs the validator
    shown = problems[:MAX_LINES]
    if len(problems) > MAX_LINES:
        shown.append(f"... and {len(problems) - MAX_LINES} more; run python3 scripts/validate-skills.py")
    print(
        f"scripts/validate-skills.py fails after the edit to {', '.join(touched)}:\n"
        + "\n".join(f"  {line}" for line in shown)
        + "\nFix these before the next edit. Run `bash checks/check.sh --fast` for the plugin gates.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
