#!/usr/bin/env python3
"""Regression test for serialization of shared check artifacts."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
LOCKER = HERE / "with_lock.py"


class TestCheckLock(unittest.TestCase):
    def test_second_process_waits_for_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            lock = directory / "check.lock"
            events = directory / "events"
            ready = directory / "ready"

            first_code = """import pathlib, sys, time
events, ready = map(pathlib.Path, sys.argv[1:])
events.write_text("first-start\\n", encoding="utf-8")
ready.touch()
time.sleep(0.4)
with events.open("a", encoding="utf-8") as stream:
    stream.write("first-end\\n")
"""
            second_code = """import pathlib, sys
with pathlib.Path(sys.argv[1]).open("a", encoding="utf-8") as stream:
    stream.write("second\\n")
"""

            first = subprocess.Popen(
                [
                    sys.executable,
                    str(LOCKER),
                    "--lock-file",
                    str(lock),
                    "--",
                    sys.executable,
                    "-c",
                    first_code,
                    str(events),
                    str(ready),
                ]
            )
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists(), "first process did not acquire the lock")

            second = subprocess.run(
                [
                    sys.executable,
                    str(LOCKER),
                    "--lock-file",
                    str(lock),
                    "--",
                    sys.executable,
                    "-c",
                    second_code,
                    str(events),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.wait(timeout=5), 0)
            self.assertEqual(
                events.read_text(encoding="utf-8").splitlines(),
                ["first-start", "first-end", "second"],
            )
            self.assertIn("waiting for check lock", second.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
