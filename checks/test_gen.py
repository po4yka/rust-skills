#!/usr/bin/env python3
"""Regression tests for executable Rust fences."""
import unittest

import gen


class TestRunFence(unittest.TestCase):
    def test_run_fence_is_known(self):
        self.assertEqual(gen.parse_fence("```rust,run"), ("run", []))

    def test_run_fence_accepts_a_complete_main(self):
        self.assertIsNone(gen.run_problem("fn main() { assert_eq!(2 + 2, 4); }"))

    def test_run_fence_requires_main(self):
        self.assertIn("fn main", gen.run_problem("assert!(true);") or "")

    def test_run_fence_rejects_placeholders(self):
        for marker in ("todo!()", "unimplemented!()", "// TODO", "// FIXME"):
            with self.subTest(marker=marker):
                self.assertIsNotNone(gen.run_problem(f"fn main() {{ {marker}; }}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
