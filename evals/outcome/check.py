#!/usr/bin/env python3
"""Offline gate for the outcome evaluation suite in evals/outcome/.

The suite itself runs under `claude plugin eval` and needs a key. This gate needs neither: it
checks that every case is well formed and that every fixture still plants the defect it claims.

    python3 evals/outcome/check.py           # structure, then fixtures (needs cargo, no network)
    python3 evals/outcome/check.py --lint    # structure only

Structure: every case directory is in cases.toml and the reverse; the case names the bundle of
its skill; every bundle has a case; case.yaml keeps the suite's floor (schema 1.1, three runs or
more, the scaffold, an offline cargo, a skill-fired indicator, at least one scored grader); the
prompt names no skill; every graders/*.md has a known type and both a PASS and a FAIL line.

Fixtures: the scaffold builds the workspace in a temporary directory; every file that a grader
reads must exist there; `cargo test` on it must match `fixture` in cases.toml; and each
probe/*.rs must compile and then fail. Then solution/, a reference fix, goes over the workspace,
and `cargo test` with every probe must pass. Cargo runs on the toolchain that
checks/rust-toolchain.toml pins, so a local run matches CI.

A green gate proves that the cases are runnable, that each probe fails on the fixture and passes
on one correct fix, and that a hang is a hang. It does not prove that a grader is fair or that a
case discriminates; only a recorded eval run shows that.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SKILLS = ROOT / "skills"
BUNDLES = ROOT / "bundles.toml"
CASES = HERE / "cases.toml"
TOOLCHAIN = ROOT / "checks" / "rust-toolchain.toml"

GRADER_TYPES = {"regex", "tool_order", "tool_used", "file_exists", "llm", "baseline"}
FIXTURE_STATES = {"pass", "fail", "hang"}
MIN_RUNS = 3
BUILD_TIMEOUT = 300
TEST_TIMEOUT = 30


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def skill_bundles(bundles: dict) -> dict[str, str]:
    return {
        skill: name
        for name, bundle in bundles.get("bundles", {}).items()
        for skill in bundle.get("skills", [])
    }


def scalar(text: str, key: str) -> str | None:
    """Returns a top-level `key: value` from case.yaml, without quotes. Nested keys need indent."""
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", text, re.M)
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def folded_block(text: str, key: str) -> str:
    """Returns the lines of a `key: >-` block scalar at any indent, joined by spaces."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(rf"^(\s*){re.escape(key)}:\s*[>|]-?\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        body = []
        for following in lines[i + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following.strip())
        return " ".join(part for part in body if part)
    return ""


def block(text: str, name: str) -> str:
    """Returns the lines of the grader list item `- name: <name>` in case.yaml."""
    match = re.search(rf"^(\s*)- name:\s*{re.escape(name)}\s*$", text, re.M)
    if not match:
        return ""
    lines = [match.group(0)]
    for line in text[match.end():].splitlines()[1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= len(match.group(1)):
            break
        lines.append(line)
    return "\n".join(lines)


def skill_fired_matches(text: str, skill: str) -> bool:
    """True if the skill-fired grader is a tool_used grader on Skill whose single-quoted
    input_match ends in `skill`. The suite writes every input_match in single quotes."""
    item = block(text, "skill-fired")
    pattern = re.search(r"^\s*input_match:\s*'(.*)'\s*$", item, re.M)
    return (
        re.search(r"^\s*type:\s*tool_used\s*$", item, re.M) is not None
        and re.search(r"^\s*tool:\s*Skill\s*$", item, re.M) is not None
        and pattern is not None
        and re.search(rf'(?:\)\?|"){re.escape(skill)}"$', pattern.group(1)) is not None
    )


def grader_paths(case_dir: Path) -> list[str]:
    """Returns every `path:` a grader reads, from case.yaml and from graders/*.md frontmatter."""
    texts = []
    if (case_dir / "case.yaml").is_file():
        texts.append((case_dir / "case.yaml").read_text(encoding="utf-8"))
    for grader in sorted((case_dir / "graders").glob("*.md")):
        front = re.match(r"^---\s*\n(.*?)\n---", grader.read_text(encoding="utf-8"), re.S)
        texts.append(front.group(1) if front else "")
    found = []
    for text in texts:
        found += [p.strip("'\"") for p in re.findall(r"\bpath:\s*([^\s,}]+)", text)]
    return sorted(set(found))


def lint_grader_file(path: Path) -> list[str]:
    errors = []
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not match:
        return [f"{path}: needs YAML frontmatter between two --- lines"]
    front, body = match.groups()
    kind = scalar(front, "type")
    if kind not in GRADER_TYPES:
        errors.append(f"{path}: type is {kind!r}, not one of {sorted(GRADER_TYPES)}")
    if not re.search(r"^PASS\b", body, re.M) or not re.search(r"^FAIL\b", body, re.M):
        errors.append(f"{path}: the criteria need a line that starts with PASS and one with FAIL")
    return errors


def lint_case(case_dir: Path, entry: dict, bundle_of: dict[str, str], skill_names: set[str]) -> list[str]:
    name = case_dir.name
    where = f"evals/outcome/{name}"
    errors: list[str] = []

    skill = entry.get("skill")
    if skill not in skill_names:
        errors.append(f"cases.toml: {name} names skill {skill!r}, which is not in skills/")
    elif not name.startswith(f"{bundle_of.get(skill, '?')}-"):
        errors.append(f"{where}: the name must start with '{bundle_of.get(skill)}-', the bundle of {skill}")
    if entry.get("fixture") not in FIXTURE_STATES:
        errors.append(f"cases.toml: {name} fixture must be one of {sorted(FIXTURE_STATES)}")

    yaml_path = case_dir / "case.yaml"
    if not yaml_path.is_file():
        return errors + [f"{where}: case.yaml is missing"]
    text = yaml_path.read_text(encoding="utf-8")

    if scalar(text, "schema_version") != "1.1":
        errors.append(f"{where}/case.yaml: schema_version must be \"1.1\"")
    if scalar(text, "name") != name:
        errors.append(f"{where}/case.yaml: name must equal the directory name {name!r}")
    runs = scalar(text, "runs")
    if not (runs and runs.isdigit() and int(runs) >= MIN_RUNS):
        errors.append(f"{where}/case.yaml: runs must be {MIN_RUNS} or more")
    tags = scalar(text, "tags") or ""
    for tag in ("outcome", bundle_of.get(skill or "", "?"), skill or "?"):
        if not re.search(rf"[\[, ]{re.escape(tag)}[\],]", tags):
            errors.append(f"{where}/case.yaml: tags must include {tag!r}")
    if not re.search(r"^\s+scaffold_script:\s*scaffold\.sh\s*$", text, re.M):
        errors.append(f"{where}/case.yaml: context.scaffold_script must be scaffold.sh")
    if not re.search(r"^\s+CARGO_NET_OFFLINE:\s*\"true\"\s*$", text, re.M):
        errors.append(f"{where}/case.yaml: execution.env must set CARGO_NET_OFFLINE: \"true\"")

    prompt = folded_block(text, "prompt")
    if not prompt:
        errors.append(f"{where}/case.yaml: execution.prompt must be a folded block (prompt: >-)")
    for other in sorted(skill_names):
        if re.search(rf"(?<![\w-]){re.escape(other)}(?![\w-])", prompt):
            errors.append(f"{where}/case.yaml: the prompt names the skill {other!r}; a case must not")

    if skill is None or not skill_fired_matches(text, skill):
        errors.append(f"{where}/case.yaml: needs a skill-fired tool_used grader that matches {skill!r}")
    yaml_types = re.findall(r"^\s+type:\s*(\S+)\s*$", text, re.M)
    for kind in yaml_types:
        if kind not in GRADER_TYPES:
            errors.append(f"{where}/case.yaml: unknown grader type {kind!r}")

    grader_files = sorted((case_dir / "graders").glob("*.md"))
    for path in grader_files:
        errors += [e.replace(str(ROOT) + "/", "") for e in lint_grader_file(path)]
    scored = [k for k in yaml_types if k != "tool_used"] + grader_files
    if not scored:
        errors.append(f"{where}: needs at least one scored grader besides tool_used")

    for path in grader_paths(case_dir):
        if path.startswith("/") or ".." in Path(path).parts:
            errors.append(f"{where}: grader path {path!r} must be relative to the workspace")
    needs_solution = entry.get("fixture") != "pass" or any((case_dir / "probe").glob("*.rs"))
    if needs_solution and not any((case_dir / "solution").rglob("*.rs")):
        errors.append(f"{where}: a case with a probe or a failing fixture needs a solution/ fix")

    scaffold = case_dir / "scaffold.sh"
    if not scaffold.is_file():
        errors.append(f"{where}: scaffold.sh is missing")
    elif not os.access(scaffold, os.X_OK):
        errors.append(f"{where}/scaffold.sh: must be executable")
    for required in ("files/Cargo.toml", "files/Cargo.lock"):
        if not (case_dir / required).is_file():
            errors.append(f"{where}: {required} is missing")
    return errors


def lint(cases: dict, bundles: dict, skill_names: set[str], root: Path = HERE) -> list[str]:
    errors: list[str] = []
    entries = cases.get("cases", {})
    on_disk = {p.parent.name for p in root.glob("*/case.yaml")}
    for name in sorted(on_disk - entries.keys()):
        errors.append(f"evals/outcome/{name}: not in cases.toml")
    for name in sorted(entries.keys() - on_disk):
        errors.append(f"cases.toml: {name} has no evals/outcome/{name}/case.yaml")

    bundle_of = skill_bundles(bundles)
    for name in sorted(entries.keys() & on_disk):
        errors += lint_case(root / name, entries[name], bundle_of, skill_names)

    covered = {bundle_of.get(entry.get("skill")) for entry in entries.values()}
    for bundle in sorted(bundles.get("bundles", {}).keys() - covered):
        errors.append(f"cases.toml: bundle {bundle!r} has no outcome case")
    return errors


def cargo(args: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[str, str]:
    """Runs cargo; returns ("pass" | "fail" | "hang", tail of output).

    cargo runs in its own process group. On a timeout the whole group is killed, so a deadlocked
    test binary does not outlive the gate.
    """
    proc = subprocess.Popen(
        ["cargo", *args], cwd=cwd, env=env, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # the group exited between the timeout and the kill
        proc.communicate()
        return "hang", f"no result after {timeout}s"
    return ("pass" if proc.returncode == 0 else "fail"), "\n".join((out or "").splitlines()[-15:])


def check_fixture(case_dir: Path, entry: dict, channel: str) -> list[str]:
    where = f"evals/outcome/{case_dir.name}"
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"outcome-{case_dir.name}-") as tmp:
        work = Path(tmp) / "workspace"
        work.mkdir()
        env = {
            **os.environ,
            "RUSTUP_TOOLCHAIN": channel,
            "CARGO_TARGET_DIR": str(Path(tmp) / "target"),
            "CARGO_NET_OFFLINE": "true",
            "CARGO_TERM_COLOR": "never",
        }
        scaffold = subprocess.run(
            ["bash", str(case_dir / "scaffold.sh")], cwd=work,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if scaffold.returncode != 0:
            return [f"{where}: scaffold.sh failed:\n{scaffold.stdout}"]
        for leaked in ("probe", "graders", "solution", "case.yaml"):
            if (work / leaked).exists():
                errors.append(f"{where}: the scaffold copied {leaked} into the workspace")
        for path in grader_paths(case_dir):
            if not (work / path).is_file():
                errors.append(f"{where}: a grader reads {path}, which the scaffold does not create")

        state, log = cargo(["test", "--locked", "--no-run"], work, env, BUILD_TIMEOUT)
        if state != "pass":
            return errors + [f"{where}: the fixture does not build:\n{log}"]
        state, log = cargo(["test", "--locked"], work, env, TEST_TIMEOUT)
        if state != entry.get("fixture"):
            errors.append(f"{where}: cargo test should {entry.get('fixture')} on the fixture, it did {state}:\n{log}")

        probes = sorted((case_dir / "probe").glob("*.rs"))
        for probe in probes:
            tests = work / "tests"
            tests.mkdir(exist_ok=True)
            shutil.copy(probe, tests / probe.name)
            target = ["--locked", "--test", probe.stem]
            state, log = cargo(["test", *target, "--no-run"], work, env, BUILD_TIMEOUT)
            if state != "pass":
                errors.append(f"{where}/probe/{probe.name}: does not compile against the fixture:\n{log}")
                continue
            state, log = cargo(["test", *target], work, env, TEST_TIMEOUT)
            if state != "fail":
                errors.append(f"{where}/probe/{probe.name}: should fail on the fixture, it did {state}")

        solution = case_dir / "solution"
        if solution.is_dir():
            # shutil.copy, not the default copy2: a copied mtime older than the last build makes
            # cargo reuse the stale test binary of the fixture.
            shutil.copytree(solution, work, dirs_exist_ok=True, copy_function=shutil.copy)
            state, log = cargo(["test", "--locked", "--no-run"], work, env, BUILD_TIMEOUT)
            if state == "pass":
                state, log = cargo(["test", "--locked"], work, env, TEST_TIMEOUT)
            if state != "pass":
                errors.append(f"{where}/solution: cargo test with the probes should pass, it did {state}:\n{log}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lint", action="store_true", help="check structure only; run no cargo")
    args = parser.parse_args()

    cases = load_toml(CASES)
    skill_names = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
    errors = lint(cases, load_toml(BUNDLES), skill_names)
    entries = cases.get("cases", {})
    if not errors and not args.lint:
        if shutil.which("cargo") is None:
            errors.append("cargo is not on PATH; run with --lint to check structure only")
        else:
            channel = load_toml(TOOLCHAIN)["toolchain"]["channel"]
            for name in sorted(entries):
                errors += check_fixture(HERE / name, entries[name], channel)

    for error in errors:
        print(f"  {error}")
    if errors:
        print(f"outcome suite: {len(errors)} problem(s)")
        return 1
    scope = "structure" if args.lint else "structure and fixtures"
    print(f"  {len(entries)} outcome case(s): {scope} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
