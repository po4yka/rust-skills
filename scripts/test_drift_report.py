#!/usr/bin/env python3
"""Tests for the version logic in drift-report.py. No network.

Run:
    python3 scripts/test_drift_report.py
"""
import importlib.util
import pathlib
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "drift-report.py"
SPEC = importlib.util.spec_from_file_location("drift_report", SOURCE)
assert SPEC and SPEC.loader
drift = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drift)


class Versions(unittest.TestCase):
    def test_the_channel_version_string_parses(self):
        self.assertEqual(drift.parse_version("1.99.1 (58cf8f9c3 2026-10-13)"), (1, 99, 1))

    def test_a_pre_release_tail_is_dropped(self):
        self.assertEqual(drift.parse_version("0.32.0-beta.1"), (0, 32, 0))

    def test_caret_compatibility_follows_cargo(self):
        cases = [
            ((1, 53, 3), (1, 54, 1), True),
            ((1, 0, 0), (2, 0, 0), False),
            ((0, 12, 5), (0, 12, 9), True),
            ((0, 12, 5), (0, 13, 0), False),
            ((0, 0, 3), (0, 0, 4), False),
        ]
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertEqual(drift.compatible(old, new), expected)


class DatedClaims(unittest.TestCase):
    def claims(self, text: str, pinned: str = "1.98.1") -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            skill = pathlib.Path(tmp) / "rust-a"
            skill.mkdir()
            (skill / "SKILL.md").write_text(text, encoding="utf-8")
            original = drift.SKILLS
            try:
                drift.SKILLS = pathlib.Path(tmp)
                return drift.dated_claims(pinned)
            finally:
                drift.SKILLS = original

    def test_full_and_short_versions_count(self):
        self.assertEqual(self.claims("as of Rust 1.98.1, x. As well, as of Rust 1.98. y"), {"rust-a": 2})

    def test_a_longer_version_does_not_count(self):
        self.assertEqual(self.claims("as of Rust 1.98.10 and as of Rust 1.980"), {})

    def test_another_release_does_not_count(self):
        self.assertEqual(self.claims("as of Rust 1.97.1"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
