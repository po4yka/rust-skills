#!/usr/bin/env python3
"""Validate the skill catalog.

Runs the checks that keep this repository installable. CI runs this script,
and so should you before you open a pull request:

    python3 scripts/validate-skills.py

Exit status is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
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
YAML_NULL_OR_BOOL = re.compile(r"^(?:~|null|true|false)$", re.IGNORECASE)
YAML_NUMBER = re.compile(
    r"^[+-]?(?:"
    r"0o[0-7_]+|0x[0-9a-f_]+|"
    r"(?:[0-9][0-9_]*)(?:\.[0-9_]*)?(?:e[+-]?[0-9]+)?|"
    r"\.[0-9_]+(?:e[+-]?[0-9]+)?|\.inf|\.nan"
    r")$",
    re.IGNORECASE,
)


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


def metadata_string(raw: str, where: str, label: str) -> str | None:
    """Decode one supported YAML string scalar and reject typed scalars."""
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            fail(where, f"{label} is not a valid double-quoted YAML string")
            return None
        if not isinstance(value, str):
            fail(where, f"{label} must be a YAML string")
            return None
        return value

    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            fail(where, f"{label} is not a valid single-quoted YAML string")
            return None
        inner = raw[1:-1]
        if "'" in inner.replace("''", ""):
            fail(where, f"{label} is not a valid single-quoted YAML string")
            return None
        return inner.replace("''", "'")

    if YAML_NULL_OR_BOOL.fullmatch(raw) or YAML_NUMBER.fullmatch(raw):
        fail(where, f"{label} must be a YAML string; quote {raw!r}")
        return None

    problem = plain_scalar_problem(raw)
    if problem:
        fail(where, f"{label} {problem}")
        return None
    return raw


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MIN_DESCRIPTION = 80
MAX_COMPATIBILITY = 500

failures: list[str] = []
descriptions: dict[str, str] = {}


def fail(where: str, message: str) -> None:
    failures.append(f"{where}: {message}")


def split_frontmatter(text: str, where: str) -> dict[str, object] | None:
    """Return the supported Agent Skills frontmatter subset."""
    if not text.startswith("---\n"):
        fail(where, "file does not start with a '---' frontmatter fence")
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        fail(where, "frontmatter fence is not closed")
        return None

    fields: dict[str, object] = {}
    metadata: dict[str, str] | None = None
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            if metadata is None:
                fail(
                    where,
                    f"only metadata can contain an indented mapping, found: {line.strip()!r}",
                )
                continue
            raw_key, sep, raw_value = line.strip().partition(":")
            raw_key = raw_key.strip()
            raw_value = raw_value.strip()
            if not sep or not raw_key or not raw_value:
                fail(where, f"metadata line is not 'key: value': {line.strip()!r}")
                continue
            key = metadata_string(raw_key, where, "metadata key")
            if key is None:
                continue
            if key in metadata:
                fail(where, f"duplicate metadata key: {key!r}")
                continue
            value = metadata_string(raw_value, where, f"metadata.{key}")
            if value is not None:
                metadata[key] = value
            continue
        key, sep, value = line.partition(":")
        if not sep:
            fail(where, f"frontmatter line is not 'key: value': {line!r}")
            continue
        key = key.strip()
        if key in fields:
            fail(where, f"duplicate frontmatter key: {key!r}")
            continue
        if key == "metadata" and not value.strip():
            metadata = {}
            fields[key] = metadata
        else:
            metadata = None
            fields[key] = value.strip()

    body = text[end + 5 :]
    if not body.strip():
        fail(where, "skill has frontmatter but no body")
    return fields


def check_rust_fences(text: str, where: str) -> None:
    """Reject a Rust fence that reaches the end of a Markdown file."""
    opened_at: int | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        fence = line.strip()
        if opened_at is not None:
            if fence == "```":
                opened_at = None
            continue
        if fence.startswith("```rust"):
            opened_at = lineno
    if opened_at is not None:
        fail(f"{where}:{opened_at}", "Rust code fence is not closed")


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

    declared_value = fields.get("name", "")
    declared = declared_value if isinstance(declared_value, str) else ""
    if declared != name:
        fail(where, f"name {declared!r} does not match the directory name {name!r}")
    if not NAME_RE.match(name):
        fail(where, f"directory name {name!r} is not lowercase kebab-case")
    if len(name) > MAX_NAME:
        fail(where, f"name is {len(name)} characters, the limit is {MAX_NAME}")

    for key, value in sorted(fields.items()):
        if isinstance(value, str):
            problem = plain_scalar_problem(value)
            if problem:
                fail(where, f"{key} {problem}. Rewrite the line so it needs no quoting.")
        elif key == "metadata" and isinstance(value, dict):
            pass
        else:
            fail(where, f"{key} must be a string")

    description_value = fields.get("description", "")
    description = description_value if isinstance(description_value, str) else ""
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
    elif not description.startswith("Use when "):
        fail(where, "description must start with 'Use when '")

    descriptions[name] = description

    license_value = fields.get("license")
    if license_value and license_value != "BSD-3-Clause":
        fail(where, f"license is {license_value!r}, this repository publishes BSD-3-Clause")

    compatibility = fields.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility:
            fail(where, "compatibility must be a non-empty string")
        elif len(compatibility) > MAX_COMPATIBILITY:
            fail(
                where,
                f"compatibility is {len(compatibility)} characters, the limit is "
                f"{MAX_COMPATIBILITY}",
            )

    allowed_tools = fields.get("allowed-tools")
    if allowed_tools is not None and (not isinstance(allowed_tools, str) or not allowed_tools):
        fail(where, "allowed-tools must be a non-empty space-separated string")

    metadata_value = fields.get("metadata")
    if metadata_value is not None and not isinstance(metadata_value, dict):
        fail(where, "metadata must be a mapping from string keys to string values")

    # Every pointer to a reference file must resolve, or the agent hits a dead
    # end halfway through a task. The skills name a reference in two ways: as a
    # Markdown link, and as a bare code span in a prose list. Check both, or the
    # check silently covers only part of the catalog.
    for markdown in skill_dir.rglob("*.md"):
        rel = str(markdown.relative_to(ROOT))
        text = markdown.read_text(encoding="utf-8")
        check_rust_fences(text, rel)
        targets = set(re.findall(r"\]\((references/[^)#]+)\)", text))
        targets |= set(re.findall(r"`(references/[^`]+\.md)`", text))
        for target in sorted(targets):
            if not (skill_dir / target).is_file():
                fail(rel, f"points at a missing reference file: {target}")


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

    text = ROUTING.read_text(encoding="utf-8")
    # `[^|]` in the phrase group keeps a three-column row out of this match.
    rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*([a-z0-9-]+)\s*\|\s*$", text, re.M)
    # A three-column row also names a skill that must not answer the phrase.
    guarded = re.findall(
        r"^\|\s*([^|]+?)\s*\|\s*([a-z0-9-]+)\s*\|\s*([a-z0-9-]+)\s*\|\s*$", text, re.M
    )
    separator = lambda cell: set(cell) <= {"-", " "}
    rows = [(phrase, skill) for phrase, skill in rows if not separator(phrase)]
    guarded = [row for row in guarded if not separator(row[0])]
    rows += [(phrase, skill) for phrase, skill, _ in guarded]
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

    # The other half of a decision that was already made once. Without it, an
    # edit to either description can quietly re-create the ambiguity.
    for phrase, owner, rival in guarded:
        if rival not in descriptions:
            fail("tests/routing-cases.md", f"names {rival!r} as a rival, which is not in skills/")
        elif phrase.lower() in descriptions[rival].lower():
            fail(
                f"skills/{rival}/SKILL.md",
                f"description claims {phrase!r}, which tests/routing-cases.md gives to "
                f"{owner!r}; drop the phrase or change the corpus",
            )

    routed = {skill for _, skill in rows}
    for name in sorted(set(descriptions) - routed):
        fail("tests/routing-cases.md", f"skill {name!r} has no routing case")


def check_readme_catalog(skill_names: set[str]) -> None:
    text = README.read_text(encoding="utf-8")
    catalog = re.search(r"(?ms)^## Catalog\s*$\n(.*?)(?=^##\s|\Z)", text)
    if catalog is None:
        fail("README.md", "Catalog section is missing")
        return

    rows = re.findall(
        r"^\|\s*\[([a-z0-9-]+)\]\(skills/([a-z0-9-]+)/SKILL\.md\)\s*\|",
        catalog.group(1),
        re.M,
    )
    counts: dict[str, int] = {}
    for label, target in rows:
        if label != target:
            fail("README.md", f"catalog row label {label!r} links to skill {target!r}")
        counts[target] = counts.get(target, 0) + 1

    linked = set(counts)
    for name in sorted(skill_names - linked):
        fail("README.md", f"skill {name!r} is missing from the catalog table")
    for name in sorted(linked - skill_names):
        fail("README.md", f"catalog links {name!r}, which is not in skills/")
    for name, count in sorted(counts.items()):
        if count != 1:
            fail("README.md", f"skill {name!r} appears {count} times in the catalog tables")


def check_readme_graph(skill_names: set[str]) -> None:
    """Keep the routing overview in sync with the catalog."""
    text = README.read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", text, re.S)
    if not blocks:
        fail("README.md", "Mermaid routing graph is missing")
        return

    graph = "\n".join(blocks)
    for name in sorted(skill_names):
        count = len(re.findall(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", graph))
        if count != 1:
            fail("README.md", f"skill {name!r} appears {count} times in the Mermaid routing graph")


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print("no skills/ directory", file=sys.stderr)
        return 1

    skill_dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir())
    for skill_dir in skill_dirs:
        check_skill(skill_dir)
    check_routing_cases(descriptions)
    skill_names = {d.name for d in skill_dirs}
    check_readme_catalog(skill_names)
    check_readme_graph(skill_names)

    if failures:
        print(f"FAIL: {len(failures)} problem(s) in {len(skill_dirs)} skill(s)\n")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(f"OK: {len(skill_dirs)} skills valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
