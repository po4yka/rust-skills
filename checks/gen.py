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

A block that names items the surrounding prose defines gets them from
checks/preludes/*.toml, keyed by file, section, and the block's ordinal in that
section.
`items` is appended at the crate root, and `setup` opens the body of the
statement wrapper. The skill text stays as the reader sees it, and the block is
type-checked in full instead of stopping at its first unresolved name. A
prelude that matches no block fails the run, so an edit cannot orphan one
silently.
"""
import hashlib
import json
import pathlib
import re
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
SKILLS = (HERE.parent / "skills").resolve()
OUT = HERE / "examples"
PRELUDES = HERE / "preludes"
PRELUDE_KEYS = {"file", "section", "block", "items", "setup"}

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


def shape_of(block: str) -> str:
    """Name the wrapper a block needs: crate, item, or async-body."""
    if re.search(r"\bfn\s+main\s*\(", block) is not None:
        return "crate"
    # A block that declares a module is item-level: keep it at the crate root so
    # `mod m { use super::*; }` still resolves.
    has_mod = re.search(r"(?m)^\s*(pub(\([^)]*\))?\s+)?mod\s+\w", block) is not None
    if "#![" in block or has_mod:
        return "item"
    return "async-body"


def wrap(block: str, items: str = "", setup: str = "") -> tuple[str, str]:
    """Build a compilable file around one block, and name the shape used.

    Prelude `items` go after the block, at the crate root. Item order does not
    matter in Rust, and an inner attribute in the block must stay first.
    Prelude `setup` statements open the statement wrapper's body.
    """
    shape = shape_of(block)
    if setup and shape != "async-body":
        raise ValueError(f"a prelude `setup` needs a statement block, and this block is {shape}-level")
    alias = RESULT_ALIAS if needs_result_alias(block + "\n" + items) else ""
    tail = ("\n" + items + "\n") if items else ""
    if shape == "crate":
        return HEADER + alias + block + "\n" + tail, shape
    if shape == "item":
        return HEADER + alias + block + "\nfn main() {}\n" + tail, shape
    body = (setup + "\n" if setup else "") + block
    return HEADER + alias + WRAPPER_OPEN + body + WRAPPER_CLOSE + tail, shape


def load_preludes(path: pathlib.Path = PRELUDES) -> tuple[dict, list[str]]:
    """Return {(file, section, ordinal): prelude} and the problems found.

    `path` is a directory of *.toml files, one per skill by convention, or one
    file. Every file holds `[[block]]` tables.
    """
    files = sorted(path.glob("*.toml")) if path.is_dir() else [path] if path.is_file() else []
    preludes: dict[tuple[str, str, int], dict] = {}
    problems: list[str] = []
    entries = []
    for source in files:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
        entries += [(f"{source.name} block #{i}", e) for i, e in enumerate(data.get("block", []), 1)]
    for where, entry in entries:
        unknown = set(entry) - PRELUDE_KEYS
        if unknown:
            problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
            continue
        if not all(isinstance(entry.get(k), str) for k in ("file", "section")) or not isinstance(
            entry.get("block"), int
        ):
            problems.append(f"{where}: needs string `file` and `section` and integer `block`")
            continue
        if not entry.get("items") and not entry.get("setup"):
            problems.append(f"{where}: defines neither `items` nor `setup`")
            continue
        key = (entry["file"], entry["section"], entry["block"])
        if key in preludes:
            problems.append(f"{where}: a second prelude for {key}")
            continue
        preludes[key] = entry
    return preludes, problems


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
    preludes, prelude_problems = load_preludes()
    used: set[tuple[str, str, int]] = set()

    for markdown in sorted(SKILLS.rglob("*.md")):
        rel = str(markdown.relative_to(SKILLS))
        stem = rel[: -len(".md")].replace("/", "__").replace("-", "_")
        lines = markdown.read_text(encoding="utf-8").splitlines()
        ordinals: dict[str, int] = {}
        for fence, section, line, block in blocks_of(lines):
            total += 1
            ordinals[section] = ordinals.get(section, 0) + 1
            key = (rel, section, ordinals[section])
            prelude = preludes.get(key)
            if prelude is not None:
                used.add(key)
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
                # The prelude key: the block's 1-based ordinal in its section.
                "block": ordinals[section],
                "mode": mode,
                # A stable identity for the block. The baseline signature uses
                # it so two blocks in one section cannot share a line.
                "hash": hashlib.sha256(block.encode()).hexdigest()[:8],
            }
            if prelude is not None and mode not in ("compile", "compile_fail"):
                bad_fences.append(
                    f"{rel}:{line}: a prelude applies only to a compile or compile_fail block, not {mode}"
                )
                continue
            if mode != "ignore":
                try:
                    source, shape = wrap(
                        block,
                        (prelude or {}).get("items", ""),
                        (prelude or {}).get("setup", ""),
                    )
                except ValueError as error:
                    bad_fences.append(f"{rel}:{line}: {error}")
                    continue
                (OUT / f"{name}.rs").write_text(source, encoding="utf-8")
                entry["wrapper"] = shape
                if prelude is not None:
                    entry["prelude"] = True
                if codes:
                    entry["codes"] = codes
            manifest[name] = entry

    for key in sorted(set(preludes) - used):
        prelude_problems.append(
            f"checks/preludes: no block {key[2]} in section {key[1]!r} of {key[0]}"
        )

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
    if prelude_problems:
        print("\nFAIL: checks/preludes does not match the skills:\n")
        for problem in prelude_problems:
            print(f"  {problem}")
        print(
            "\nA prelude is keyed by file, section heading, and the block's 1-based"
            " ordinal\namong the ```rust blocks of that section. Update the key"
            " after you move or\nrename a block, or delete the prelude with the block."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
