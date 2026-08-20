#!/usr/bin/env python3
"""Extract ```rust blocks from ../skills/**/*.md into cargo examples.

The fence tag decides what happens to a block, and nothing else:

    ```rust                the block must compile
    ```rust,run            the block must compile and its main function must run
    ```rust,compile_fail   the block must not compile
    ```rust,ignore         the block is not checked

`compile_fail` accepts the expected error codes after the tag, and
`analyze.py` then requires them:

    ```rust,compile_fail,E0499

Every block reaches manifest.json with its mode, so coverage is a number the
gate can check rather than a claim. There is no heuristic skip: a block that
cannot compile on its own carries `ignore` or it fails the gate.
"""
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SKILLS = (HERE.parent / "skills").resolve()
OUT = HERE / "examples"

# A compile_fail example carries this prefix so analyze.py can tell the two
# populations apart from the target name alone.
XFAIL = "xfail__"
RUN = "run__"

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

CODE_RE = re.compile(r"^E\d{4}$")
INCOMPLETE_RE = re.compile(r"\b(?:todo|unimplemented)!\s*\(|\b(?:TODO|FIXME)\b")


def parse_fence(fence: str) -> tuple[str, list[str]] | None:
    """Return (mode, expected codes) for a ```rust fence, or None when unknown.

    An unknown tag is not a silent pass. main() reports it and exits non-zero,
    because a typo in a fence would otherwise remove a block from the gate.
    """
    parts = [p.strip() for p in fence[len("```") :].split(",") if p.strip()]
    if not parts or parts[0] != "rust":
        return None
    tags = parts[1:]
    if not tags:
        return "compile", []
    if tags[0] == "run":
        return ("run", []) if len(tags) == 1 else None
    if tags[0] == "ignore":
        return ("ignore", []) if len(tags) == 1 else None
    if tags[0] == "compile_fail":
        codes = tags[1:]
        if all(CODE_RE.match(c) for c in codes):
            return "compile_fail", codes
    return None


def run_problem(block: str) -> str | None:
    """Return why a behavior probe cannot run, or None when it is complete."""
    if re.search(r"\bfn\s+main\s*\(", block) is None:
        return "a rust,run block must define fn main()"
    if INCOMPLETE_RE.search(block):
        return "a rust,run block cannot contain TODO, FIXME, todo!(), or unimplemented!()"
    return None


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


def wrap(block: str) -> tuple[str, str]:
    """Build a compilable file around one block, and name the shape used."""
    prelude = HEADER + (RESULT_ALIAS if needs_result_alias(block) else "")
    has_main = re.search(r"\bfn\s+main\s*\(", block) is not None
    has_inner_attr = "#![" in block
    # A block that declares a module is item-level: keep it at the crate root so
    # `mod m { use super::*; }` still resolves.
    has_mod = re.search(r"(?m)^\s*(pub(\([^)]*\))?\s+)?mod\s+\w", block) is not None
    if has_main:
        return prelude + block + "\n", "crate"
    if has_inner_attr or has_mod:
        return prelude + block + "\nfn main() {}\n", "item"
    return prelude + WRAPPER_OPEN + block + WRAPPER_CLOSE, "async-body"


def blocks_of(lines: list[str]):
    """Yield (fence, section, start line, block text) for every ```rust fence."""
    section = ""
    i = 0
    while i < len(lines):
        heading = re.match(r"^#{2,}\s+(.*)", lines[i])
        if heading:
            section = heading.group(1).strip()
        fence = lines[i].strip()
        if fence.startswith("```rust"):
            start = i + 1
            end = start
            while end < len(lines) and lines[end].strip() != "```":
                end += 1
            yield fence, section or "(top)", start + 1, "\n".join(lines[start:end])
            i = end
        i += 1


def main() -> int:
    if not SKILLS.is_dir():
        print(f"no skills directory at {SKILLS}", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.rs"):
        stale.unlink()

    manifest: dict[str, dict[str, object]] = {}
    counts = {"compile": 0, "run": 0, "compile_fail": 0, "ignore": 0}
    bad_fences: list[str] = []
    total = 0

    for markdown in sorted(SKILLS.rglob("*.md")):
        rel = str(markdown.relative_to(SKILLS))
        stem = rel[: -len(".md")].replace("/", "__").replace("-", "_")
        lines = markdown.read_text(encoding="utf-8").splitlines()
        for fence, section, line, block in blocks_of(lines):
            total += 1
            parsed = parse_fence(fence)
            if parsed is None:
                bad_fences.append(f"{rel}:{line}: unknown fence {fence!r}")
                continue
            mode, codes = parsed
            if mode == "run" and (problem := run_problem(block)):
                bad_fences.append(f"{rel}:{line}: {problem}")
                continue
            counts[mode] += 1
            prefix = XFAIL if mode == "compile_fail" else RUN if mode == "run" else ""
            name = f"{prefix}{stem}__{total}"
            entry: dict[str, object] = {
                "file": rel,
                "line": line,
                "section": section,
                "mode": mode,
                # A stable identity for the block. The baseline signature uses
                # it so two blocks in one section cannot share a line.
                "hash": hashlib.sha256(block.encode()).hexdigest()[:8],
            }
            if mode != "ignore":
                source, shape = wrap(block)
                (OUT / f"{name}.rs").write_text(source, encoding="utf-8")
                entry["wrapper"] = shape
                if codes:
                    entry["codes"] = codes
            manifest[name] = entry

    (HERE / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    print(
        f"rust blocks {total}: {counts['compile']} compile, "
        f"{counts['run']} run, "
        f"{counts['compile_fail']} compile_fail, {counts['ignore']} ignore"
    )
    if bad_fences:
        print("\nFAIL: a fence tag decides whether a block is checked, and these are unknown:\n")
        for problem in bad_fences:
            print(f"  {problem}")
        print(
            "\nUse ```rust, ```rust,run, ```rust,compile_fail[,E0000...],"
            " or ```rust,ignore."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
