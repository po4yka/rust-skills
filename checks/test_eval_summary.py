#!/usr/bin/env python3
"""Run the workflow's summary program against failed and successful measurements."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TestEvalSummary(unittest.TestCase):
    def run_summary(self, content):
        workflow = (ROOT / ".github/workflows/plugin-eval.yml").read_text()
        start = workflow.index("          import json, math, os, subprocess\n")
        end = workflow.index("          PY\n", start)
        script = textwrap.dedent(workflow[start:end])
        with tempfile.TemporaryDirectory() as tmp:
            if content is not None:
                (Path(tmp) / "eval-results.json").write_text(content)
            env = {**os.environ, "SUITE": "outcome", "MODEL": "test", "JUDGE_MODEL": "test"}
            return subprocess.run(["python3", "-c", script], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=10)

    def test_missing_result_fails(self):
        result = self.run_summary(None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No result file", result.stdout)

    def test_invalid_json_fails(self):
        result = self.run_summary("{broken")
        self.assertNotEqual(result.returncode, 0)

    def test_no_plugin_fails(self):
        result = self.run_summary(json.dumps({"suite": {"plugins": []},
            "cases": [{"name": "case", "arms": {"with": [{"score": 0}]}}]}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No plugin loaded", result.stdout)

    def test_empty_measurements_fail(self):
        for cases in ([], [{"name": "case", "arms": {"with": [], "without": []}}],
                      [{"name": "case", "arms": {"with": [{}]}}]):
            with self.subTest(cases=cases):
                result = self.run_summary(json.dumps({"partial": True,
                    "suite": {"plugins": [{"name": "rust-skills"}]}, "cases": cases}))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No valid measurements", result.stdout)

    def test_valid_low_score_remains_a_measurement(self):
        result = self.run_summary(json.dumps({
            "suite": {"plugins": [{"name": "rust-skills"}], "ablation": True},
            "partial": False,
            "cases": [{"name": "case", "arms": {
                "with": [{"score": 0}], "without": [{"score": 0.5}]}}],
        }))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| case | 0.00 | 0.50 |", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
