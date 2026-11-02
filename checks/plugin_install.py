#!/usr/bin/env python3
"""Install every plugin of this marketplace and check what each one loads.

scripts/validate-skills.py proves that .claude-plugin/marketplace.json lists the
bundles of bundles.toml. It reads the JSON; it cannot prove what Claude Code
does with it. This script asks Claude Code itself: in a throwaway config
directory it validates the manifests, adds this checkout as a marketplace,
installs the full catalog and each bundle plugin, and compares the skill
inventory of `claude plugin details` with skills/ and bundles.toml. A wrong path, a
plugin.json that adds the whole skills/ directory to a bundle, or a CLI release
that changes how a root-relative entry loads all fail here.

It needs no API key and no login, and it never touches the caller's own Claude
Code configuration. Run it with the CLI that checks/check.sh pins:

    python3 checks/plugin_install.py --claude "npx -y -p @anthropic-ai/claude-code@<version> claude"

Exit status is 0 when every plugin loads exactly its skills, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
BUNDLES = ROOT / "bundles.toml"

# `claude plugin details` prints `  Skills (N)  a, b, c`. It has no --json.
# `[ \t]` and not `\s`: the match must not run on into the `Agents (0)` line.
SKILLS_LINE = re.compile(r"^[ \t]*Skills \((\d+)\)[ \t]*(.*)$", re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def expected_skills(manifest: dict) -> dict[str, list[str]]:
    """Plugin name -> the skill names it must load.

    The expectation comes from bundles.toml and skills/, never from the
    marketplace entry under test: the plugin named like the marketplace loads
    the whole catalog, and `<marketplace>-<bundle>` loads that bundle.
    """
    bundles = tomllib.loads(BUNDLES.read_text(encoding="utf-8"))["bundles"]
    everything = sorted(d.name for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").is_file())
    full = manifest["name"]
    expected = {full: everything}
    expected |= {f"{full}-{bundle}": sorted(table["skills"]) for bundle, table in bundles.items()}
    return expected


def entry_problems(manifest: dict, expected: dict[str, list[str]]) -> list[str]:
    """Marketplace entries that no bundle explains, and bundles with no entry."""
    names = [e.get("name") if isinstance(e, dict) else None for e in manifest.get("plugins", [])]
    problems = [f"marketplace entry {n!r} is not the full catalog or a bundle" for n in names if n not in expected]
    problems += [f"plugin {p!r} has {names.count(p)} marketplace entries, not 1" for p in expected if names.count(p) != 1]
    return problems


def parse_skills(details: str) -> list[str] | None:
    match = SKILLS_LINE.search(ANSI.sub("", details))
    if match is None:
        return None
    count, names = int(match.group(1)), match.group(2).strip()
    found = sorted(n.strip() for n in names.split(",") if n.strip()) if names else []
    return found if len(found) == count else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install every plugin of this marketplace and check its skills.")
    parser.add_argument("--claude", default="claude", help="command that runs the Claude Code CLI")
    args = parser.parse_args(argv)
    claude = shlex.split(args.claude)

    manifest = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    marketplace = manifest["name"]
    expected = expected_skills(manifest)
    problems = entry_problems(manifest, expected)
    for problem in problems:
        print(f"  {problem}")

    with tempfile.TemporaryDirectory(prefix="plugin-install-") as config:
        env = dict(os.environ)
        env.update(
            {
                # A fresh config directory: no login, no installed plugins, and
                # nothing written to the caller's ~/.claude.
                "CLAUDE_CONFIG_DIR": config,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
            }
        )

        def run(*command: str) -> subprocess.CompletedProcess[str]:
            argv = [*claude, *command]
            try:
                return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return subprocess.CompletedProcess(argv, 124, "", f"timed out after 300 s: {shlex.join(argv)}")

        def output(result: subprocess.CompletedProcess[str]) -> str:
            return ANSI.sub("", result.stdout + result.stderr).strip()

        version = run("--version")
        if version.returncode != 0:
            print(f"cannot run {args.claude!r}:\n{version.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"  Claude Code {version.stdout.strip()}")

        # Errors fail; warnings do not. docs/releasing.md explains why the
        # missing `version` warning is expected, so --strict is never used.
        result = run("plugin", "validate", ".")
        if result.returncode != 0:
            print(output(result))
            print("FAIL: claude plugin validate reported errors")
            return 1
        print("  claude plugin validate: no errors")

        result = run("plugin", "marketplace", "add", "./")
        if result.returncode != 0:
            print(output(result))
            print("FAIL: claude plugin marketplace add ./")
            return 1

        listed = {e.get("name") for e in manifest.get("plugins", []) if isinstance(e, dict)}
        failed = 0
        for plugin, skills in expected.items():
            if plugin not in listed:
                continue  # already reported by entry_problems
            target = f"{plugin}@{marketplace}"
            result = run("plugin", "install", target)
            if result.returncode != 0:
                print(f"  {target}: install failed\n{output(result)}")
                failed += 1
                continue
            details = run("plugin", "details", target)
            loaded = parse_skills(details.stdout) if details.returncode == 0 else None
            if loaded is None:
                print(f"  {target}: no skill inventory in `claude plugin details`:\n{output(details)}")
                failed += 1
            elif loaded != skills:
                missing = sorted(set(skills) - set(loaded))
                extra = sorted(set(loaded) - set(skills))
                print(f"  {target}: loads {len(loaded)} skills, expected {len(skills)}")
                if missing:
                    print(f"    missing: {', '.join(missing)}")
                if extra:
                    print(f"    extra:   {', '.join(extra)}")
                failed += 1
            else:
                print(f"  {target}: {len(loaded)} skills")

    if failed or problems:
        print(f"FAIL: {failed} of {len(expected)} plugin(s) do not load their skills; {len(problems)} entry problem(s)")
        return 1
    print(f"OK: all {len(expected)} plugins load exactly their skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
