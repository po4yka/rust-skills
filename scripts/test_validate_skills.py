#!/usr/bin/env python3
"""Regression tests for the frontmatter rules in validate-skills.py.

`split_frontmatter` reads a line as `key: value`. A YAML parser does not, and
the agent runtimes and the skills CLI use a YAML parser. Two shipped defects
came from that gap:

  a description containing `: ` made the whole skill unreadable, so the CLI
  skipped it and no install could reach it;

  a description containing ` #` was cut at that point without a warning, so
  two thirds of the routing triggers never reached the runtime.

`plain_scalar_problem` closes the gap. These tests hold it closed.

Run:
    python3 scripts/test_validate_skills.py
"""
import importlib.util
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "validate-skills.py"
SPEC = importlib.util.spec_from_file_location("validate_skills", SOURCE)
assert SPEC and SPEC.loader, f"cannot load {SOURCE}"
validate_skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_skills)
problem = validate_skills.plain_scalar_problem


class TestPlainScalar(unittest.TestCase):
    def test_ordinary_description_passes(self):
        self.assertIsNone(problem("Use when you review an unsafe block, an FFI boundary, or a transmute."))

    def test_quotes_commas_and_parentheses_pass(self):
        # Every description in the catalog carries these. They are safe inside
        # a plain scalar and must not be rejected.
        self.assertIsNone(problem('Triggers on "unsafe", "FFI", extern "C", E0793, and Box::leak.'))

    def test_a_colon_inside_the_value_is_rejected(self):
        # skills/rust-send-sync shipped this. The CLI reported
        # "Nested mappings are not allowed in compact mappings" and skipped it.
        self.assertIn("mapping key", problem("Covers the rule that generates the rest: &T is Send."))

    def test_a_trailing_colon_is_rejected(self):
        self.assertIn("mapping key", problem("Covers the following:"))

    def test_a_comment_start_is_rejected(self):
        # skills/rust-unsafe shipped this. YAML cut the description at ` #`.
        self.assertIn("comment", problem("any change that removes #![forbid(unsafe_code)] from a crate."))

    def test_a_double_colon_in_a_path_passes(self):
        # `mem::zeroed` has no space after the colons, so it stays text.
        self.assertIsNone(problem("Covers mem::zeroed, Box::leak, and std::ptr::read_unaligned."))

    def test_a_leading_indicator_is_rejected(self):
        for value in ["> folded", "| literal", "- item", "& anchor", "* alias", "# comment"]:
            with self.subTest(value=value):
                self.assertIn("indicator", problem(value))

    def test_surrounding_whitespace_is_rejected(self):
        self.assertIn("whitespace", problem("Use when you review a diff. "))

    def test_a_tab_is_rejected(self):
        self.assertIn("tab", problem("Use when you\treview a diff."))


class TestCatalog(unittest.TestCase):
    """The rule is worth nothing if the catalog does not satisfy it."""

    def test_every_shipped_frontmatter_value_is_a_clean_plain_scalar(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "skills"
        for skill in sorted(root.glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            end = text.find("\n---\n", 3)
            for line in text[4:end].split("\n"):
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                with self.subTest(skill=skill.parent.name, key=key.strip()):
                    self.assertIsNone(problem(value.strip()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
