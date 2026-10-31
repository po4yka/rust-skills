#!/usr/bin/env python3
"""Report drift between the pins in checks/ and what is published upstream.

    python3 scripts/drift-report.py toolchain            # Rust stable vs checks/rust-toolchain.toml
    python3 scripts/drift-report.py crates               # crates.io vs checks/Cargo.lock
    python3 scripts/drift-report.py toolchain --stable 1.99.1   # no network: compare to a given version

It prints a Markdown issue body on stdout. Exit status: 0 when the pins are current, 10 when they
drifted, 1 on an error. The weekly drift workflows open or update an issue on exit 10.

The toolchain report lists the skills whose text carries a dated claim for the pinned release
("as of Rust 1.98.1" or "as of Rust 1.98"), because those are the claims to re-probe before the
pin moves. Changing the pin also means regenerating checks/baseline.txt on the new version.

The crates report queries https://crates.io/api/v1/crates/<name> once per second, with a
User-Agent, as the crates.io crawler policy requires.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = ROOT / "checks" / "rust-toolchain.toml"
MANIFEST = ROOT / "checks" / "Cargo.toml"
LOCKFILE = ROOT / "checks" / "Cargo.lock"
SKILLS = ROOT / "skills"
CHANNEL_URL = "https://static.rust-lang.org/dist/channel-rust-stable.toml"
CRATE_URL = "https://crates.io/api/v1/crates/{}"
USER_AGENT = "rust-skills-drift-report (https://github.com/po4yka/rust-skills)"
DRIFT = 10


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_version(text: str) -> tuple[int, ...]:
    """'1.99.1 (58cf8f9c3 2026-10-13)' or '0.13.2' -> (1, 99, 1); pre-release tails are dropped."""
    match = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part) for part in match.groups())


def compatible(old: tuple[int, ...], new: tuple[int, ...]) -> bool:
    """Cargo's caret rule: the left-most non-zero component must stay the same."""
    if old[0] != 0:
        return old[0] == new[0]
    if old[1] != 0:
        return new[0] == 0 and old[1] == new[1]
    return new[:2] == (0, 0) and old[2] == new[2]


def pinned_toolchain() -> str:
    return tomllib.loads(TOOLCHAIN.read_text(encoding="utf-8"))["toolchain"]["channel"]


def published_stable() -> str:
    channel = tomllib.loads(fetch(CHANNEL_URL).decode("utf-8"))
    return channel["pkg"]["rust"]["version"]


def dated_claims(pinned: str) -> dict[str, int]:
    """Skill -> number of 'as of Rust <pinned>' claims, matching x.y.z and x.y."""
    short = ".".join(pinned.split(".")[:2])
    pattern = re.compile(rf"as of Rust (?:{re.escape(pinned)}|{re.escape(short)})(?![\d.]*\d)")
    found: dict[str, int] = {}
    for path in sorted(SKILLS.rglob("*.md")):
        hits = len(pattern.findall(path.read_text(encoding="utf-8")))
        if hits:
            skill = path.relative_to(SKILLS).parts[0]
            found[skill] = found.get(skill, 0) + hits
    return found


def toolchain_report(stable: str | None) -> int:
    pinned = pinned_toolchain()
    stable = stable or published_stable()
    if parse_version(stable) <= parse_version(pinned):
        print(f"Rust {pinned} is current (stable is {stable}).")
        return 0
    claims = dated_claims(pinned)
    print(f"`checks/rust-toolchain.toml` pins Rust **{pinned}**. The stable channel is **{stable}**.\n")
    print("Do not bump the pin by itself. A toolchain move is a catalog actualization:\n")
    print("1. Change `channel` in `checks/rust-toolchain.toml`, run `bash checks/check.sh`, and")
    print("   regenerate `checks/baseline.txt` on the new version in the same commit.")
    print("2. Re-probe every dated claim below on the new version, and relabel only the ones the")
    print("   probe confirms.")
    print("3. Record the findings in `research/` and tag the release (`docs/releasing.md`).\n")
    if claims:
        total = sum(claims.values())
        print(f"Skills with a claim dated to Rust {pinned} ({total} in {len(claims)} skills):\n")
        for skill, hits in sorted(claims.items()):
            print(f"- `{skill}`: {hits}")
    else:
        print(f"No skill carries a claim dated to Rust {pinned}.")
    return DRIFT


def dependencies() -> list[str]:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    names = []
    for name, spec in manifest.get("dependencies", {}).items():
        names.append(spec.get("package", name) if isinstance(spec, dict) else name)
    return sorted(names)


def locked_versions() -> dict[str, tuple[int, ...]]:
    """Crate -> highest locked version (a lockfile can hold several versions of one crate)."""
    lock = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    found: dict[str, tuple[int, ...]] = {}
    for package in lock.get("package", []):
        version = parse_version(package["version"])
        if version > found.get(package["name"], (-1,)):
            found[package["name"]] = version
    return found


def mentions(crate: str) -> int:
    """How many skills name the crate, as a hint for which text to re-check."""
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(crate)}(?![A-Za-z0-9_-])")
    return sum(
        1 for skill in SKILLS.iterdir()
        if skill.is_dir() and any(pattern.search(p.read_text(encoding="utf-8")) for p in skill.rglob("*.md"))
    )


def fmt(version: tuple[int, ...]) -> str:
    return ".".join(map(str, version))


def crates_report(delay: float) -> int:
    locked = locked_versions()
    rows, errors = [], []
    for index, crate in enumerate(dependencies()):
        if index:
            time.sleep(delay)
        try:
            data = json.loads(fetch(CRATE_URL.format(crate)))
            latest = parse_version(data["crate"]["max_stable_version"])
        except Exception as error:  # noqa: BLE001 - one bad crate must not hide the others
            errors.append(f"- `{crate}`: {error}")
            continue
        have = locked.get(crate)
        if have is None:
            errors.append(f"- `{crate}`: not in `checks/Cargo.lock`")
        elif latest > have:
            rows.append((crate, have, latest, compatible(have, latest)))
    if not rows and not errors:
        print("Every crate in `checks/Cargo.toml` is locked at its newest stable release.")
        return 0
    breaking = [r for r in rows if not r[3]]
    print("Crates in `checks/Cargo.toml` with a newer stable release on crates.io.\n")
    if breaking:
        print("**Semver-incompatible releases.** The skills that name these crates may describe an API")
        print("that changed. Re-check them before you raise the requirement in `checks/Cargo.toml`, in")
        print("a catalog actualization (see `docs/releasing.md`):\n")
        print("| Crate | Locked | Newest stable | Skills that name it |")
        print("| --- | --- | --- | ---: |")
        for crate, have, latest, _ in breaking:
            print(f"| `{crate}` | {fmt(have)} | {fmt(latest)} | {mentions(crate)} |")
        print()
    compatible_rows = [r for r in rows if r[3]]
    if compatible_rows:
        print("**Compatible releases.** `cargo update` inside `checks/` picks these up; Dependabot")
        print("proposes them weekly.\n")
        print("| Crate | Locked | Newest stable |")
        print("| --- | --- | --- |")
        for crate, have, latest, _ in compatible_rows:
            print(f"| `{crate}` | {fmt(have)} | {fmt(latest)} |")
        print()
    if errors:
        print("**Not checked:**\n")
        print("\n".join(errors))
    return DRIFT


def main() -> int:
    parser = argparse.ArgumentParser(description="Report toolchain or crate drift.")
    parser.add_argument("what", choices=["toolchain", "crates"])
    parser.add_argument("--stable", help="toolchain: compare to this version instead of fetching it")
    parser.add_argument("--delay", type=float, default=1.0, help="crates: seconds between requests")
    args = parser.parse_args()
    try:
        if args.what == "toolchain":
            return toolchain_report(args.stable)
        return crates_report(args.delay)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
