#!/usr/bin/env python3
"""Tests for the parsers of the lint gate. No cargo.

Run:
    python3 checks/test_lint_gate.py
"""
import importlib.util
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "lint_gate.py"
SPEC = importlib.util.spec_from_file_location("lint_gate", SOURCE)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

TABLE = """[workspace.lints.rust]
missing_docs = "warn"

[workspace.lints.clippy]
pedantic = { level = "warn", priority = -1 }
unwrap_used = "warn"
panic = { level = "deny" }
redundant_pub_crate = "allow"

[workspace.lints.rustdoc]
bare_urls = "warn"
"""


class Parsers(unittest.TestCase):
    def test_named_lints_skip_groups_rustdoc_and_allow(self):
        self.assertEqual(gate.named_lints(TABLE), {"missing_docs", "clippy::unwrap_used", "clippy::panic"})

    def test_toml_block_takes_the_block_after_the_heading(self):
        markdown = "## A\n```toml\na = 1\n```\n## B\n```toml\nb = 2\n```\n"
        self.assertEqual(gate.toml_block(markdown, "## B"), "b = 2\n")

    def test_markers_ignore_comment_lines_and_qualify_clippy_names(self):
        gate.RUSTC_LINTS.clear()
        gate.RUSTC_LINTS.add("missing_docs")
        source = "//! See the `// expect: x` marker.\npub fn f() {} // expect: missing_docs, unwrap_used\n"
        self.assertEqual(gate.markers(source), {"missing_docs": [2], "clippy::unwrap_used": [2]})

    def test_the_real_template_parses_and_every_named_lint_has_a_marker(self):
        templates = gate.TEMPLATES.read_text(encoding="utf-8")
        expected = gate.named_lints(gate.toml_block(templates, "## Strict template"))
        gate.RUSTC_LINTS.clear()
        gate.RUSTC_LINTS.update(n for n in expected if not n.startswith("clippy::"))
        marked = gate.markers(gate.VIOLATIONS.read_text(encoding="utf-8"))
        self.assertEqual(expected, set(marked))

    def test_unknown_lint_codes_are_name_problems(self):
        self.assertIn("E0602", gate.NAME_PROBLEMS)
        self.assertIn("renamed_and_removed_lints", gate.NAME_PROBLEMS)


if __name__ == "__main__":
    unittest.main()
