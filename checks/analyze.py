#!/usr/bin/env python3
"""Classify `cargo check --examples --message-format=json` output.

Adapted from the harness in https://github.com/leonardomso/rust-skills (MIT).

Most skill examples are fragments: they name types and functions that the
surrounding prose defines, so they cannot resolve on their own. A plain
pass/fail gate would drown a real defect in that noise. Every failing example is
bucketed instead:

  FRAGMENT  every error is name resolution. Expected, ignored.
  ARTIFACT  the extraction caused it: a `&self` method body lifted into a free
            function, a doc comment with no item after it, pseudocode tokens.
  LOW       only "type annotations needed", which the real context supplies.
  SUSPECT   everything else: type mismatch, missing method, wrong arity, bad
            syntax. These are real defects until shown otherwise.

Usage:
  analyze.py check.json                        summary plus suspect detail
  analyze.py check.json --emit-baseline        one signature per suspect
  analyze.py check.json --check-baseline FILE  exit 1 on a suspect not in FILE

A signature is `file :: section :: sorted error codes`. It carries no line
number, so it survives edits above the block and only changes when the failure
itself changes. CI gates on signatures absent from the committed baseline.
"""
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent

# Errors that mean "this name is defined in the prose, not in the block".
RESOLUTION_CODES = {
    "E0405", "E0412", "E0422", "E0423", "E0425", "E0432", "E0433",
    "E0463", "E0531", "E0561", "E0573", "E0583", "E0658",
}
RESOLUTION_PREFIXES = (
    "cannot find",
    "unresolved import",
    "failed to resolve",
    "use of undeclared",
    "cannot determine",
    "can't find crate",
    "maybe a missing crate",
    "unresolved module",
)
LOW_CODES = {"E0282", "E0283"}

# Errors the wrapper itself causes.
ARTIFACT_CODES = {
    "E0585",  # a doc comment with no item following it
    "E0586",  # inclusive range with no end, from an elided example
    "E0424",  # `self` used where the body was lifted out of an impl block
}
ARTIFACT_MESSAGES = (
    "parameter is only allowed in associated functions",
    "await is only allowed inside",
    "expected value, found module `self`",
    "`...`",
    "missing documentation",
)


def code_of(diagnostic: dict) -> str | None:
    return (diagnostic.get("code") or {}).get("code")


def is_resolution(diagnostic: dict) -> bool:
    if code_of(diagnostic) in RESOLUTION_CODES:
        return True
    message = diagnostic.get("message", "")
    return any(message.startswith(prefix) for prefix in RESOLUTION_PREFIXES)


def is_artifact(diagnostic: dict) -> bool:
    if code_of(diagnostic) in ARTIFACT_CODES:
        return True
    message = diagnostic.get("message", "")
    return any(fragment in message for fragment in ARTIFACT_MESSAGES)


def token(diagnostic: dict) -> str:
    code = code_of(diagnostic)
    if code:
        return code
    # A parse error carries no code. Use a short normalized stem so the
    # signature stays stable across unrelated edits.
    words = diagnostic.get("message", "").lower().split()
    return "P:" + " ".join(words[:5])


def parse(path: str) -> dict[str, list[dict]]:
    errors: dict[str, list[dict]] = collections.defaultdict(list)
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if record.get("reason") != "compiler-message":
                continue
            message = record.get("message", {})
            if message.get("level") != "error":
                continue
            target = (record.get("target") or {}).get("name")
            if target:
                errors[target].append(message)
    return errors


def classify(errors: dict[str, list[dict]]):
    fragment = artifact = low = 0
    suspects: dict[str, list[dict]] = {}
    for example, diagnostics in errors.items():
        unresolved = [d for d in diagnostics if not is_resolution(d)]
        if not unresolved:
            fragment += 1
            continue
        if all(is_artifact(d) for d in unresolved):
            artifact += 1
            continue
        real = [d for d in unresolved if not is_artifact(d)]
        if all(code_of(d) in LOW_CODES for d in real):
            low += 1
            continue
        suspects[example] = [d for d in real if code_of(d) not in LOW_CODES]
    return fragment, artifact, low, suspects


def main() -> int:
    manifest_path = HERE / "manifest.json"
    if not manifest_path.is_file():
        print("no manifest.json; run gen.py first", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    args = sys.argv[1:]
    path = next((a for a in args if not a.startswith("--")), "check.json")
    errors = parse(path)
    fragment, artifact, low, suspects = classify(errors)

    def signature(example: str, diagnostics: list[dict]) -> str:
        info = manifest.get(example, {})
        tokens = ",".join(sorted({token(d) for d in diagnostics}))
        return f"{info.get('file', '?')} :: {info.get('section', '?')} :: {tokens}"

    signatures = sorted({signature(e, d) for e, d in suspects.items()})

    if "--emit-baseline" in args:
        print("# Compile suspects accepted as known. Regenerate with:")
        print("#   python3 checks/analyze.py check.json --emit-baseline > checks/baseline.txt")
        print("# CI fails on any signature that is not listed here.")
        print("\n".join(signatures))
        return 0

    if "--check-baseline" in args:
        baseline_path = args[args.index("--check-baseline") + 1]
        known = {
            line.strip()
            for line in open(baseline_path, encoding="utf-8")
            if line.strip() and not line.startswith("#")
        }
        new = [s for s in signatures if s not in known]
        stale = sorted(known - set(signatures))
        if new:
            print(f"FAIL: {len(new)} new compile suspect(s) not in the baseline:\n")
            print("\n".join(f"  + {s}" for s in new))
            print(
                "\nIf the example is wrong, fix the example. If it is a new"
                " deliberate fragment, tag the fence ```rust,ignore, or"
                " regenerate the baseline:\n"
                "  python3 checks/analyze.py check.json --emit-baseline > checks/baseline.txt"
            )
            return 1
        if stale:
            # Not a failure. A fixed example should shrink the baseline, and
            # saying so is how the baseline stops growing forever.
            print(f"note: {len(stale)} baseline entr(ies) no longer occur; consider regenerating:")
            print("\n".join(f"  - {s}" for s in stale))
        print(f"OK: no new compile suspects ({len(signatures)} known, all in the baseline)")
        return 0

    checked = len(manifest)
    failed = len(errors)
    print("== compile-check summary ==")
    print(f"examples checked            : {checked}")
    print(f"compiled clean              : {checked - failed}")
    print(f"fragments (undefined syms)  : {fragment}")
    print(f"wrapper artifacts           : {artifact}")
    print(f"low signal (needs type ann) : {low}")
    print(f"SUSPECT (review these)      : {len(suspects)}")

    rows = []
    for example, diagnostics in suspects.items():
        info = manifest.get(example, {})
        rows.append((info.get("file", "?"), info.get("line", 0), info.get("section", "?"), diagnostics))
    for file, line, section, diagnostics in sorted(rows):
        print(f"\n--- {file}:{line}  [{section}]")
        seen = set()
        for diagnostic in diagnostics:
            code = code_of(diagnostic) or "----"
            first = diagnostic.get("message", "").splitlines()[0]
            if (code, first) in seen:
                continue
            seen.add((code, first))
            print(f"    {code}: {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
