#!/usr/bin/env python3
"""Validate the skill catalog.

Runs the checks that keep this repository installable. CI runs this script,
and so should you before you open a pull request:

    python3 scripts/validate-skills.py

    python3 scripts/validate-skills.py --report budget      # per-skill sizes
    python3 scripts/validate-skills.py --report cross-refs  # partial-install gaps

Exit status is 0 when every check passes, 1 otherwise. A report run prints
the report and then runs every check as usual.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
README = ROOT / "README.md"
ROUTING = ROOT / "tests" / "routing-cases.md"
BUNDLES = ROOT / "bundles.toml"
SNIPPET = ROOT / "AGENTS.snippet.md"
NEGATIVE = ROOT / "evals" / "routing" / "negative-cases.md"
CEILINGS = ROOT / "scripts" / "catalog-ceilings.toml"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

# The Agent Skills spec allows six keys. This repository allows exactly three
# (AGENTS.md, "The SKILL.md contract"). The other three are not harmless:
# `allowed-tools` pre-approves tools in Claude Code, so a one-line frontmatter
# edit would widen what every consumer's agent may run without a prompt, and
# `metadata` and `compatibility` are free text that no gate here reads.
REQUIRED_KEYS = {"name", "description", "license"}
ALLOWED_KEYS = REQUIRED_KEYS

# Characters that a reader does not see and a model does: C0 and C1 controls
# (a YAML reader rejects most of them, which drops the whole skill), zero-width
# and bidirectional formatting characters, and the Unicode tag block, which can
# carry a whole hidden instruction inside the one text every agent reads. Tab
# and newline are the only controls a Markdown file in this catalog needs.
INVISIBLE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e"
    "\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb\U000e0000-\U000e007f]"
)

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


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MIN_DESCRIPTION = 80
# The Agent Skills spec recommends a SKILL.md under 500 lines. Longer material
# belongs in references/, which the agent opens only when it needs it.
MAX_SKILL_LINES = 500

# Token estimates. The gate counts characters and divides by 2.5, so every
# host computes the same number with no tokenizer and no network. The ratio is
# calibrated, not assumed: `claude plugin details` (Claude Code 2.1.316, on
# 2026-10-31) projected 2.37 characters per token for the descriptions of this
# catalog, per-entry overhead included, and 2.58 for the bodies; the record is
# research/token-calibration-2026-10.md. The common chars/3.5 rule undercounts
# this catalog by 25 % to 32 %. `--report budget` also prints a cl100k count
# when tiktoken happens to be installed; the gate never reads it, because a
# verdict that depends on an optional package is not reproducible, and cl100k
# is not the tokenizer of any Claude model. What the calibration does not prove:
# `claude plugin details` does not say how it counts, and its ratio is 2.57 to
# 2.61 for every body, prose-heavy or code-heavy, which a real tokenizer would
# not give. It is most likely a character estimate itself, so no Claude
# tokenizer count backs this ratio yet; the limits below are character budgets.
CHARS_PER_TOKEN = 2.5

# The always-on skill listing. Claude Code keeps it within 1% of the context
# window (about 2,000 tokens on a 200K window) and drops whole descriptions
# when it overflows. A bundle is the unit a consumer installs, so each bundle
# must fit that budget: 5,000 characters is 2,000 estimated tokens.
MAX_BUNDLE_DESCRIPTIONS = 5_000
# The whole catalog does not fit a 200K window at any useful size. This cap
# bounds the full install, and the warning gives notice before it is reached.
MAX_TOTAL_DESCRIPTIONS = 20_000
WARN_TOTAL_DESCRIPTIONS = 18_000

# Claude Code re-injects an invoked skill body after context compaction and
# keeps at most 5,000 tokens of it. The margin covers estimate error.
MAX_BODY_TOKENS = 4_800
WARN_BODY_TOKENS = 4_500

# The router snippet is pasted into a consuming repository's always-on
# instructions, so it has to stay small.
MAX_SNIPPET_LINES = 60

# The shortest routing phrase the corpus accepts. NDK, LTO, and PDB are real
# three-letter tokens a user pastes; anything shorter matches by accident.
MIN_ROUTING_PHRASE = 3

failures: list[str] = []
warnings: list[str] = []
descriptions: dict[str, str] = {}
bodies: dict[str, str] = {}


def fail(where: str, message: str) -> None:
    failures.append(f"{where}: {message}")


def warn(where: str, message: str) -> None:
    warnings.append(f"{where}: {message}")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def frontmatter_body(text: str) -> str:
    end = text.find("\n---\n", 3)
    return text[end + 5 :] if text.startswith("---\n") and end != -1 else text


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
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            fail(where, f"indented frontmatter line; only name, description, and license are allowed: {line.strip()!r}")
            continue
        key, sep, value = line.partition(":")
        if not sep:
            fail(where, f"frontmatter line is not 'key: value': {line!r}")
            continue
        key = key.strip()
        if key in fields:
            fail(where, f"duplicate frontmatter key: {key!r}")
            continue
        fields[key] = value.strip()

    body = text[end + 5 :]
    if not body.strip():
        fail(where, "skill has frontmatter but no body")
    return fields


# A fence is the unit every cargo gate reads, and checks/gen.py recognises
# only a line that starts with exactly three backticks and `rust`. Any other
# spelling of a Rust fence (```rs, ```Rust, ~~~rust, ````rust, ``` rust) is
# silently skipped by the compile check, so the validator rejects it here.
FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
FENCE_LANGUAGES = {
    "rust", "bash", "toml", "yaml", "kotlin", "swift", "text",
    "c", "json", "sql", "xml", "gdb", "lldb", "javascript",
}
RUST_FENCE = re.compile(r"rust(?:,run|,ignore|,compile_fail(?:,E\d{4})*)?")


def check_fences(text: str, where: str) -> str:
    """Check every code fence and return the prose: the text with fenced lines blanked."""
    prose: list[str] = []
    opened_at: int | None = None
    for lineno, line in enumerate(text.split("\n"), 1):
        if opened_at is not None:
            prose.append("")
            if line.strip() == "```":
                opened_at = None
            continue
        match = FENCE_OPEN.match(line)
        if match is None:
            prose.append(line)
            continue
        prose.append("")
        opened_at = lineno
        marker, info = match.groups()
        at = f"{where}:{lineno}"
        if marker != "```":
            fail(at, f"fence {marker!r}: use exactly three backticks, the only fence checks/gen.py reads")
        if not info.strip():
            fail(at, f"untagged code fence; tag it with one of {sorted(FENCE_LANGUAGES)}")
            continue
        if info != info.strip():
            fail(at, f"fence info {info!r} has surrounding space; write ```{info.strip()}")
        info = info.strip()
        language = info.split(",", 1)[0]
        if language.lower() in ("rust", "rs"):
            if not RUST_FENCE.fullmatch(info):
                fail(at, f"Rust fence {info!r}: use rust, rust,run, rust,ignore, or rust,compile_fail[,E0000...]")
        elif language not in FENCE_LANGUAGES:
            fail(at, f"fence language {language!r} is not in {sorted(FENCE_LANGUAGES)}")
    if opened_at is not None:
        fail(f"{where}:{opened_at}", "code fence is not closed")
    return "\n".join(prose)


INLINE_LINK = re.compile(r"\]\(([^)]*)\)")
REFERENCE_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.M)
HTML_LINK = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']*)["']""", re.I)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def link_targets(prose: str) -> set[str]:
    """Every link target in Markdown prose: inline, reference-style, and HTML."""
    text = INLINE_CODE.sub("", prose)
    targets = set()
    for raw in INLINE_LINK.findall(text):
        raw = re.sub(r'\s+"[^"]*"\s*$', "", raw.strip())
        targets.add(raw.strip("<>"))
    targets |= {raw.strip("<>") for raw in REFERENCE_DEFINITION.findall(text)}
    targets |= set(HTML_LINK.findall(text))
    return targets


def check_skill_files(skill_dir: Path) -> None:
    """Shape, characters, fences, and links of every file an install copies.

    `npx skills add` and both plugin clients copy the whole skill directory,
    so every file in it ships, and an installed skill carries only its own
    directory: a link that leaves it is dead after the install.
    """
    skill_md = skill_dir / "SKILL.md"
    for path in sorted(skill_dir.rglob("*")):
        rel = path.relative_to(skill_dir)
        where = str(path.relative_to(ROOT))
        if path.is_symlink():
            fail(where, "is a symlink; an install copies it, and it can point outside the skill")
        elif path.is_file() and not (
            rel.parts == ("SKILL.md",)
            or (len(rel.parts) == 2 and rel.parts[0] == "references" and rel.suffix == ".md")
        ):
            fail(where, "only SKILL.md and references/*.md may live in a skill; every other file ships to consumers")

    linked_from_skill: set[Path] = set()
    for markdown in sorted(skill_dir.rglob("*.md")):
        if markdown.is_symlink():
            continue
        rel = str(markdown.relative_to(ROOT))
        try:
            text = markdown.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            fail(rel, f"is not UTF-8: {error}")
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            for match in INVISIBLE.finditer(line):
                fail(
                    f"{rel}:{lineno}",
                    f"contains invisible character U+{ord(match.group()):04X} at column "
                    f"{match.start() + 1}; a reader cannot see what an agent reads",
                )
        prose = check_fences(text, rel)

        # A bare code span in a prose list is the other way the skills name a
        # reference, so it has to resolve too.
        for target in sorted(set(re.findall(r"`(references/[^`]+\.md)`", text))):
            if not (skill_dir / target).is_file():
                fail(rel, f"points at a missing reference file: {target}")
            elif markdown == skill_md:
                linked_from_skill.add((skill_dir / target).resolve())

        for target in sorted(link_targets(prose)):
            path = target.split("#", 1)[0]
            if not path or re.match(r"[a-z][a-z0-9+.-]*:", path):
                continue
            resolved = (markdown.parent / path).resolve()
            if not resolved.is_relative_to(skill_dir.resolve()):
                fail(rel, f"links outside its skill directory: {target}; name the other skill instead")
            elif not resolved.exists():
                fail(rel, f"points at a missing file: {target}")
            elif resolved == markdown.resolve():
                fail(rel, f"links to itself: {target}; the reader is already in this file, so delete the pointer")
            elif markdown == skill_md:
                linked_from_skill.add(resolved)

        for span in sorted(set(re.findall(r"\bskills/[a-z0-9-]+/[^\s`)]*", text))):
            fail(rel, f"names a repository path: {span}; name the skill, or use a path relative to this file")

    # A reference that SKILL.md never names is reachable only by chance: the
    # agent loads SKILL.md, and a pointer two files deep is one it rarely follows.
    for reference in sorted((skill_dir / "references").glob("*.md")):
        if reference.resolve() not in linked_from_skill:
            fail(
                str(reference.relative_to(ROOT)),
                "is not linked from SKILL.md; link it at the point of need with the condition to read it",
            )


def check_skill(skill_dir: Path) -> None:
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    where = str(skill_md.relative_to(ROOT))

    if not skill_md.is_file():
        fail(str(skill_dir.relative_to(ROOT)), "directory has no SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    lines = len(text.splitlines())
    if lines > MAX_SKILL_LINES:
        fail(where, f"SKILL.md has {lines} lines, the limit is {MAX_SKILL_LINES}; move material to references/")
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
    bodies[name] = frontmatter_body(text)

    license_value = fields.get("license")
    if license_value and license_value != "BSD-3-Clause":
        fail(where, f"license is {license_value!r}, this repository publishes BSD-3-Clause")

    check_skill_files(skill_dir)


def routing_rows(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """(phrase, skill) for every row of tests/routing-cases.md, and (phrase, owner, rival) for the guarded ones.

    checks/plugin_install.py reads the corpus through this function, so both
    gates see the same rows.
    """
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
    return rows, guarded


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
    rows, guarded = routing_rows(text)
    if not rows:
        fail("tests/routing-cases.md", "routing corpus has no rows")
        return

    # A row the two patterns above do not read is a row no gate checks: a
    # backticked skill name, a fourth column, or a leading space drops it in
    # silence. Every table line must be a header, a separator, or a row.
    lines = text.split("\n")
    row_line = re.compile(r"^\|\s*[^|]+?\s*\|\s*[a-z0-9-]+\s*\|(?:\s*[a-z0-9-]+\s*\|)?\s*$")
    separator_line = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if separator_line.match(line) or separator_line.match(following):
            continue
        if not row_line.match(line):
            fail(f"tests/routing-cases.md:{index + 1}", f"table line is not a routing row, so no gate reads it: {line.strip()!r}")

    for phrase, skill in rows:
        # A phrase that every description shares ("Use when") or a one- or
        # two-letter token passes the substring check without saying anything
        # about this skill.
        if len(phrase) < MIN_ROUTING_PHRASE:
            fail("tests/routing-cases.md", f"phrase {phrase!r} is shorter than {MIN_ROUTING_PHRASE} characters")
            continue
        # A guarded row names its rival; the guard below reports that case.
        named = {rival for p_, owner, rival in guarded if p_ == phrase and owner == skill}
        rivals = sorted(
            other
            for other, description in descriptions.items()
            if other != skill
            and other not in named
            and phrase.lower() in description_claims(description).lower()
        )
        if rivals:
            fail(
                "tests/routing-cases.md",
                f"phrase {phrase!r} routes to {skill!r} but the description of {', '.join(rivals)} "
                f"claims it too; pick a phrase only {skill!r} claims, or move the other mention "
                f"into a 'Not for' clause",
            )

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


def load_toml(path: Path, where: str) -> dict | None:
    if not path.is_file():
        fail(where, "file is missing")
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        fail(where, f"is not valid TOML: {error}")
        return None


def load_bundles() -> dict[str, list[str]]:
    """Return bundle name -> ordered skill names, as bundles.toml declares them."""
    data = load_toml(BUNDLES, "bundles.toml")
    if data is None:
        return {}
    table = data.get("bundles")
    if not isinstance(table, dict) or not table:
        fail("bundles.toml", "has no [bundles.<name>] tables")
        return {}
    bundles: dict[str, list[str]] = {}
    for name, entry in table.items():
        skills = entry.get("skills") if isinstance(entry, dict) else None
        if not NAME_RE.match(name):
            fail("bundles.toml", f"bundle name {name!r} is not lowercase kebab-case")
        if not isinstance(skills, list) or not all(isinstance(x, str) for x in skills) or not skills:
            fail("bundles.toml", f"bundle {name!r} needs a non-empty skills = [...] list")
            continue
        bundles[name] = skills
    return bundles


def bundle_index(bundles: dict[str, list[str]]) -> dict[str, str]:
    return {skill: name for name, skills in bundles.items() for skill in skills}


def check_bundles(bundles: dict[str, list[str]], skill_names: set[str]) -> None:
    """Every skill installs with exactly one bundle, and README offers every bundle."""
    seen: dict[str, list[str]] = {}
    for bundle, skills in bundles.items():
        for skill in skills:
            seen.setdefault(skill, []).append(bundle)
            if skill not in skill_names:
                fail("bundles.toml", f"bundle {bundle!r} lists {skill!r}, which is not in skills/")
    for skill in sorted(skill_names):
        owners = seen.get(skill, [])
        if len(owners) != 1:
            where = "no bundle" if not owners else f"{len(owners)} bundles: {', '.join(owners)}"
            fail("bundles.toml", f"skill {skill!r} is in {where}; put it in exactly one")

    text = README.read_text(encoding="utf-8")
    install = re.search(r"(?ms)^## Install\s*$\n(.*?)(?=^##\s|\Z)", text)
    if install is None:
        fail("README.md", "Install section is missing")
        return
    rows: set[str] = set()
    skills_col = None  # index of the "Skills" column in the current table, if it has one
    for line in install.group(1).splitlines():
        if not line.startswith("|"):
            skills_col = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "Skills" in cells:
            skills_col = cells.index("Skills")
            continue
        match = re.fullmatch(r"`?([a-z0-9-]+)`?", cells[0])
        if match is None:
            continue
        bundle = match.group(1)
        rows.add(bundle)
        # The count is written by hand, so it falls behind when a skill joins a bundle.
        if bundle in bundles and skills_col is not None and skills_col < len(cells):
            shown, actual = cells[skills_col], len(bundles[bundle])
            if shown != str(actual):
                fail("README.md", f"bundle {bundle!r} shows {shown} skills in the Install table; "
                                  f"bundles.toml lists {actual}")
    for bundle in sorted(set(bundles) - rows):
        fail("README.md", f"bundle {bundle!r} has no row in the Install table")

    # The per-bundle install commands are written by hand too. A `# <bundle>` comment
    # opens each one; the skill list after it is the `for s in ...;` loop of the `gh skill`
    # block or the `--skill ...` list of the `npx skills add` block.
    commands = re.findall(
        r"^# ([a-z0-9-]+)\n(?:for s in ([^;\n]+);|npx skills add \S+ --skill ([^\n]+))",
        install.group(1),
        re.M,
    )
    listed: dict[str, int] = {}
    for bundle, loop, flags in commands:
        names = (loop or flags).split()
        listed[bundle] = listed.get(bundle, 0) + 1
        if bundle not in bundles:
            fail("README.md", f"an install command is labelled {bundle!r}, which is not in bundles.toml")
        elif names != bundles[bundle]:
            fail(
                "README.md",
                f"the install command for bundle {bundle!r} lists {names}; bundles.toml lists "
                f"{bundles[bundle]} in that order",
            )
    if commands:
        for bundle in sorted(bundles):
            if listed.get(bundle, 0) != 2:
                fail(
                    "README.md",
                    f"bundle {bundle!r} has {listed.get(bundle, 0)} labelled install commands; "
                    f"the gh skill and npx blocks need one each",
                )


def load_json(path: Path, where: str) -> dict | None:
    if not path.is_file():
        fail(where, "file is missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(where, f"is not valid JSON: {error}")
        return None
    if not isinstance(data, dict):
        fail(where, "must hold a JSON object")
        return None
    return data


MARKETPLACE_KEYS = {"name", "owner", "description", "plugins"}
PLUGIN_ENTRY_KEYS = {"name", "source", "description", "license", "skills", "author", "homepage", "repository"}
# Plugin components a Claude Code or Codex client loads from a plugin root.
PLUGIN_COMPONENTS = (
    "hooks", ".mcp.json", ".lsp.json", ".app.json", "commands", "agents",
    "output-styles", "monitors", "bin", "settings.json",
)

# "13 Rust agent skills" in a plugin description. The /plugin panel shows it
# before an install, so a stale count misleads a consumer about what they get.
SKILL_COUNT = re.compile(r"\b(\d+) Rust agent skills\b")


def check_marketplace(bundles: dict[str, list[str]], skill_names: set[str]) -> None:
    """The marketplace offers the full catalog and each bundle, exactly as bundles.toml has them.

    Claude Code and Codex both read this one file, and each entry is the whole
    plugin manifest. Codex installs an entry only when no plugin.json at the
    root names a different plugin, so there is no plugin.json. A plugin version
    is the commit SHA only while no `version` is set; one `version` string that
    is not bumped freezes every consumer, so none is allowed (docs/releasing.md).
    An entry loads only the skill directories it lists only when its source is
    the repository root, so every entry uses "./".
    """
    where = ".claude-plugin/marketplace.json"
    # Every root manifest that Claude Code or Codex reads. lexists: a dangling
    # symlink is still a manifest path a client tries to open.
    for manifest in (PLUGIN_MANIFEST, ROOT / ".codex-plugin" / "plugin.json", ROOT / "plugin.json"):
        if os.path.lexists(manifest):
            fail(
                str(manifest.relative_to(ROOT)),
                "must not exist; Codex then refuses every bundle whose name differs from it. "
                "Put plugin metadata in the marketplace entries",
            )
    # Every entry has source "./", so the plugin root is the repository root,
    # and a client loads whatever plugin component it finds there: hooks run
    # commands on the consumer's machine, an MCP or LSP server starts a
    # process, and agents and commands add instructions no skill gate reads.
    # The catalog ships skills only.
    for component in PLUGIN_COMPONENTS:
        if os.path.lexists(ROOT / component):
            fail(
                component,
                "must not exist at the repository root: every plugin's source is \"./\", so a "
                "client installs it next to the skills. This catalog ships skills only",
            )
    market = load_json(MARKETPLACE, where)
    if market is None:
        return
    for key in sorted(set(market) - MARKETPLACE_KEYS - {"version"}):
        fail(where, f"top-level key {key!r} is not allowed; use only {sorted(MARKETPLACE_KEYS)}")

    full = market.get("name")
    if not isinstance(full, str):
        fail(where, "name must be a string")
        return
    if "version" in market:
        fail(where, "sets a top-level `version`; remove it")

    entries = market.get("plugins")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        fail(where, "plugins must be a list of objects")
        return
    # None marks the full catalog, which loads the default skills/ directory.
    expected: dict[str, list[str] | None] = {full: None}
    expected |= {f"{full}-{bundle}": skills for bundle, skills in bundles.items()}
    seen: list[str] = []
    for index, entry in enumerate(entries):
        name = entry.get("name")
        label = f"plugins[{index}] {name!r}"
        if not isinstance(name, str):
            fail(where, f"plugins[{index}] name must be a string")
            continue
        seen.append(name)
        for key in sorted(set(entry) - PLUGIN_ENTRY_KEYS - {"version"}):
            fail(
                where,
                f"{label} sets {key!r}; an entry may set only {sorted(PLUGIN_ENTRY_KEYS)}, because "
                f"hooks, mcpServers, agents, commands, and strict change what a consumer runs",
            )
        if name not in expected:
            fail(where, f"{label} matches no bundle in bundles.toml; name it {full}-<bundle>")
            continue
        if entry.get("source") != "./":
            fail(where, f'{label} source must be "./", the repository root, or the entry loads every skill')
        if "version" in entry:
            fail(where, f"{label} sets `version`; remove it so the version stays the commit SHA")
        if entry.get("license") != "BSD-3-Clause":
            fail(where, f'{label} license must be "BSD-3-Clause"')
        skills = expected[name]
        count = len(skill_names) if skills is None else len(skills)
        if skills is None:
            if "skills" in entry:
                fail(where, f"{label} is the full catalog; it must not list skills, so skills/ loads whole")
        else:
            want = [f"./skills/{skill}" for skill in skills]
            if entry.get("skills") != want:
                fail(where, f"{label} skills differ from bundles.toml; list {want} in that order")
        description = entry.get("description")
        stated = SKILL_COUNT.findall(description) if isinstance(description, str) else []
        if stated != [str(count)]:
            fail(where, f"{label} description must say '{count} Rust agent skills' once")
    for name in expected:
        if seen.count(name) != 1:
            fail(where, f"plugin {name!r} appears {seen.count(name)} times; list it exactly once")


def load_ceilings() -> dict:
    """The ratchet: values above a hard limit that the catalog may keep, never grow."""
    if not CEILINGS.is_file():
        return {}
    return load_toml(CEILINGS, "scripts/catalog-ceilings.toml") or {}


# A commit that adds a cross-bundle fallback sentence may raise that skill's
# body_tokens ceiling by this much per fallback it adds: about one sentence.
FALLBACK_SENTENCE_TOKENS = 60


def check_ceilings_against(ref: str, ceilings: dict) -> None:
    """The ratchet only turns one way: no entry may be added or raised against `ref`.

    The per-value checks compare the tree with the ceilings file, so they
    cannot see an edit to the file itself. This compares the file with the
    one at `ref`, the merge base in CI. The one exception is the documented
    one: body_tokens may rise by FALLBACK_SENTENCE_TOKENS for each cross-bundle
    reference the same change resolves.
    """
    where = "scripts/catalog-ceilings.toml"
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:scripts/catalog-ceilings.toml"],
        capture_output=True,
        text=True,
    )
    if shown.returncode != 0:
        if "does not exist" in shown.stderr or "exists on disk, but not in" in shown.stderr:
            print(f"ceilings: {ref} has no ceilings file; nothing to compare")
            return
        fail(where, f"cannot read the ceilings file at {ref}: {shown.stderr.strip()}")
        return
    try:
        base = tomllib.loads(shown.stdout)
    except tomllib.TOMLDecodeError as error:
        fail(where, f"the ceilings file at {ref} is not valid TOML: {error}")
        return
    before = len(failures)
    base_refs = base.get("cross_refs", {})
    current_refs = ceilings.get("cross_refs", {})
    for section, entries in sorted(ceilings.items()):
        if not isinstance(entries, dict):
            continue
        for key, value in sorted(entries.items()):
            old = base.get(section, {}).get(key)
            if old is not None and value <= old:
                continue
            if section == "body_tokens" and old is not None:
                resolved = base_refs.get(key, 0) - current_refs.get(key, 0)
                if resolved > 0 and value - old <= resolved * FALLBACK_SENTENCE_TOKENS:
                    continue
            change = f"added at {value}" if old is None else f"raised from {old} to {value}"
            fail(
                where,
                f"[{section}] {key} is {change} against {ref}. The ratchet only shrinks: move "
                f"material to references/ or shorten the text instead",
            )
    if len(failures) == before:
        print(f"ceilings: no entry added or raised against {ref}")


def check_description_budget(bundles: dict[str, list[str]], ceilings: dict) -> None:
    total = sum(len(d) for d in descriptions.values())
    ceiling = ceilings.get("description", {}).get("total", 0)
    limit = max(MAX_TOTAL_DESCRIPTIONS, ceiling)
    print(
        f"descriptions: {total:,} characters, ~{estimate_tokens('x' * total):,} tokens "
        f"in {len(descriptions)} skills (limit {limit:,})"
    )
    if total > limit:
        fail(
            "skills/*/SKILL.md",
            f"descriptions total {total:,} characters, the limit is {limit:,}; shorten a "
            f"description instead of growing the always-on listing",
        )
    elif total > WARN_TOTAL_DESCRIPTIONS:
        warn("skills/*/SKILL.md", f"descriptions total {total:,} characters, over {WARN_TOTAL_DESCRIPTIONS:,}")
    if ceiling > MAX_TOTAL_DESCRIPTIONS and total < ceiling:
        warn("scripts/catalog-ceilings.toml", f"lower [description] total to {max(total, MAX_TOTAL_DESCRIPTIONS)}")

    accepted = ceilings.get("bundle_descriptions", {})
    for bundle, skills in bundles.items():
        size = sum(len(descriptions.get(skill, "")) for skill in skills)
        limit = max(MAX_BUNDLE_DESCRIPTIONS, accepted.get(bundle, 0))
        print(f"  bundle {bundle}: {size:,} characters, ~{estimate_tokens('x' * size):,} tokens (limit {limit:,})")
        if size > limit:
            fail(
                "bundles.toml",
                f"bundle {bundle!r} descriptions total {size:,} characters, the limit is "
                f"{limit:,}; {MAX_BUNDLE_DESCRIPTIONS:,} is about 2,000 tokens, the skill listing "
                f"of a 200K-context client. Shorten a description instead of growing the bundle",
            )
        elif bundle in accepted and size < accepted[bundle]:
            warn("scripts/catalog-ceilings.toml", f"lower bundle_descriptions.{bundle} to {max(size, MAX_BUNDLE_DESCRIPTIONS)}")
    for bundle in sorted(set(accepted) - set(bundles)):
        fail("scripts/catalog-ceilings.toml", f"bundle_descriptions names {bundle!r}, which is not in bundles.toml")


def check_body_tokens(ceilings: dict) -> None:
    accepted = ceilings.get("body_tokens", {})
    for name, body in sorted(bodies.items()):
        where = f"skills/{name}/SKILL.md"
        tokens = estimate_tokens(body)
        ceiling = accepted.get(name)
        if tokens > MAX_BODY_TOKENS:
            if ceiling is None:
                fail(
                    where,
                    f"body is ~{tokens:,} estimated tokens, the limit is {MAX_BODY_TOKENS:,}; "
                    f"move trailing sections to references/",
                )
            elif tokens > ceiling:
                fail(
                    where,
                    f"body grew to ~{tokens:,} estimated tokens; its accepted ceiling is "
                    f"{ceiling:,} and the limit is {MAX_BODY_TOKENS:,}. Move material to references/",
                )
            elif tokens < ceiling:
                warn("scripts/catalog-ceilings.toml", f"lower body_tokens.{name} to {tokens}")
        elif ceiling is not None:
            warn("scripts/catalog-ceilings.toml", f"remove body_tokens.{name}: the body is under the limit")
        elif tokens > WARN_BODY_TOKENS:
            warn(where, f"body is ~{tokens:,} estimated tokens, over {WARN_BODY_TOKENS:,}")
    for name in sorted(set(accepted) - set(bodies)):
        fail("scripts/catalog-ceilings.toml", f"body_tokens names {name!r}, which is not in skills/")


def check_snippet(skill_names: set[str], bundles: dict[str, list[str]] | None = None) -> None:
    """The always-on router must route to every skill once, stay small, and follow the bundles."""
    if not SNIPPET.is_file():
        fail("AGENTS.snippet.md", "router snippet is missing")
        return
    text = SNIPPET.read_text(encoding="utf-8")
    lines = len(text.splitlines())
    if lines > MAX_SNIPPET_LINES:
        fail("AGENTS.snippet.md", f"has {lines} lines, the limit is {MAX_SNIPPET_LINES}")
    for name in sorted(skill_names):
        count = len(re.findall(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", text))
        if count != 1:
            fail("AGENTS.snippet.md", f"skill {name!r} appears {count} times; route to it exactly once")
    for path in re.findall(r"skills/[a-z0-9-]+/", text):
        fail("AGENTS.snippet.md", f"names a repository path {path!r}; name the skill only")
    # The snippet tells a consumer to delete the rows of a bundle they did not
    # install, which works only while the rows stay grouped in bundles.toml order.
    if bundles:
        order = [skill for skills in bundles.values() for skill in skills]
        routed = [row for row in re.findall(r"\|\s*([a-z0-9-]+)\s*\|\s*$", text, re.M) if row in order]
        if routed != [skill for skill in order if skill in routed]:
            fail("AGENTS.snippet.md", "rows are not in bundles.toml order; group them by bundle, in that order")


# A sibling named as "the `x` skill" (or "`x` and `y` skills"). An installed
# bundle has no sibling outside it, so the reference must not be the only place
# the reader learns what to do.
# A sibling skill is named in a code span: "the `x` skill", "`x` and `y` skills",
# a list such as "`x` (async), `y` (FFI)", or a table cell. Every such span
# counts; the old pattern saw only the "`x` skill" form and missed about half.
SIBLING_REF = re.compile(r"`([a-z0-9-]+)`")
CODE_SPAN = re.compile(r"`([^`\n]+)`")


def prose_units(text: str) -> list[list[tuple[int, str]]]:
    """Split Markdown into paragraphs, list items, table rows, and headings."""
    units: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    fenced = False
    for lineno, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            if current:
                units.append(current)
            current = []
            continue
        if fenced:
            continue
        starts_unit = stripped.startswith(("|", "#")) or re.match(r"(?:[-*]|\d+\.)\s", stripped)
        if (not stripped or starts_unit) and current:
            units.append(current)
            current = []
        if stripped:
            current.append((lineno, stripped))
            if stripped.startswith(("|", "#")):
                units.append(current)
                current = []
    if current:
        units.append(current)
    return units


def sentences(unit: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return (line, sentence) pairs; a table cell counts as a sentence."""
    text, starts = "", []
    for lineno, line in unit:
        starts.append((len(text), lineno))
        text += line + " "
    pieces, position = [], 0
    for match in re.finditer(r"(?<=[.!?;])\s+(?=[A-Z`(\[*])|\s\|\s", text):
        pieces.append((position, text[position : match.start()]))
        position = match.end()
    pieces.append((position, text[position:]))
    found = []
    for offset, sentence in pieces:
        if sentence.strip():
            line = next((ln for start, ln in reversed(starts) if start <= offset), unit[0][0])
            found.append((line, sentence.strip()))
    return found


def cross_ref_violations(bundles: dict[str, list[str]]) -> list[tuple[str, int, str, str]]:
    """Cross-bundle sibling references with no fallback in the same or next sentence.

    A fallback is concrete: it carries a code span (a command, flag, lint, API,
    or file name) that is not a skill name. The test is a proxy. It cannot tell
    whether the span states the rule the sibling owns, only that the sentence
    gives the reader something to act on without the sibling.
    """
    owner = bundle_index(bundles)
    names = set(owner)

    def concrete(sentence: str) -> bool:
        return any(span not in names for span in CODE_SPAN.findall(sentence))

    found = []
    for markdown in sorted(SKILLS_DIR.rglob("*.md")):
        skill = markdown.relative_to(SKILLS_DIR).parts[0]
        if skill not in owner:
            continue
        rel = str(markdown.relative_to(ROOT))
        text = markdown.read_text(encoding="utf-8")
        if markdown.name == "SKILL.md":
            # The description routes; a "Not for X; use y" boundary there is not a
            # pointer the reader follows for a rule. Blank the frontmatter so the
            # line numbers stay right.
            body = frontmatter_body(text)
            text = "\n" * (text.count("\n") - body.count("\n")) + body
        for unit in prose_units(text):
            pieces = sentences(unit)
            for index, (line, sentence) in enumerate(pieces):
                following = pieces[index + 1][1] if index + 1 < len(pieces) else ""
                for match in SIBLING_REF.finditer(sentence):
                    for sibling in filter(None, match.groups()):
                        if sibling not in names or sibling == skill or owner[sibling] == owner[skill]:
                            continue
                        if concrete(sentence) or concrete(following):
                            continue
                        found.append((rel, line, sibling, sentence))
    return found


def check_cross_refs(bundles: dict[str, list[str]], ceilings: dict) -> None:
    # Counted per skill, not per file, so a section can move between SKILL.md and
    # references/ without touching the ceiling.
    accepted = ceilings.get("cross_refs", {})
    counts: dict[str, int] = {}
    for rel, line, sibling, _ in cross_ref_violations(bundles):
        skill = rel.split("/")[1]
        counts[skill] = counts.get(skill, 0) + 1
        if skill not in accepted:
            fail(
                f"{rel}:{line}",
                f"names the `{sibling}` skill, which is in another bundle, with no fallback; "
                f"state the rule it owns in one sentence with a command or API name",
            )
    for skill, allowed in sorted(accepted.items()):
        count = counts.get(skill, 0)
        if count > allowed:
            fail(
                f"skills/{skill}",
                f"has {count} cross-bundle references with no fallback; its accepted ceiling "
                f"is {allowed}. Add a fallback sentence (run --report cross-refs)",
            )
        elif count < allowed:
            warn("scripts/catalog-ceilings.toml", f"lower cross_refs.{skill} to {count}" if count else f"remove cross_refs.{skill}")


def description_claims(description: str) -> str:
    """The part of a description that claims work: every sentence but a 'Not for' boundary."""
    kept = [s for s in re.split(r"(?<=[.;])\s+", description) if not s.startswith("Not for")]
    return " ".join(kept)


def check_negative_cases(descriptions: dict[str, str]) -> None:
    """A collision once found stays fixed: the phrase must not return to the rival."""
    if not NEGATIVE.is_file():
        fail("evals/routing/negative-cases.md", "negative cases are missing")
        return
    text = NEGATIVE.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*([a-z0-9-]+)\s*\|\s*([a-z0-9-]+)\s*\|[^\n]*$", text, re.M)
    rows = [row for row in rows if not set(row[0]) <= {"-", " "}]
    if not rows:
        fail("evals/routing/negative-cases.md", "has no rows")
    for phrase, rival, owner in rows:
        phrase = phrase.strip("`")
        for skill in (rival, owner):
            if skill not in descriptions:
                fail("evals/routing/negative-cases.md", f"names {skill!r}, which is not in skills/")
        if rival in descriptions and phrase.lower() in description_claims(descriptions[rival]).lower():
            fail(
                f"skills/{rival}/SKILL.md",
                f"description claims {phrase!r}, which evals/routing/negative-cases.md gives to "
                f"{owner!r}; move it into a 'Not for' clause or drop it",
            )


def report_budget(bundles: dict[str, list[str]]) -> None:
    try:
        import tiktoken  # optional; never required

        encoding = tiktoken.get_encoding("cl100k_base")
        count = lambda text: len(encoding.encode(text))
        label = "cl100k"
    except Exception:  # noqa: BLE001 - any failure means "not available"
        count, label = None, "cl100k (not installed)"
    owner = bundle_index(bundles)
    print(f"| Skill | Bundle | Description chars | Description ~tokens | Body chars | Body ~tokens | Body {label} |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for name in sorted(bodies, key=lambda n: -len(bodies[n])):
        extra = count(bodies[name]) if count else "-"
        print(
            f"| {name} | {owner.get(name, '-')} | {len(descriptions[name])} | "
            f"{estimate_tokens(descriptions[name])} | {len(bodies[name])} | "
            f"{estimate_tokens(bodies[name])} | {extra} |"
        )
    print()


def report_cross_refs(bundles: dict[str, list[str]]) -> None:
    found = cross_ref_violations(bundles)
    per_skill: dict[str, int] = {}
    for rel, line, sibling, sentence in found:
        per_skill[rel.split("/")[1]] = per_skill.get(rel.split("/")[1], 0) + 1
        print(f"{rel}:{line}: `{sibling}`: {sentence}")
    print(f"\n{len(found)} cross-bundle reference(s) with no fallback in {len(per_skill)} skill(s)")
    for skill, count in sorted(per_skill.items(), key=lambda item: (-item[1], item[0])):
        flag = "  (over 10: review the skill boundary)" if count > 10 else ""
        print(f"  {count:3d}  {skill}{flag}")
    print()


def emit_ceilings(bundles: dict[str, list[str]]) -> str:
    """The ratchet file for the tree as it stands: every value over a hard limit."""
    out = [
        "# Accepted values above a hard limit in scripts/validate-skills.py. A ratchet:",
        "# the validator fails when a listed value grows, and asks for the entry to be",
        "# lowered or removed when it shrinks. Never raise an entry to make a change",
        "# pass; move material to references/ or shorten the text instead. check.sh",
        "# compares this file with the merge base (--ceilings-base), so an added or",
        "# raised entry fails CI. One exception, checked there too: a change that",
        "# resolves a cross-bundle reference may raise that skill's body_tokens by up",
        "# to 60 per resolved reference, the size of one fallback sentence.",
        "#",
        "# Regenerate after a change that shrinks a value:",
        "#   python3 scripts/validate-skills.py --emit-ceilings > scripts/catalog-ceilings.toml",
        "",
    ]
    total = sum(len(d) for d in descriptions.values())
    if total > MAX_TOTAL_DESCRIPTIONS:
        out += ["[description]", f"total = {total}", ""]
    over = {
        b: size
        for b, skills in bundles.items()
        if (size := sum(len(descriptions.get(s, "")) for s in skills)) > MAX_BUNDLE_DESCRIPTIONS
    }
    if over:
        out += ["[bundle_descriptions]"] + [f"{b} = {n}" for b, n in sorted(over.items())] + [""]
    heavy = {n: estimate_tokens(b) for n, b in bodies.items() if estimate_tokens(b) > MAX_BODY_TOKENS}
    if heavy:
        out += ["[body_tokens]"] + [f"{n} = {t}" for n, t in sorted(heavy.items())] + [""]
    counts: dict[str, int] = {}
    for rel, *_ in cross_ref_violations(bundles):
        skill = rel.split("/")[1]
        counts[skill] = counts.get(skill, 0) + 1
    if counts:
        out += ["[cross_refs]"] + [f"{k} = {v}" for k, v in sorted(counts.items())] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the skill catalog.")
    parser.add_argument("--report", choices=["budget", "cross-refs"], action="append", default=[])
    parser.add_argument("--emit-ceilings", action="store_true", help="print the ratchet file for the current tree")
    parser.add_argument(
        "--ceilings-base",
        metavar="REF",
        help="fail when scripts/catalog-ceilings.toml adds or raises an entry against this git ref",
    )
    args = parser.parse_args(argv)

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

    bundles = load_bundles()
    if args.emit_ceilings:
        print(emit_ceilings(bundles), end="")
        return 0
    ceilings = load_ceilings()
    if "budget" in args.report:
        report_budget(bundles)
    if "cross-refs" in args.report:
        report_cross_refs(bundles)
    check_bundles(bundles, skill_names)
    check_marketplace(bundles, skill_names)
    if args.ceilings_base:
        check_ceilings_against(args.ceilings_base, ceilings)
    check_description_budget(bundles, ceilings)
    check_body_tokens(ceilings)
    check_snippet(skill_names, bundles)
    check_cross_refs(bundles, ceilings)
    check_negative_cases(descriptions)

    for warning in warnings:
        print(f"  warning: {warning}")
    if failures:
        print(f"FAIL: {len(failures)} problem(s) in {len(skill_dirs)} skill(s)\n")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(f"OK: {len(skill_dirs)} skills valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
