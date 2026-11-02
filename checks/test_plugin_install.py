#!/usr/bin/env python3
"""Tests for the parts of plugin_install.py that run without a client CLI.

The install check is only as good as its reading of `claude plugin details` and
`codex debug prompt-input`. A
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


# The shape Codex 0.166.0 prints: a JSON list whose text holds the skill list.
CODEX_PROMPT = json.dumps(
    [
        {
            "type": "message",
            "content": [
                {
                    "text": "## Skills\n### Available skills\n"
                    "- imagegen: Generate or edit raster images. (file: r0/imagegen/SKILL.md)\n"
                    "- rust-skills-testing:rust-tdd: Use when writing Rust code test-first. (file: r1/rust-tdd/SKILL.md)\n"
                    "- rust-skills-testing:rust-test-tools: Use when choosing a runner; see rust-unsafe. "
                    "(file: r1/rust-test-tools/SKILL.md)\n"
                }
            ],
        }
    ]
)


class TestParseCodexSkills(unittest.TestCase):
    def test_the_plugin_skills_are_read(self):
        self.assertEqual(
            plugin_install.parse_codex_skills(CODEX_PROMPT, "rust-skills-testing"), ["rust-tdd", "rust-test-tools"]
        )

    def test_a_skill_named_in_a_description_is_not_counted(self):
        # `rust-unsafe` appears in a description, not as a listed skill.
        self.assertNotIn("rust-unsafe", plugin_install.parse_codex_skills(CODEX_PROMPT, "rust-skills-testing") or [])

    def test_another_plugin_prefix_does_not_match(self):
        # `rust-skills` is a prefix of `rust-skills-testing`; it must match neither line.
        self.assertEqual(plugin_install.parse_codex_skills(CODEX_PROMPT, "rust-skills"), [])

    def test_a_skill_listed_twice_is_counted_twice(self):
        doubled = CODEX_PROMPT.replace(
            "(file: r1/rust-tdd/SKILL.md)\\n", "(file: r1/rust-tdd/SKILL.md)\\n- rust-skills-testing:rust-tdd: again\\n"
        )
        self.assertEqual(
            plugin_install.parse_codex_skills(doubled, "rust-skills-testing"), ["rust-tdd", "rust-tdd", "rust-test-tools"]
        )

    def test_the_codex_environment_drops_caller_keys(self):
        import os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x", "CODEX_SANDBOX": "seatbelt", "PATH": "/p"}):
                env = plugin_install.codex_env(pathlib.Path(tmp))
            self.assertEqual(env["CODEX_HOME"], tmp)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("CODEX_SANDBOX", env)
            self.assertEqual(env["PATH"], "/p")

    def test_the_export_holds_tracked_files_and_no_build_output(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = plugin_install.export_tree(pathlib.Path(tmp))
            self.assertTrue((dest / ".claude-plugin" / "marketplace.json").is_file())
            self.assertTrue((dest / "skills" / "rust-tdd" / "SKILL.md").is_file())
            self.assertFalse((dest / "checks" / "target").exists())
            self.assertFalse((dest / ".git").exists())

    def test_output_without_a_skill_list_is_unreadable(self):
        self.assertIsNone(plugin_install.parse_codex_skills(json.dumps([{"text": "no skills here"}]), "rust-skills"))

    def test_output_that_is_not_json_is_unreadable(self):
        self.assertIsNone(plugin_install.parse_codex_skills("Error: failed to resolve CODEX_HOME", "rust-skills"))


def codex_prompt(*lines: str) -> str:
    return json.dumps([{"content": [{"text": "### Available skills\n" + "\n".join(lines) + "\n"}]}])


class TestCodexVisibility(unittest.TestCase):
    """Routing phrases that Codex cuts off a shortened description."""

    def test_the_shown_description_excludes_the_file_reference(self):
        listing = plugin_install.parse_codex_listing(CODEX_PROMPT, "rust-skills-testing")
        self.assertEqual(listing[0], ("rust-tdd", "Use when writing Rust code test-first."))

    def test_a_file_reference_inside_the_text_survives(self):
        prompt = codex_prompt("- p:s: Use when editing (file: Cargo.toml) or (file: x (file: r1/s/SKILL.md)")
        self.assertEqual(
            plugin_install.parse_codex_listing(prompt, "p"), [("s", "Use when editing (file: Cargo.toml) or (file: x")]
        )

    def test_a_carriage_return_does_not_keep_the_file_reference(self):
        prompt = codex_prompt("- p:s: Use when SKILL is cut (file: r1/s/SKILL.md)\r")
        self.assertEqual(plugin_install.parse_codex_listing(prompt, "p"), [("s", "Use when SKILL is cut")])

    def test_a_phrase_cut_off_the_description_is_hidden(self):
        listing = [("rust-tdd", "Use when writing Rust code test-fi")]
        cases = [("test-first", "rust-tdd"), ("WRITING RUST", "rust-tdd"), ("loom", "rust-unsafe"), ("test-first", "rust-tdd")]
        # Case-insensitive like the validator, one result for a duplicate row, and
        # a skill outside the listing is not measured.
        self.assertEqual(plugin_install.hidden_phrases(listing, cases), [("rust-tdd", "test-first")])

    def test_skills_from_outside_the_plugin_and_codex_are_foreign(self):
        prompt = codex_prompt(
            "- imagegen: Generate images. (file: r0/imagegen/SKILL.md)",
            "- p:s: Ours. (file: r1/s/SKILL.md)",
            "- my-home-skill: From ~/.agents/skills. (file: r2/x/SKILL.md)",
            "- other:t: Another plugin. (file: r3/t/SKILL.md)",
        )
        self.assertEqual(plugin_install.foreign_skills(prompt, "p"), ["my-home-skill", "other:t"])

    def test_the_codex_environment_moves_home_and_keeps_the_npm_cache(self):
        import os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"npm_config_cache": "/c"}):
            env = plugin_install.codex_env(pathlib.Path(tmp))
            self.assertEqual(env["HOME"], str(pathlib.Path(tmp) / "home"))
            self.assertTrue(pathlib.Path(env["HOME"]).is_dir())
            self.assertEqual(env["npm_config_cache"], "/c")

    def test_a_skill_with_an_unusual_name_or_no_description_is_still_foreign(self):
        prompt = codex_prompt("- MySkill: From /etc/codex/skills. (file: r0/x/SKILL.md)", "- bare:", "- p:s: Ours.")
        self.assertEqual(plugin_install.foreign_skills(prompt, "p"), ["MySkill", "bare"])

    def test_the_heading_quoted_in_prose_is_not_the_list(self):
        # Codex 0.166.0 names the heading in its instructions before the real one.
        text = 'Skills are listed under "### Available skills".\n## When to use\n- rule: not a skill\n### Available skills\n- p:s: Ours.\n'
        self.assertEqual(plugin_install.parse_codex_listing(json.dumps([text]), "p"), [("s", "Ours.")])
        self.assertEqual(plugin_install.foreign_skills(json.dumps([text]), "p"), [])

    def test_bullets_after_the_skill_list_are_not_skills(self):
        prompt = json.dumps([{"text": "### Available skills\n- p:s: Ours.\n### How to use skills\n- note: not a skill\n"}])
        self.assertEqual(plugin_install.foreign_skills(prompt, "p"), [])

    def test_routing_cases_are_the_validator_rows(self):
        spec = importlib.util.spec_from_file_location("validate_skills", plugin_install.VALIDATOR)
        assert spec and spec.loader
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        rows, _ = validator.routing_rows(plugin_install.ROUTING.read_text(encoding="utf-8"))
        self.assertEqual(plugin_install.routing_cases(), rows)
        self.assertIn(("cargo nextest", "cargo-workflows"), rows)


# A stand-in for the Codex CLI: it remembers the last `plugin add` target in
# CODEX_HOME and answers `debug prompt-input` with the listing that
# FAKE_LISTINGS (a JSON file: plugin -> list lines) gives for it.
FAKE_CODEX = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
home = pathlib.Path(os.environ["CODEX_HOME"])
if args == ["--version"]:
    print("codex-cli fake")
elif args[:3] == ["plugin", "marketplace", "add"]:
    print(json.dumps({"marketplaceName": "rust-skills"}))
elif args[:2] == ["plugin", "add"]:
    (home / "target").write_text(args[2].split("@")[0])
    print("{}")
elif args[:2] == ["debug", "prompt-input"]:
    lines = json.loads(pathlib.Path(os.environ["FAKE_LISTINGS"]).read_text())[(home / "target").read_text()]
    print(json.dumps([{"text": "### Available skills\n" + "\n".join(lines) + "\n"}]))
else:
    sys.exit(2)
'''


class TestCheckCodexDecisions(unittest.TestCase):
    """What fails a plugin in the Codex gate, driven through a fake CLI."""

    def run_gate(self, listings: dict[str, list[str]]) -> int | None:
        import contextlib
        import io
        import os
        import sys
        import tempfile
        from unittest import mock

        description = next(
            line[len("description: ") :]
            for line in (plugin_install.ROOT / "skills" / "rust-tdd" / "SKILL.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("description: ")
        )
        listings = {p: [line.replace("FULL", description) for line in lines] for p, lines in listings.items()}
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "codex.py"
            fake.write_text(FAKE_CODEX, encoding="utf-8")
            data = pathlib.Path(tmp) / "listings.json"
            data.write_text(json.dumps(listings), encoding="utf-8")
            expected = {plugin: ["rust-tdd"] for plugin in listings}
            with mock.patch.dict(os.environ, {"FAKE_LISTINGS": str(data)}), contextlib.redirect_stdout(io.StringIO()):
                return plugin_install.check_codex([sys.executable, str(fake)], {"name": "rust-skills"}, expected)

    def test_a_bundle_that_shows_every_phrase_passes(self):
        self.assertEqual(self.run_gate({"rust-skills-testing": ["- rust-skills-testing:rust-tdd: FULL"]}), 0)

    def test_a_bundle_with_a_hidden_phrase_fails(self):
        self.assertEqual(self.run_gate({"rust-skills-testing": ["- rust-skills-testing:rust-tdd: Use when"]}), 1)

    def test_the_full_catalog_may_hide_phrases(self):
        self.assertEqual(self.run_gate({"rust-skills": ["- rust-skills:rust-tdd: Use when"]}), 0)

    def test_a_foreign_skill_fails_the_plugin(self):
        listing = ["- rust-skills-testing:rust-tdd: FULL", "- my-home-skill: shares the budget"]
        self.assertEqual(self.run_gate({"rust-skills-testing": listing}), 1)

    def test_a_built_in_skill_does_not_fail_the_plugin(self):
        listing = ["- imagegen: Generate images.", "- rust-skills-testing:rust-tdd: FULL"]
        self.assertEqual(self.run_gate({"rust-skills-testing": listing}), 0)


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
