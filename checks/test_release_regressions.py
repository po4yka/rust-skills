#!/usr/bin/env python3
"""Fail-closed checks for the release-regression runner. No Rust build."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name("release_regressions.py")
SPEC = importlib.util.spec_from_file_location("release_regressions", SOURCE)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class ExpectedFailures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def command(self, code):
        return [sys.executable, "-c", code]

    def test_success_text_cannot_satisfy_expected_failure(self):
        with self.assertRaises(gate.Failure):
            gate.run(self.command("print('E0277')"), self.root, error="E0277")

    def test_unrelated_failure_cannot_satisfy_expected_failure(self):
        with self.assertRaises(gate.Failure):
            gate.run(self.command("raise SystemExit('missing linker')"), self.root, error="E0277")

    def test_failure_without_an_expectation_is_rejected(self):
        with self.assertRaises(gate.Failure):
            gate.run(self.command("raise SystemExit(1)"), self.root)

    def test_expected_error_requires_both_nonzero_exit_and_diagnostic(self):
        result = gate.run(self.command("raise SystemExit('E0277')"), self.root, error="E0277")
        self.assertNotEqual(result.returncode, 0)

    def test_a_hung_probe_does_not_count_as_expected_failure(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            gate.run(self.command("import time; time.sleep(2)"), self.root, error="E0277", timeout=0.05)

    def test_build_environment_has_no_service_tokens_or_injected_flags(self):
        with patch.dict(os.environ, {"CARGO_REGISTRY_TOKEN": "test-token", "GITHUB_TOKEN": "test-token",
                                    "OPENAI_API_KEY": "test-token", "RUSTFLAGS": "--cfg wrong",
                                    "RUSTC_BOOTSTRAP": "1", "CARGO_TARGET_DIR": "/wrong"}):
            env = gate.environment(self.root)
        for key in ("CARGO_REGISTRY_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "RUSTFLAGS", "RUSTC_BOOTSTRAP"):
            self.assertNotIn(key, env)
        self.assertEqual(env["CARGO_HOME"], str(self.root / "cargo-home"))
        self.assertEqual(env["CARGO_TARGET_DIR"], str(self.root / "target"))


if __name__ == "__main__":
    unittest.main()
