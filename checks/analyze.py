#!/usr/bin/env python3
"""Classify `cargo check --examples --message-format=json` output.

Most skill examples are fragments: they name types and functions that the
surrounding prose defines, so they cannot resolve on their own. A plain
pass/fail gate would drown a real defect in that noise. Every failing example is
bucketed instead:

  FRAGMENT  every error is a name that the surrounding prose defines.
            Missing harness dependencies and features are suspects.
  ARTIFACT  the extraction caused it: a `&self` method body lifted into a free
            function, a doc comment with no item after it, pseudocode tokens.
  LOW       only "type annotations needed", which the real context supplies.
  SUSPECT   everything else: type mismatch, missing method, wrong arity, bad
            syntax. These are real defects until shown otherwise.

An error code enters the excused sets only when it means "the name is defined in
the prose, not in the block". Every other code, and every code this file does
not know, is a suspect. A wider excuse list is how a real defect passes as a
harmless fragment; test_analyze.py holds the regression cases.

Three gates run before the buckets:

  every example cargo was asked to build appears in its output,
  every compile_fail example does fail,
  every error code a compile_fail fence names does occur.

Usage:
  analyze.py check.json                        summary plus suspect detail
  analyze.py check.json --emit-baseline        one signature per suspect
  analyze.py check.json --check-baseline FILE  exit 1 on a suspect not in FILE

A signature is `file :: section :: block hash :: sorted error codes`. It carries
no line number, so it survives edits above the block, and the hash keeps two
blocks in one section apart. CI gates on signatures absent from the baseline.
"""
import collections
import json
import pathlib
import re
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent


def harness_dependencies() -> dict[str, object]:
    """Return dependencies that the example harness declares."""
    manifest = tomllib.loads((HERE / "Cargo.toml").read_text(encoding="utf-8"))
    return manifest.get("dependencies", {})


HARNESS_DEPENDENCIES = harness_dependencies()
HARNESS_CRATES = {name.replace("-", "_") for name in HARNESS_DEPENDENCIES}
REQUIRED_EXTERNAL_CRATES = {"criterion", "libfuzzer_sys", "nix", "rayon"}

# Errors that mean "this name is defined in the prose, not in the block".
RESOLUTION_CODES = {
    "E0405",  # cannot find trait
    "E0412",  # cannot find type
    "E0422",  # cannot find struct
    "E0423",  # expected value, found something else with that name
    "E0425",  # cannot find value
    "E0432",  # unresolved import
    "E0433",  # failed to resolve
    "E0463",  # can't find crate
    "E0531",  # cannot find tuple struct or variant in pattern
    "E0583",  # file for module not found
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


def is_dependency_failure(diagnostic: dict) -> bool:
    """True when name resolution failed because the harness is incomplete."""
    message = diagnostic.get("message", "")
    patterns = (
        r"unresolved import `([^`:]+)",
        r"(?:module or crate|crate) `([^`]+)`",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match and match.group(1).split("::", 1)[0] in REQUIRED_EXTERNAL_CRATES:
            return True
    return False


def is_resolution(diagnostic: dict) -> bool:
    if is_dependency_failure(diagnostic):
        return False
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


def parse(path: str) -> tuple[dict[str, list[dict]], set[str], bool]:
    """Return the errors per example, the targets cargo touched, and whether it finished."""
    errors: dict[str, list[dict]] = collections.defaultdict(list)
    seen: set[str] = set()
    finished = False
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            reason = record.get("reason")
            if reason == "build-finished":
                finished = True
                continue
            target = (record.get("target") or {}).get("name")
            if reason == "compiler-artifact":
                if target:
                    seen.add(target)
                continue
            if reason != "compiler-message":
                continue
            if not target:
                continue
            seen.add(target)
            message = record.get("message", {})
            if message.get("level") == "error":
                errors[target].append(message)
    return errors, seen, finished


def unbuilt(manifest: dict, seen: set[str]) -> list[str]:
    """Examples that were generated but never appear in cargo's output."""
    return sorted(
        name
        for name, info in manifest.items()
        if info.get("mode") != "ignore" and name not in seen
    )


def compile_fail_failures(manifest: dict, errors: dict[str, list[dict]]) -> list[str]:
    """compile_fail examples that compiled, or missed the codes their fence names."""
    problems = []
    for name, info in sorted(manifest.items()):
        if info.get("mode") != "compile_fail":
            continue
        where = f"{info.get('file', '?')}:{info.get('line', 0)}"
        found = {code_of(d) for d in errors.get(name, [])}
        if not errors.get(name):
            problems.append(f"{where}: tagged compile_fail, but it compiles")
            continue
        missing = [c for c in info.get("codes", []) if c not in found]
        if missing:
            seen = ",".join(sorted(c for c in found if c)) or "no coded error"
            problems.append(
                f"{where}: fence expects {','.join(missing)}, cargo reported {seen}"
            )
    return problems


def weak_compile_fail(manifest: dict, errors: dict[str, list[dict]]) -> list[str]:
    """compile_fail examples that fail only because a name does not resolve.

    These do not demonstrate what the prose says they demonstrate. Naming the
    expected code in the fence is the fix. Reported, not gated: a fragment that
    also carries the intended error is common and legitimate.
    """
    weak = []
    for name, info in sorted(manifest.items()):
        if info.get("mode") != "compile_fail" or info.get("codes"):
            continue
        diagnostics = errors.get(name, [])
        if diagnostics and all(is_resolution(d) for d in diagnostics):
            weak.append(f"{info.get('file', '?')}:{info.get('line', 0)}")
    return weak


def require_cargo_ran(path: str, finished: bool, seen: set[str]) -> None:
    """Exit non-zero when the output does not prove cargo compiled something."""
    if finished and seen:
        return
    print("FAIL: the compile check did not run.\n")
    if not finished:
        print(f"  {path} carries no build-finished record.")
    if not seen:
        print(f"  {path} names no target at all.")
    stderr_path = pathlib.Path(path).with_suffix(".err")
    if stderr_path.is_file():
        tail = stderr_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if tail:
            print(f"\ncargo wrote to {stderr_path.name}:\n")
            for line in tail[:20]:
                print(f"  {line}")
    print(
        "\nThis is a broken harness, not a clean catalog. Common causes: a"
        " dependency in\nchecks/Cargo.toml does not resolve, the manifest is"
        " malformed, or the pinned\ntoolchain is unavailable."
    )
    sys.exit(1)


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
    errors, seen, finished = parse(path)
    require_cargo_ran(path, finished, seen)

    missing = unbuilt(manifest, seen)
    if missing:
        print(f"FAIL: {len(missing)} generated example(s) never reached the compiler:\n")
        for name in missing[:20]:
            info = manifest[name]
            print(f"  {info.get('file', '?')}:{info.get('line', 0)}")
        print("\nCoverage dropped without a fence tag saying so. Do not accept this run.")
        return 1

    broken = compile_fail_failures(manifest, errors)
    if broken:
        print(f"FAIL: {len(broken)} compile_fail block(s) do not fail as tagged:\n")
        for problem in broken:
            print(f"  {problem}")
        print(
            "\nA compile_fail block that compiles is a claim the language no"
            " longer supports.\nFix the block, retag it, or correct the expected"
            " code in the fence."
        )
        return 1

    # Only the compile-mode examples take part in the buckets below. A
    # compile_fail example is expected to fail and was gated above.
    compile_errors = {
        name: diagnostics
        for name, diagnostics in errors.items()
        if manifest.get(name, {}).get("mode") == "compile"
    }
    fragment, artifact, low, suspects = classify(compile_errors)

    def signature(example: str, diagnostics: list[dict]) -> str:
        info = manifest.get(example, {})
        tokens = ",".join(sorted({token(d) for d in diagnostics}))
        return (
            f"{info.get('file', '?')} :: {info.get('section', '?')}"
            f" :: {info.get('hash', '?')} :: {tokens}"
        )

    signatures = sorted({signature(e, d) for e, d in suspects.items()})

    if "--emit-baseline" in args:
        print("# Compile suspects accepted as known. Regenerate with:")
        print("#   python3 checks/analyze.py check.json --emit-baseline > checks/baseline.txt")
        print("# CI fails on any signature that is not listed here.")
        print("\n".join(signatures))
        return 0

    modes = collections.Counter(info.get("mode") for info in manifest.values())
    checked = modes["compile"]
    clean = checked - len(compile_errors)

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
        weak = weak_compile_fail(manifest, errors)
        print(
            f"OK: {clean}/{checked} compile blocks build clean,"
            f" {modes['compile_fail']} compile_fail blocks fail as tagged,"
            f" {modes['ignore']} not checked"
        )
        if weak:
            print(
                f"note: {len(weak)} compile_fail block(s) fail only on an undefined name."
                " Name the expected code in the fence to pin what they prove."
            )
        print(f"OK: no new compile suspects ({len(signatures)} known, all in the baseline)")
        return 0

    total = sum(modes.values())
    print("== catalog coverage ==")
    print(f"rust blocks                 : {total}")
    print(f"  must compile              : {checked}")
    print(f"  must not compile          : {modes['compile_fail']}")
    print(f"  not checked (ignore)      : {modes['ignore']}")
    print()
    print("== compile-check summary ==")
    print(f"compiled clean              : {clean}")
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
        seen_lines = set()
        for diagnostic in diagnostics:
            code = code_of(diagnostic) or "----"
            first = diagnostic.get("message", "").splitlines()[0]
            if (code, first) in seen_lines:
                continue
            seen_lines.add((code, first))
            print(f"    {code}: {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
