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
import re
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
# The Agent Skills spec recommends a SKILL.md under 500 lines. Longer material
# belongs in references/, which the agent opens only when it needs it.
MAX_SKILL_LINES = 500
MAX_COMPATIBILITY = 500

# Token estimates. The gate counts characters and divides by 2.5, so every
# host computes the same number with no tokenizer and no network. The ratio is
# calibrated, not assumed: `claude plugin details` (Claude Code 2.1.316, on
# 2026-10-31) projected 2.37 characters per token for the descriptions of this
# catalog, per-entry overhead included, and 2.58 for the bodies; the record is
# research/token-calibration-2026-10.md. The common chars/3.5 rule undercounts
# this catalog by 25 % to 32 %. `--report budget` also prints a cl100k count
# when tiktoken happens to be installed; the gate never reads it, because a
# verdict that depends on an optional package is not reproducible, and cl100k
# is not the tokenizer of any Claude model.
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
    bodies[name] = frontmatter_body(text)

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
        targets = set(re.findall(r"`(references/[^`]+\.md)`", text))
        for target in sorted(targets):
            if not (skill_dir / target).is_file():
                fail(rel, f"points at a missing reference file: {target}")
        # A Markdown link resolves from the file that holds it. An installed
        # skill carries only its own directory, so a link that leaves it, or a
        # repository path to another skill, is dead after `npx skills add`.
        for target in sorted(set(re.findall(r"\]\(([^)\s]+)\)", text))):
            path = target.split("#", 1)[0]
            if not path or re.match(r"[a-z][a-z0-9+.-]*:", path):
                continue
            resolved = (markdown.parent / path).resolve()
            if not resolved.is_relative_to(skill_dir.resolve()):
                fail(rel, f"links outside its skill directory: {target}; name the other skill instead")
            elif not resolved.exists():
                fail(rel, f"points at a missing file: {target}")
        for span in sorted(set(re.findall(r"`(skills/[a-z0-9-]+/[^`]*)`", text))):
            fail(rel, f"names a repository path: {span}; name the skill, or use a path relative to this file")


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
    rows = set(re.findall(r"^\|\s*`?([a-z0-9-]+)`?\s*\|", install.group(1), re.M))
    for bundle in sorted(set(bundles) - rows):
        fail("README.md", f"bundle {bundle!r} has no row in the Install table")


def load_ceilings() -> dict:
    """The ratchet: values above a hard limit that the catalog may keep, never grow."""
    if not CEILINGS.is_file():
        return {}
    return load_toml(CEILINGS, "scripts/catalog-ceilings.toml") or {}


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


def check_snippet(skill_names: set[str]) -> None:
    """The always-on router must route to every skill once and stay small."""
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


# A sibling named as "the `x` skill" (or "`x` and `y` skills"). An installed
# bundle has no sibling outside it, so the reference must not be the only place
# the reader learns what to do.
SIBLING_REF = re.compile(r"`([a-z0-9-]+)`(?= skills?\b)|`([a-z0-9-]+)` and `([a-z0-9-]+)` skills\b")
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
        for unit in prose_units(markdown.read_text(encoding="utf-8")):
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
    accepted = ceilings.get("cross_refs", {})
    counts: dict[str, int] = {}
    for rel, line, sibling, _ in cross_ref_violations(bundles):
        counts[rel] = counts.get(rel, 0) + 1
        if rel.removeprefix("skills/") not in accepted:
            fail(
                f"{rel}:{line}",
                f"names the `{sibling}` skill, which is in another bundle, with no fallback; "
                f"state the rule it owns in one sentence with a command or API name",
            )
    for key, allowed in sorted(accepted.items()):
        rel = f"skills/{key}"
        count = counts.get(rel, 0)
        if count > allowed:
            fail(
                rel,
                f"has {count} cross-bundle references with no fallback; its accepted ceiling "
                f"is {allowed}. Add a fallback sentence (run --report cross-refs)",
            )
        elif count < allowed:
            warn("scripts/catalog-ceilings.toml", f"lower cross_refs.\"{key}\" to {count}" if count else f"remove cross_refs.\"{key}\"")


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
        "# pass; move material to references/ or shorten the text instead. One exception:",
        "# a commit that adds a cross-bundle fallback sentence may raise body_tokens for",
        "# that skill by the size of the sentence, and its message must say so.",
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
        key = rel.removeprefix("skills/")
        counts[key] = counts.get(key, 0) + 1
    if counts:
        out += ["[cross_refs]"] + [f'"{k}" = {v}' for k, v in sorted(counts.items())] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the skill catalog.")
    parser.add_argument("--report", choices=["budget", "cross-refs"], action="append", default=[])
    parser.add_argument("--emit-ceilings", action="store_true", help="print the ratchet file for the current tree")
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
    check_description_budget(bundles, ceilings)
    check_body_tokens(ceilings)
    check_snippet(skill_names)
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
