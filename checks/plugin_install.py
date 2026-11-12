#!/usr/bin/env python3
"""Install every plugin of this marketplace and check what each one loads.

scripts/validate-skills.py proves that .claude-plugin/marketplace.json lists the
bundles of bundles.toml. It reads the JSON; it cannot prove what a client does
with it. This script asks the clients themselves, in a throwaway config
directory, and compares what each plugin loads with skills/ and bundles.toml:

  Claude Code: `claude plugin validate .`, add this checkout as a marketplace,
  install each plugin, and read the inventory of `claude plugin details`.

  Codex: add this checkout as a marketplace, install each plugin into its own
  fresh CODEX_HOME, and read the skills that `codex debug prompt-input` puts in
  front of the model, which is what a session loads.

A wrong path, a root plugin.json that Codex compares each entry name with, or a
CLI release that changes how a root-relative entry loads all fail here.

It needs no API key and no login, and it never touches the caller's own
configuration. Run it with the CLIs that checks/check.sh pins:

    python3 checks/plugin_install.py --claude "npx -y -p @anthropic-ai/claude-code@<version> claude"
    python3 checks/plugin_install.py --codex "npx -y @openai/codex@<version>"

Exit status is 0 when every plugin loads exactly its skills, 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
BUNDLES = ROOT / "bundles.toml"
ROUTING = ROOT / "tests" / "routing-cases.md"
VALIDATOR = ROOT / "scripts" / "validate-skills.py"
# The skills Codex lists in a fresh CODEX_HOME and HOME (0.166.0 and 0.167.2). Any other
# non-plugin entry shares the skill-list budget and makes the measurement
# depend on one machine.
CODEX_BUILTIN_SKILLS = {"imagegen", "openai-docs", "skill-creator", "skill-installer"}

# `claude plugin details` prints `  Skills (N)  a, b, c`. It has no --json.
# `[ \t]` and not `\s`: the match must not run on into the `Agents (0)` line.
SKILLS_LINE = re.compile(r"^[ \t]*Skills \((\d+)\)[ \t]*(.*)$", re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# `codex debug prompt-input` lists each plugin skill as `- <plugin>:<skill>: <description>`
# under an `### Available skills` heading (Codex 0.166.0 and 0.167.2).
CODEX_HEADING = "### Available skills"


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
    """The skills in `claude plugin details` output, or None when it has no readable inventory."""
    match = SKILLS_LINE.search(ANSI.sub("", details))
    if match is None:
        return None
    count, names = int(match.group(1)), match.group(2).strip()
    found = sorted(n.strip() for n in names.split(",") if n.strip()) if names else []
    return found if len(found) == count else None


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def codex_entries(prompt_input: str) -> list[tuple[str, str]] | None:
    """(name, shown description) for every entry of the Codex skill list, or None when there is none.

    The name is `<plugin>:<skill>` for a plugin skill. The description is the
    text Codex shows the model, which it shortens when skills share its budget;
    the trailing `(file: ...)` location is removed.
    """
    try:
        text = "\n".join(strings(json.loads(prompt_input)))
    except json.JSONDecodeError:
        return None
    # The heading on a line of its own: Codex's instructions also quote it in prose.
    heading = re.search(rf"^{re.escape(CODEX_HEADING)}[ \t]*$", text, re.M)
    if heading is None:
        return None
    # The list ends at the next heading; later bullets are not skills.
    block = text[heading.end() :]
    end = re.search(r"^#", block, re.M)
    block = block if end is None else block[: end.start()]
    entries = []
    # Any name without spaces, so no listed skill escapes the foreign check.
    for name, shown in re.findall(r"^- (\S+?):(?: (.*))?$", block, re.M):
        # Greedy, then strip only the last location, so a ` (file: ` inside the
        # text survives; rstrip covers CRLF output.
        entries.append((name, re.sub(r" \(file: [^()\n]*\)$", "", shown.rstrip())))
    return entries


def parse_codex_listing(prompt_input: str, plugin: str) -> list[tuple[str, str]] | None:
    """(skill, shown description) for each skill of `plugin`, or None when the output has no skill list."""
    entries = codex_entries(prompt_input)
    if entries is None:
        return None
    prefix = f"{plugin}:"
    return [(name[len(prefix) :], shown) for name, shown in entries if name.startswith(prefix)]


def foreign_skills(prompt_input: str, plugin: str) -> list[str]:
    """Listed skills that are neither the plugin's nor Codex's own. They share the budget."""
    entries = codex_entries(prompt_input) or []
    return sorted(
        name for name, _ in entries if not name.startswith(f"{plugin}:") and name not in CODEX_BUILTIN_SKILLS
    )


def parse_codex_skills(prompt_input: str, plugin: str) -> list[str] | None:
    """The skills of `plugin` in `codex debug prompt-input` output, or None when it has no skill list."""
    listing = parse_codex_listing(prompt_input, plugin)
    # No set(): a skill that Codex lists twice must show as a mismatch.
    return None if listing is None else sorted(skill for skill, _ in listing)


def routing_cases() -> list[tuple[str, str]]:
    """(phrase, skill) rows of tests/routing-cases.md, read by scripts/validate-skills.py itself."""
    spec = importlib.util.spec_from_file_location("validate_skills", VALIDATOR)
    assert spec and spec.loader, f"cannot load {VALIDATOR}"
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    rows, _ = validator.routing_rows(ROUTING.read_text(encoding="utf-8"))
    return rows


def hidden_phrases(listing: list[tuple[str, str]], cases: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(skill, phrase) for each routing phrase that the shown descriptions do not contain.

    Case-insensitive, as scripts/validate-skills.py compares a phrase with the
    full description.
    """
    shown = dict(listing)
    return sorted(
        {(skill, phrase) for phrase, skill in cases if skill in shown and phrase.lower() not in shown[skill].lower()}
    )


def codex_env(home: Path) -> dict[str, str]:
    """The caller's environment without any OpenAI or Codex setting, with a throwaway CODEX_HOME and HOME.

    A key or a sandbox flag from the caller would put a local run on a path
    that CI, which has neither, never takes. HOME moves too: Codex also lists
    the skills under ~/.agents/skills, and they share the skill-list budget.
    npm keeps the caller's cache and ~/.npmrc, so npx uses the same registry
    and does not download the CLI again.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "CODEX_"))}
    # npm reads npm_config_* case-insensitively; keep a key the caller already set.
    present = {k.lower() for k in env}
    for key, value in (("npm_config_cache", Path.home() / ".npm"), ("npm_config_userconfig", Path.home() / ".npmrc")):
        if key not in present:
            env[key] = str(value)
    env["CODEX_HOME"] = str(home)
    env["HOME"] = str(home / "home")
    (home / "home").mkdir(parents=True, exist_ok=True)
    return env


def export_tree(dest: Path) -> Path:
    """Copy the files a clone of this checkout would hold into dest, and return dest.

    Codex copies the whole marketplace root into its cache, ignored build
    output included, so the gate installs from this export: the files git
    tracks or would track, as they are in the working tree. Without git the
    checkout itself is the source.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
    )
    if listed.returncode != 0:
        return ROOT
    for name in listed.stdout.decode("utf-8").split("\0"):
        source = ROOT / name
        if name and source.is_file():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / name)
    return dest


def runner(command: list[str], cwd: Path, env: dict[str, str]):
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        argv = [*command, *args]
        try:
            return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, 124, "", f"timed out after 300 s: {shlex.join(argv)}")

    return run


def output(result: subprocess.CompletedProcess[str]) -> str:
    return ANSI.sub("", result.stdout + result.stderr).strip()


def compare(target: str, loaded: list[str] | None, skills: list[str], source: str) -> bool:
    """Print the verdict for one plugin; True when it loads exactly its skills."""
    if loaded is None:
        print(f"  {target}: no skill list in {source}")
        return False
    if loaded != skills:
        missing = sorted(set(skills) - set(loaded))
        extra = sorted(set(loaded) - set(skills))
        print(f"  {target}: loads {len(loaded)} skills, expected {len(skills)}")
        if missing:
            print(f"    missing: {', '.join(missing)}")
        if extra:
            print(f"    extra:   {', '.join(extra)}")
        return False
    print(f"  {target}: {len(loaded)} skills")
    return True


def check_claude(command: list[str], manifest: dict, expected: dict[str, list[str]]) -> int | None:
    """Failed plugin count, or None when Claude Code cannot even start the check."""
    marketplace = manifest["name"]
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
        run = runner(command, ROOT, env)

        version = run("--version")
        if version.returncode != 0:
            print(f"cannot run {shlex.join(command)!r}:\n{output(version)}", file=sys.stderr)
            return None
        print(f"  Claude Code {version.stdout.strip()}")

        # Errors fail; warnings do not, so --strict is never used.
        result = run("plugin", "validate", ".")
        if result.returncode != 0:
            print(output(result))
            print("FAIL: claude plugin validate reported errors")
            return None
        print("  claude plugin validate: no errors")

        result = run("plugin", "marketplace", "add", "./")
        if result.returncode != 0:
            print(output(result))
            print("FAIL: claude plugin marketplace add ./")
            return None

        failed = 0
        for plugin, skills in expected.items():
            target = f"{plugin}@{marketplace}"
            result = run("plugin", "install", target)
            if result.returncode != 0:
                print(f"  {target}: install failed\n{output(result)}")
                failed += 1
                continue
            details = run("plugin", "details", target)
            loaded = parse_skills(details.stdout) if details.returncode == 0 else None
            if not compare(target, loaded, skills, "`claude plugin details`"):
                if loaded is None:
                    print(output(details))
                failed += 1
        return failed


def check_codex(command: list[str], manifest: dict, expected: dict[str, list[str]]) -> int | None:
    """Failed plugin count, or None when Codex cannot even start the check.

    A bundle plugin also fails when Codex shortens a description so far that a
    routing phrase of tests/routing-cases.md is cut off: the model never sees
    that phrase, so it cannot route a request by it. The full-catalog plugin
    only reports its count; it overflows the budget by design.
    """
    marketplace = manifest["name"]
    if not ROUTING.is_file():
        print(f"cannot check Codex visibility: {ROUTING.relative_to(ROOT)} is missing", file=sys.stderr)
        return None
    cases = routing_cases()
    # Codex can leave log or database files behind while the directory goes away.
    with tempfile.TemporaryDirectory(prefix="codex-install-", ignore_cleanup_errors=True) as scratch:
        version_home = Path(tempfile.mkdtemp(prefix="home-", dir=scratch))
        version = runner(command, Path(scratch), codex_env(version_home))("--version")
        if version.returncode != 0:
            print(f"cannot run {shlex.join(command)!r}:\n{output(version)}", file=sys.stderr)
            return None
        print(f"  Codex {version.stdout.strip()}")
        source = export_tree(Path(tempfile.mkdtemp(prefix="tree-", dir=scratch)))

        failed = 0
        for plugin, skills in expected.items():
            target = f"{plugin}@{marketplace}"
            # One CODEX_HOME per plugin, so the skill list holds this plugin
            # only. The empty working directory keeps this repository's own
            # AGENTS.md and project config out of the session.
            home = Path(tempfile.mkdtemp(prefix="home-", dir=scratch))
            empty = Path(tempfile.mkdtemp(prefix="cwd-", dir=scratch))
            run = runner(command, empty, codex_env(home))

            result = run("plugin", "marketplace", "add", str(source), "--json")
            try:
                added = json.loads(result.stdout).get("marketplaceName") if result.returncode == 0 else None
            except (json.JSONDecodeError, AttributeError):
                added = None
            if added != marketplace:
                print(f"  {target}: codex plugin marketplace add gave {added!r}\n{output(result)}")
                failed += 1
                continue
            result = run("plugin", "add", target, "--json")
            if result.returncode != 0:
                print(f"  {target}: install failed\n{output(result)}")
                failed += 1
                continue
            prompt = run("debug", "prompt-input")
            listing = parse_codex_listing(prompt.stdout, plugin) if prompt.returncode == 0 else None
            loaded = None if listing is None else sorted(skill for skill, _ in listing)
            if not compare(target, loaded, skills, "`codex debug prompt-input`"):
                if loaded is None:
                    print(output(prompt)[-2000:])
                failed += 1
                continue
            foreign = foreign_skills(prompt.stdout, plugin)
            if foreign:
                # They share the budget, so every shortened description depends on this host.
                print(f"  {target}: other skills share the Codex list: {', '.join(foreign)}")
                failed += 1
            else:
                lost = hidden_phrases(listing or [], cases)
                total = len({(phrase, skill) for phrase, skill in cases if skill in skills})
                print(f"    {total - len(lost)} of {total} routing phrases visible in Codex")
                if plugin != marketplace:
                    for skill, phrase in lost:
                        print(f"    Codex cuts {phrase!r} off the description of {skill}; move it toward the start")
                    failed += bool(lost)
        return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install every plugin of this marketplace and check its skills.")
    parser.add_argument("--claude", help="command that runs the Claude Code CLI")
    parser.add_argument("--codex", help="command that runs the Codex CLI")
    args = parser.parse_args(argv)
    if not args.claude and not args.codex:
        parser.error("pass --claude, --codex, or both")

    manifest = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    expected = expected_skills(manifest)
    problems = entry_problems(manifest, expected)
    for problem in problems:
        print(f"  {problem}")
    listed = {e.get("name") for e in manifest.get("plugins", []) if isinstance(e, dict)}
    # A plugin with no entry is already reported; installing it only repeats that.
    present = {plugin: skills for plugin, skills in expected.items() if plugin in listed}

    failed = 0
    broken = False
    for check, command in ((check_claude, args.claude), (check_codex, args.codex)):
        if not command:
            continue
        result = check(shlex.split(command), manifest, present)
        if result is None:
            broken = True  # already printed; the other client still runs
        else:
            failed += result

    if broken:
        return 1
    if failed or problems:
        print(f"FAIL: {failed} plugin check(s) failed; {len(problems)} entry problem(s)")
        return 1
    print(f"OK: all {len(present)} plugins load exactly their skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
