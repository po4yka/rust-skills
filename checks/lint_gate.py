#!/usr/bin/env python3
"""Proves the lint tables of the rust-lints skill against the pinned clippy.

The skill gives a strict `[workspace.lints]` template and a pragmatic baseline in
skills/rust-lints/references/workspace-lints.md, and a `clippy.toml` in its SKILL.md. Claims such
as "verified on 1.98.1" were checked by hand. This gate checks them on every run:

1. It copies the strict template and the `clippy.toml` out of the skill, unchanged, into a
   throwaway workspace whose one crate is checks/lints/violations.rs.
2. Every lint that the template names one by one (not a group) must have a `// expect: <lint>`
   marker in violations.rs, and clippy must report that lint on the marked line.
3. Neither table may name a lint that rustc or clippy calls unknown, renamed, or removed.

The rustdoc table is out of scope: only `cargo doc` runs those lints. A lint that the template
names but no configuration can trigger gets a gate-only configuration below, and says so.

    python3 checks/lint_gate.py           # check.sh runs this
    python3 checks/lint_gate.py --show    # print each reported lint and line, for calibration

A green gate proves that the named lints exist and fire on the pinned toolchain. It does not
prove that a level is right for a project, or that a lint catches every form of its problem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATES = ROOT / "skills" / "rust-lints" / "references" / "workspace-lints.md"
SKILL = ROOT / "skills" / "rust-lints" / "SKILL.md"
VIOLATIONS = HERE / "lints" / "violations.rs"
TOOLCHAIN = HERE / "rust-toolchain.toml"
TARGET = "x86_64-unknown-linux-gnu"

# The skill's clippy.toml lists no disallowed type, so `disallowed_types = "deny"` could never
# fire. The gate adds one entry of its own to prove that the lint exists and is on.
GATE_ONLY_CLIPPY = (
    '\n# Gate only, not part of the skill.\n'
    'disallowed-types = [{ path = "std::collections::HashMap", reason = "gate only" }]\n'
)
# An unknown name in a `[lints]` table arrives as error E0602, a removed one as
# `renamed_and_removed_lints`.
NAME_PROBLEMS = {"E0602", "unknown_lints", "renamed_and_removed_lints", "clippy::unknown_clippy_lints"}
# A lint whose diagnostic carries another code. At `deny` in edition 2024, rustc reports
# `unsafe_op_in_unsafe_fn` as error E0133.
ALIASES = {"unsafe_op_in_unsafe_fn": {"E0133"}}


def toml_block(markdown: str, heading: str) -> str:
    """Returns the first ```toml block after the line that starts with `heading`."""
    start = markdown.index(heading)
    match = re.search(r"^```toml\n(.*?)^```", markdown[start:], re.M | re.S)
    if not match:
        raise SystemExit(f"lint gate: no toml block after {heading!r}")
    return match.group(1)


def named_lints(table: str) -> set[str]:
    """Lints that the table names one by one: rustc and clippy entries, groups excluded."""
    data = tomllib.loads(table)["workspace"]["lints"]
    found = set()
    for tool in ("rust", "clippy"):
        for name, value in data.get(tool, {}).items():
            if isinstance(value, dict) and value.get("priority", 0) < 0:
                continue  # a group such as `pedantic`
            found.add(name if tool == "rust" else f"clippy::{name}")
    return found


def markers(source: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for lineno, line in enumerate(source.splitlines(), 1):
        match = re.search(r"^(?!\s*//).*//\s*expect:\s*(.+)$", line)
        for name in filter(None, (n.strip() for n in match.group(1).split(","))) if match else []:
            qualified = name if name in RUSTC_LINTS else f"clippy::{name}"
            found.setdefault(qualified, []).append(lineno)
    return found


RUSTC_LINTS: set[str] = set()


def workspace(root: Path, table: str, clippy_toml: str, source: str) -> Path:
    (root / "gate" / "src").mkdir(parents=True)
    (root / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["gate"]\nresolver = "3"\n\n' + table
    )
    (root / "clippy.toml").write_text(clippy_toml)
    (root / "gate" / "Cargo.toml").write_text(
        '[package]\nname = "lint-gate"\nversion = "0.0.0"\nedition = "2024"\n'
        'rust-version = "1.85"\npublish = false\ndescription = "lint gate"\n'
        'license = "BSD-3-Clause"\nrepository = "https://example.invalid/lint-gate"\n'
        'readme = false\nkeywords = []\ncategories = []\n\n[lints]\nworkspace = true\n'
    )
    (root / "gate" / "src" / "lib.rs").write_text(source)
    return root / "Cargo.toml"


def clippy(manifest: Path, target_dir: Path, channel: str) -> list[dict]:
    env = {**os.environ, "RUSTUP_TOOLCHAIN": channel, "CARGO_TARGET_DIR": str(target_dir),
           "CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never"}
    done = subprocess.run(
        ["cargo", "clippy", "--manifest-path", str(manifest), "--target", TARGET,
         "--message-format=json", "--quiet"],
        env=env, capture_output=True, text=True, timeout=600, check=False,
    )
    diagnostics = []
    for line in done.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("reason") != "compiler-message":
            continue
        message = event["message"]
        code = (message.get("code") or {}).get("code")
        primary = next((s for s in message.get("spans", []) if s.get("is_primary")), None)
        diagnostics.append({
            "code": code, "line": primary["line_start"] if primary else None,
            "file": primary["file_name"] if primary else None, "text": message.get("message", ""),
        })
    if not diagnostics and done.returncode != 0:
        raise SystemExit(f"lint gate: clippy did not run:\n{done.stderr[-2000:]}")
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="print every reported lint and line")
    args = parser.parse_args()

    templates = TEMPLATES.read_text(encoding="utf-8")
    strict = toml_block(templates, "## Strict template")
    baseline = toml_block(templates, "## Pragmatic baseline")
    clippy_toml = toml_block(SKILL.read_text(encoding="utf-8"), "## `clippy.toml`") + GATE_ONLY_CLIPPY
    expected = named_lints(strict)
    RUSTC_LINTS.update(n for n in expected if not n.startswith("clippy::"))
    source = VIOLATIONS.read_text(encoding="utf-8")
    marked = markers(source)
    channel = tomllib.loads(TOOLCHAIN.read_text())["toolchain"]["channel"]

    problems: list[str] = []
    for name in sorted(expected - marked.keys()):
        problems.append(f"the strict template names {name}, and violations.rs has no `// expect:` for it")
    for name in sorted(marked.keys() - expected):
        problems.append(f"violations.rs expects {name}, which the strict template does not name")

    with tempfile.TemporaryDirectory(prefix="lint-gate-") as tmp:
        tmp_path = Path(tmp)
        found = clippy(workspace(tmp_path / "strict", strict, clippy_toml, source),
                       tmp_path / "target", channel)
        base = clippy(workspace(tmp_path / "baseline", baseline, clippy_toml, "//! Baseline gate.\n"),
                      tmp_path / "target", channel)

    reported = {(d["code"], d["line"]) for d in found if d["file"] and d["file"].endswith("lib.rs")}
    if args.show:
        for code, line in sorted(reported, key=lambda x: (x[1] or 0, x[0] or "")):
            print(f"  {line:>4} {code}")
    for name, lines in sorted(marked.items()):
        for line in lines:
            if not ({name} | ALIASES.get(name, set())) & {code for code, at in reported if at == line}:
                problems.append(f"{name} did not fire on violations.rs:{line}")
    for which, diagnostics in (("strict template", found), ("pragmatic baseline", base)):
        for d in diagnostics:
            if d["code"] in NAME_PROBLEMS:
                problems.append(f"the {which} names a lint that {d['code']} reports: {d['text']}")

    for problem in problems:
        print(f"  {problem}")
    if problems:
        print(f"lint gate: {len(problems)} problem(s)")
        return 1
    print(f"  {len(expected)} named lint(s) fire on {channel}; both templates name only known lints")
    return 0


if __name__ == "__main__":
    sys.exit(main())
