#!/usr/bin/env python3
"""Run one command while holding a process-scoped checkout lock."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile


def default_lock(root: pathlib.Path) -> pathlib.Path:
    checkout = str(root.resolve()).encode()
    digest = hashlib.sha256(checkout).hexdigest()[:16]
    return pathlib.Path(tempfile.gettempdir()) / f"rust-skills-check-{digest}.lock"


def run_locked(lock_file: pathlib.Path, command: list[str]) -> int:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"==> waiting for check lock: {lock_file}", flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)

        environment = os.environ.copy()
        environment["RUST_SKILLS_CHECK_LOCKED"] = "1"
        return subprocess.run(command, env=environment, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--root", type=pathlib.Path)
    location.add_argument("--lock-file", type=pathlib.Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    lock_file = args.lock_file or default_lock(args.root)
    return run_locked(lock_file, command)


if __name__ == "__main__":
    sys.exit(main())
