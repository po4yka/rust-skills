#!/usr/bin/env python3
"""Tests for the parts of plugin_install.py that run without the Claude Code CLI.

The install check is only as good as its reading of `claude plugin details`. A
parser that returns an empty list for output it does not understand would let
every plugin pass, so an unreadable inventory must come back as None.

Run:
    python3 checks/test_plugin_install.py
"""
import importlib.util
import json
import pathlib
import tomllib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "plugin_install.py"
SPEC = importlib.util.spec_from_file_location("plugin_install", SOURCE)
assert SPEC and SPEC.loader, f"cannot load {SOURCE}"
plugin_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin_install)

# The shape Claude Code 2.1.316 prints.
DETAILS = """rust-skills
  Description: Correctness and testing: 4 Rust agent skills.
  Source: rust-skills-testing@rust-skills

Component inventory
  Skills (4)  rust-panic-safety, rust-sanitizers-miri, rust-tdd, rust-test-tools
  Agents (0)
"""


class TestParseSkills(unittest.TestCase):
    def test_the_inventory_line_is_read(self):
        self.assertEqual(
            plugin_install.parse_skills(DETAILS),
            ["rust-panic-safety", "rust-sanitizers-miri", "rust-tdd", "rust-test-tools"],
        )

    def test_colour_codes_are_ignored(self):
        coloured = DETAILS.replace("Skills (4)", "\x1b[1mSkills (4)\x1b[0m")
        self.assertEqual(len(plugin_install.parse_skills(coloured) or []), 4)

    def test_a_count_that_disagrees_with_the_names_is_unreadable(self):
        # A wrapped or truncated list must not pass as a shorter inventory.
        self.assertIsNone(plugin_install.parse_skills(DETAILS.replace("Skills (4)", "Skills (5)")))

    def test_output_without_an_inventory_is_unreadable(self):
        self.assertIsNone(plugin_install.parse_skills("Plugin not found"))

    def test_an_empty_inventory_is_read_as_empty(self):
        # The next line must not be read as a skill name.
        self.assertEqual(plugin_install.parse_skills("  Skills (0)\n  Agents (0)\n"), [])


class TestExpectedSkills(unittest.TestCase):
    """The expectation comes from bundles.toml, never from the entry under test."""

    def test_each_bundle_plugin_expects_its_bundle(self):
        manifest = {
            "name": "rust-skills",
            "plugins": [{"name": "rust-skills-testing", "skills": ["./skills/rust-unsafe"]}],
        }
        bundles = tomllib.loads(plugin_install.BUNDLES.read_text(encoding="utf-8"))["bundles"]
        expected = plugin_install.expected_skills(manifest)
        self.assertEqual(expected["rust-skills-testing"], sorted(bundles["testing"]["skills"]))

    def test_the_full_catalog_expects_every_skill(self):
        manifest = {"name": "rust-skills", "plugins": [{"name": "rust-skills"}]}
        skills = sorted(d.name for d in (plugin_install.ROOT / "skills").glob("*/") if (d / "SKILL.md").is_file())
        self.assertEqual(plugin_install.expected_skills(manifest)["rust-skills"], skills)

    def test_an_entry_that_no_bundle_explains_is_a_problem(self):
        # Its own skills list must not become its expectation and pass.
        manifest = json.loads(plugin_install.MARKETPLACE.read_text(encoding="utf-8"))
        manifest["plugins"].append({"name": "rust-skills-extra", "source": "./", "skills": ["./skills/rust-unsafe"]})
        problems = plugin_install.entry_problems(manifest, plugin_install.expected_skills(manifest))
        self.assertEqual(len(problems), 1)
        self.assertIn("'rust-skills-extra'", problems[0])

    def test_a_bundle_without_an_entry_is_a_problem(self):
        manifest = json.loads(plugin_install.MARKETPLACE.read_text(encoding="utf-8"))
        manifest["plugins"] = [e for e in manifest["plugins"] if e["name"] != "rust-skills-ffi"]
        problems = plugin_install.entry_problems(manifest, plugin_install.expected_skills(manifest))
        self.assertEqual(problems, ["plugin 'rust-skills-ffi' has 0 marketplace entries, not 1"])

    def test_the_shipped_marketplace_has_no_entry_problem(self):
        manifest = json.loads(plugin_install.MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual(plugin_install.entry_problems(manifest, plugin_install.expected_skills(manifest)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
