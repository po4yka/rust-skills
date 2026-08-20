#!/usr/bin/env python3
"""Validate the skill catalog.

Runs the checks that keep this repository installable and free of coupling to
the private codebases the skills came from. CI runs this script, and so should
you before you open a pull request:

    python3 scripts/validate-skills.py

Exit status is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
README = ROOT / "README.md"
ROUTING = ROOT / "tests" / "routing-cases.md"

# The Agent Skills spec allows six keys. This repository uses three; the other
# three stay allowed so a skill can declare them when it genuinely needs them.
# Any key outside this set is a hard packaging error on upload, not a warning.
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REQUIRED_KEYS = {"name", "description", "license"}

# A frontmatter value is written unquoted, so a YAML reader has to give it back
# unchanged. That reader is what an agent runtime and the skills CLI use, not
# the `key: value` split below, and the difference has shipped twice from this
# repository: a `: ` inside a description is a syntax error that drops the whole
# skill from the catalog, and a ` #` starts a comment that truncates the value
# without a warning. Neither is visible to a parser that splits on the first
# colon, so the rule lives here.
YAML_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"


def plain_scalar_problem(value: str) -> str | None:
    """Say why a YAML reader would not return `value` as written, or None."""
    if not value:
        return None
    if value[0] in YAML_INDICATORS:
        return f"starts with {value[0]!r}, which YAML reads as an indicator, not as text"
    if ": " in value or value.endswith(":"):
        return "contains ': ', which YAML reads as a second mapping key"
    if " #" in value:
        return "contains ' #', which YAML reads as the start of a comment"
    if "\t" in value:
        return "contains a tab, which YAML does not allow in a plain scalar"
    if value != value.strip():
        return "has leading or trailing whitespace, which YAML drops"
    return None


NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MIN_DESCRIPTION = 80

# Terms that mean a skill still carries coupling to a source codebase. Add a
# term here the moment one leaks; that is cheaper than finding it after publish.
FORBIDDEN = [
    "ripdpi",
    "cartory",
    "native/rust",
    "engine/rust",
    "/Users/",
    "mdtask",
    "openspec",
    "taskctl",
]

failures: list[str] = []
descriptions: dict[str, str] = {}


def fail(where: str, message: str) -> None:
    failures.append(f"{where}: {message}")


def split_frontmatter(text: str, where: str) -> dict[str, str] | None:
    """Return the frontmatter as a flat mapping, or None when it is malformed."""
    if not text.startswith("---\n"):
        fail(where, "file does not start with a '---' frontmatter fence")
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        fail(where, "frontmatter fence is not closed")
        return None

    fields: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            fail(where, f"frontmatter must stay flat, found an indented line: {line.strip()!r}")
            continue
        key, sep, value = line.partition(":")
        if not sep:
            fail(where, f"frontmatter line is not 'key: value': {line!r}")
            continue
        fields[key.strip()] = value.strip()

    body = text[end + 5 :]
    if not body.strip():
        fail(where, "skill has frontmatter but no body")
    return fields


def check_skill(skill_dir: Path) -> None:
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    where = str(skill_md.relative_to(ROOT))

    if not skill_md.is_file():
        fail(str(skill_dir.relative_to(ROOT)), "directory has no SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    fields = split_frontmatter(text, where)
    if fields is None:
        return

    unexpected = set(fields) - ALLOWED_KEYS
    if unexpected:
        fail(where, f"frontmatter key(s) outside the spec: {sorted(unexpected)}")
    missing = REQUIRED_KEYS - set(fields)
    if missing:
        fail(where, f"missing required frontmatter key(s): {sorted(missing)}")

    declared = fields.get("name", "")
    if declared != name:
        fail(where, f"name {declared!r} does not match the directory name {name!r}")
    if not NAME_RE.match(name):
        fail(where, f"directory name {name!r} is not lowercase-alphanumeric-with-hyphens")
    if len(name) > MAX_NAME:
        fail(where, f"name is {len(name)} characters, the limit is {MAX_NAME}")

    for key, value in sorted(fields.items()):
        problem = plain_scalar_problem(value)
        if problem:
            fail(where, f"{key} {problem}. Rewrite the line so it needs no quoting.")

    description = fields.get("description", "")
    if not description:
        fail(where, "description is empty")
    elif len(description) > MAX_DESCRIPTION:
        fail(where, f"description is {len(description)} characters, the limit is {MAX_DESCRIPTION}")
    elif len(description) < MIN_DESCRIPTION:
        # The spec sets no floor, but the description is the only text an agent
        # reads when it decides whether to open the skill. Too short cannot say
        # both what the skill covers and when to reach for it.
        fail(
            where,
            f"description is {len(description)} characters; state what the skill covers "
            f"and when to use it, in at least {MIN_DESCRIPTION}",
        )

    descriptions[name] = description

    license_value = fields.get("license")
    if license_value and license_value != "BSD-3-Clause":
        fail(where, f"license is {license_value!r}, this repository publishes BSD-3-Clause")

    # Every pointer to a reference file must resolve, or the agent hits a dead
    # end halfway through a task. The skills name a reference in two ways: as a
    # Markdown link, and as a bare code span in a prose list. Check both, or the
    # check silently covers only part of the catalog.
    for markdown in skill_dir.rglob("*.md"):
        rel = str(markdown.relative_to(ROOT))
        text = markdown.read_text(encoding="utf-8")
        targets = set(re.findall(r"\]\((references/[^)#]+)\)", text))
        targets |= set(re.findall(r"`(references/[^`]+\.md)`", text))
        for target in sorted(targets):
            if not (skill_dir / target).is_file():
                fail(rel, f"points at a missing reference file: {target}")


def check_forbidden_terms() -> None:
    for path in sorted(SKILLS_DIR.rglob("*.md")) + [README]:
        rel = str(path.relative_to(ROOT))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            lowered = line.lower()
            for term in FORBIDDEN:
                if term.lower() in lowered:
                    fail(f"{rel}:{lineno}", f"leaked source-codebase term {term!r}")


def check_routing_cases(descriptions: dict[str, str]) -> None:
    """Every phrase in the routing corpus must survive in its skill's description.

    An agent reads only the description when it decides whether to open a skill,
    so a description edit that drops a term silently breaks routing for it. This
    is a static check: it cannot prove a model routes correctly, only that the
    catalog still claims the terms it promised.
    """
    if not ROUTING.is_file():
        fail("tests/routing-cases.md", "routing corpus is missing")
        return

    rows = re.findall(r"^\|\s*(.+?)\s*\|\s*([a-z0-9-]+)\s*\|\s*$", ROUTING.read_text(encoding="utf-8"), re.M)
    rows = [(phrase, skill) for phrase, skill in rows if not set(phrase) <= {"-", " "}]
    if not rows:
        fail("tests/routing-cases.md", "routing corpus has no rows")
        return

    for phrase, skill in rows:
        if skill not in descriptions:
            fail("tests/routing-cases.md", f"routes {phrase!r} to {skill!r}, which is not in skills/")
        elif phrase.lower() not in descriptions[skill].lower():
            fail(
                f"skills/{skill}/SKILL.md",
                f"description no longer contains the routing phrase {phrase!r}; "
                f"restore it or update tests/routing-cases.md",
            )

    routed = {skill for _, skill in rows}
    for name in sorted(set(descriptions) - routed):
        fail("tests/routing-cases.md", f"skill {name!r} has no routing case")


def check_readme_catalog(skill_names: set[str]) -> None:
    linked = set(re.findall(r"skills/([a-z0-9-]+)/SKILL\.md", README.read_text(encoding="utf-8")))
    for name in sorted(skill_names - linked):
        fail("README.md", f"skill {name!r} is missing from the catalog table")
    for name in sorted(linked - skill_names):
        fail("README.md", f"catalog links {name!r}, which is not in skills/")


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print("no skills/ directory", file=sys.stderr)
        return 1

    skill_dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir())
    for skill_dir in skill_dirs:
        check_skill(skill_dir)
    check_forbidden_terms()
    check_routing_cases(descriptions)
    check_readme_catalog({d.name for d in skill_dirs})

    if failures:
        print(f"FAIL: {len(failures)} problem(s) in {len(skill_dirs)} skill(s)\n")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(f"OK: {len(skill_dirs)} skills valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
