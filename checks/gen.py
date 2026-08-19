#!/usr/bin/env python3
"""Extract ```rust blocks from ../skills/**/*.md into cargo examples.

Each candidate block becomes examples/<name>.rs, which `cargo check --examples`
then type-checks. analyze.py classifies whatever fails.

Adapted from the harness in https://github.com/leonardomso/rust-skills (MIT).

A block opts out by tagging its fence. The tags follow rustdoc:

    ```rust,compile_fail   the block is a deliberate error demonstration
    ```rust,ignore         the block cannot compile standalone by design

Only a bare ```rust fence is extracted, so tagging is the explicit escape and
the heuristics below are the safety net for blocks nobody tagged.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SKILLS = (HERE.parent / "skills").resolve()
OUT = HERE / "examples"
OUT.mkdir(exist_ok=True)
for stale in OUT.glob("*.rs"):
    stale.unlink()

PLACEHOLDER = re.compile(r"\b(my_crate|mycrate|mylib|my_app|my_project|my_lib)\b")

# Markers a skill uses for code that is wrong on purpose. A block carrying one
# is documentation of a mistake, not an example to compile.
WRONG_ON_PURPOSE = ("// BAD", "// DON'T", "// WRONG", "// Rejected", "// UB")

HEADER = (
    "#![allow(unused, dead_code, unreachable_code, unused_imports, "
    "unused_variables, unused_mut, unused_assignments, unused_macros, "
    "non_local_definitions)]\n"
)

# Many skills write `Result<T>`, which assumes the crate-local alias that almost
# every real crate defines. Without it the block fails with E0107 and lands in
# the suspect bucket for a reason that has nothing to do with the skill.
RESULT_ALIAS = "type Result<T, E = Box<dyn std::error::Error>> = std::result::Result<T, E>;\n"

# The wrapper that lets a bare statement fragment use `?` and `.await`.
WRAPPER_OPEN = "async fn __ex() -> std::result::Result<(), Box<dyn std::error::Error>> {\n"
WRAPPER_CLOSE = "\n;\nstd::result::Result::Ok(())\n}\nfn main() {}\n"


def is_candidate(block: str) -> bool:
    if "#![feature" in block:
        return False
    if "proc_macro" in block:
        return False
    if PLACEHOLDER.search(block):
        return False
    for line in block.splitlines():
        stripped = line.strip()
        if stripped == "...":
            return False
        if stripped.startswith(WRONG_ON_PURPOSE):
            return False
    return True


def needs_result_alias(block: str) -> bool:
    """True when the block says `Result<T>` and defines no `Result` of its own.

    Injecting the alias next to a `use anyhow::Result` or a local `type Result`
    would collide, so check for both before adding it.
    """
    if not re.search(r"\bResult<", block):
        return False
    if re.search(r"^\s*use\s+[^;]*\bResult\b", block, re.M):
        return False
    if re.search(r"^\s*(pub\s+)?type\s+Result\b", block, re.M):
        return False
    return True


def wrap(block: str) -> str:
    """Build a compilable file around one block."""
    prelude = HEADER + (RESULT_ALIAS if needs_result_alias(block) else "")
    has_main = re.search(r"\bfn\s+main\s*\(", block) is not None
    has_inner_attr = "#![" in block
    # A block that declares a module is item-level: keep it at the crate root so
    # `mod m { use super::*; }` still resolves.
    has_mod = re.search(r"(?m)^\s*(pub(\([^)]*\))?\s+)?mod\s+\w", block) is not None
    if has_main:
        return prelude + block + "\n"
    if has_inner_attr or has_mod:
        return prelude + block + "\nfn main() {}\n"
    return prelude + WRAPPER_OPEN + block + WRAPPER_CLOSE


def main() -> int:
    if not SKILLS.is_dir():
        print(f"no skills directory at {SKILLS}", file=sys.stderr)
        return 1

    manifest: dict[str, dict[str, object]] = {}
    scanned = 0
    tagged = 0

    for markdown in sorted(SKILLS.rglob("*.md")):
        lines = markdown.read_text(encoding="utf-8").splitlines()
        section = ""
        i = 0
        while i < len(lines):
            line = lines[i]
            heading = re.match(r"^#{2,}\s+(.*)", line)
            if heading:
                section = heading.group(1).strip()
            fence = line.strip()
            if fence.startswith("```rust"):
                start = i + 1
                end = start
                while end < len(lines) and lines[end].strip() != "```":
                    end += 1
                if fence != "```rust":
                    tagged += 1
                else:
                    scanned += 1
                    block = "\n".join(lines[start:end])
                    if is_candidate(block):
                        rel = markdown.relative_to(SKILLS)
                        stem = str(rel)[: -len(".md")].replace("/", "__").replace("-", "_")
                        name = f"{stem}__{scanned}"
                        (OUT / f"{name}.rs").write_text(wrap(block), encoding="utf-8")
                        manifest[name] = {
                            "file": str(rel),
                            "line": start + 1,
                            "section": section or "(top)",
                        }
                i = end
            i += 1

    (HERE / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    print(
        f"generated {len(manifest)} example files "
        f"(scanned {scanned} rust blocks, skipped {tagged} tagged by fence)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
