#!/usr/bin/env python3
"""Tests for the outcome suite's structure lint. No cargo, no network, no key.

Run:
    python3 evals/outcome/test_check.py
"""
import importlib.util
import pathlib
import shutil
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "check.py"
SPEC = importlib.util.spec_from_file_location("outcome_check", SOURCE)
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

SKILLS = {"rust-a", "rust-b"}
BUNDLES = {"bundles": {"lang": {"skills": ["rust-a"]}, "test": {"skills": ["rust-b"]}}}
CASES = {"cases": {"lang-one": {"skill": "rust-a", "fixture": "hang"},
                   "test-one": {"skill": "rust-b", "fixture": "pass"}}}

CASE_YAML = """schema_version: "1.1"
name: {name}
tags: [outcome, {bundle}, {skill}]
runs: 3
context:
  scaffold_script: scaffold.sh
execution:
  env:
    CARGO_NET_OFFLINE: "true"
  prompt: >-
    {prompt}
graders:
  - name: skill-fired
    type: tool_used
    tool: Skill
    input_match: '"skill"\\s*:\\s*"(?:[\\w-]+:)?{skill}"'
  - name: scored
    type: regex
    pattern: 'x'
"""

GRADER = """---
type: llm
focus: trace
---

PASS if the tests pass.
FAIL if they do not.
"""


class Lint(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.write_case("lang-one", "lang", "rust-a")
        self.write_case("test-one", "test", "rust-b")

    def write_case(self, name, bundle, skill, prompt="The test hangs. Fix it.", runs=3):
        case = self.root / name
        (case / "files").mkdir(parents=True, exist_ok=True)
        (case / "graders").mkdir(exist_ok=True)
        text = CASE_YAML.format(name=name, bundle=bundle, skill=skill, prompt=prompt)
        (case / "case.yaml").write_text(text.replace("runs: 3", f"runs: {runs}"))
        (case / "graders" / "tests.md").write_text(GRADER)
        (case / "files" / "Cargo.toml").write_text("[package]\n")
        (case / "files" / "Cargo.lock").write_text("version = 4\n")
        (case / "solution" / "src").mkdir(parents=True, exist_ok=True)
        (case / "solution" / "src" / "lib.rs").write_text("")
        scaffold = case / "scaffold.sh"
        scaffold.write_text("#!/usr/bin/env bash\n")
        scaffold.chmod(0o755)

    def lint(self, cases=CASES):
        return check.lint(cases, BUNDLES, SKILLS, root=self.root)

    def test_a_complete_suite_passes(self):
        self.assertEqual(self.lint(), [])

    def test_the_real_suite_passes(self):
        skills = {p.parent.name for p in check.SKILLS.glob("*/SKILL.md")}
        errors = check.lint(check.load_toml(check.CASES), check.load_toml(check.BUNDLES), skills)
        self.assertEqual(errors, [])

    def test_a_prompt_that_names_a_skill_fails(self):
        self.write_case("lang-one", "lang", "rust-a", prompt="Use rust-b to fix the hang.")
        self.assertTrue(any("names the skill 'rust-b'" in e for e in self.lint()))

    def test_a_case_missing_from_the_manifest_fails(self):
        self.write_case("lang-two", "lang", "rust-a")
        self.assertIn("evals/outcome/lang-two: not in cases.toml", self.lint())

    def test_a_bundle_without_a_case_fails(self):
        shutil.rmtree(self.root / "test-one")
        cases = {"cases": {"lang-one": CASES["cases"]["lang-one"]}}
        self.assertIn("cases.toml: bundle 'test' has no outcome case", self.lint(cases))

    def test_a_name_outside_the_skill_bundle_fails(self):
        self.write_case("test-two", "lang", "rust-a")
        cases = {"cases": {**CASES["cases"], "test-two": {"skill": "rust-a", "fixture": "pass"}}}
        self.assertTrue(any("must start with 'lang-'" in e for e in self.lint(cases)))

    def test_fewer_than_three_runs_fails(self):
        self.write_case("lang-one", "lang", "rust-a", runs=2)
        self.assertTrue(any("runs must be 3 or more" in e for e in self.lint()))

    def test_a_grader_without_a_fail_line_fails(self):
        (self.root / "lang-one" / "graders" / "tests.md").write_text(GRADER.replace("FAIL", "Else"))
        self.assertTrue(any("one with FAIL" in e for e in self.lint()))

    def test_an_unknown_grader_type_fails(self):
        (self.root / "lang-one" / "graders" / "tests.md").write_text(GRADER.replace("llm", "rubric"))
        self.assertTrue(any("type is 'rubric'" in e for e in self.lint()))

    def test_a_scaffold_that_is_not_executable_fails(self):
        (self.root / "lang-one" / "scaffold.sh").chmod(0o644)
        self.assertIn("evals/outcome/lang-one/scaffold.sh: must be executable", self.lint())

    def test_an_unknown_fixture_state_fails(self):
        cases = {"cases": {**CASES["cases"], "lang-one": {"skill": "rust-a", "fixture": "slow"}}}
        self.assertTrue(any("fixture must be one of" in e for e in self.lint(cases)))

    def edit_yaml(self, old, new, case="lang-one"):
        path = self.root / case / "case.yaml"
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

    def test_a_failing_fixture_without_a_solution_fails(self):
        shutil.rmtree(self.root / "lang-one" / "solution")
        self.assertTrue(any("needs a solution/ fix" in e for e in self.lint()))

    def test_a_skill_fired_grader_for_a_longer_skill_name_fails(self):
        self.edit_yaml('?rust-a"', '?rust-a-extra"')
        self.assertTrue(any("skill-fired" in e for e in self.lint()))

    def test_a_skill_fired_grader_on_another_tool_fails(self):
        self.edit_yaml("tool: Skill", "tool: Bash")
        self.assertTrue(any("skill-fired" in e for e in self.lint()))

    def test_a_reordered_skill_fired_grader_passes(self):
        self.edit_yaml("    type: tool_used\n    tool: Skill\n", "    tool: Skill\n    type: tool_used\n")
        self.assertEqual(self.lint(), [])

    def test_a_case_without_offline_cargo_fails(self):
        self.edit_yaml('CARGO_NET_OFFLINE: "true"', 'CARGO_HOME: "/tmp"')
        self.assertTrue(any("CARGO_NET_OFFLINE" in e for e in self.lint()))

    def test_an_old_schema_version_fails(self):
        self.edit_yaml('schema_version: "1.1"', 'schema_version: "1.0"')
        self.assertTrue(any("schema_version" in e for e in self.lint()))

    def test_a_missing_skill_tag_fails(self):
        self.edit_yaml("tags: [outcome, lang, rust-a]", "tags: [outcome, lang]")
        self.assertTrue(any("tags must include 'rust-a'" in e for e in self.lint()))

    def test_an_absolute_grader_path_fails(self):
        self.edit_yaml("    pattern: 'x'\n", "    target: {source: file, path: /etc/passwd}\n    pattern: 'x'\n")
        self.assertTrue(any("must be relative" in e for e in self.lint()))


class Parse(unittest.TestCase):
    def test_grader_paths_come_from_the_case_and_the_graders(self):
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "graders").mkdir()
        (root / "case.yaml").write_text("  - target: {source: file, path: Cargo.toml}\n")
        (root / "graders" / "a.md").write_text("---\nfocus: {source: file, path: src/lib.rs}\n---\n")
        self.assertEqual(check.grader_paths(root), ["Cargo.toml", "src/lib.rs"])

    def test_folded_block_stops_at_the_next_key(self):
        text = "execution:\n  prompt: >-\n    one\n    two\nexpected_outcome: x\n"
        self.assertEqual(check.folded_block(text, "prompt"), "one two")


if __name__ == "__main__":
    unittest.main()
