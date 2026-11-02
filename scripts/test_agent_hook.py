#!/usr/bin/env python3
"""Tests for scripts/agent-hook.py, the PostToolUse hook of Claude Code and Codex.

The hook must report a validator failure to the model after a catalog edit,
stay silent after any other edit, and never block an edit because of its own
failure.

Run:
    python3 scripts/test_agent_hook.py
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parent / "agent-hook.py"
SPEC = importlib.util.spec_from_file_location("agent_hook", SOURCE)
assert SPEC and SPEC.loader, f"cannot load {SOURCE}"
agent_hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_hook)
ROOT = agent_hook.ROOT

# The shape of a Codex apply_patch call.
PATCH = """*** Begin Patch
*** Update File: skills/rust-tdd/SKILL.md
@@
-old
+new
*** Add File: skills/rust-tdd/references/new.md
+text
*** Update File: checks/check.sh
*** Move to: README.md
*** Delete File: tests/routing-cases.md
*** End Patch"""


class TestEditedPaths(unittest.TestCase):
    def test_a_claude_code_edit_gives_its_file_path(self):
        event = {"tool_name": "Edit", "tool_input": {"file_path": "/x/skills/a/SKILL.md", "old_string": "a"}}
        self.assertEqual(agent_hook.edited_paths(event), ["/x/skills/a/SKILL.md"])

    def test_a_codex_patch_gives_every_file_it_touches(self):
        event = {"tool_name": "apply_patch", "tool_input": {"command": PATCH}}
        self.assertEqual(
            agent_hook.edited_paths(event),
            [
                "skills/rust-tdd/SKILL.md",
                "skills/rust-tdd/references/new.md",
                "checks/check.sh",
                "README.md",
                "tests/routing-cases.md",
            ],
        )

    def test_an_event_without_tool_input_gives_nothing(self):
        self.assertEqual(agent_hook.edited_paths({"tool_input": "text"}), [])


class TestCatalogPaths(unittest.TestCase):
    def test_only_files_the_validator_reads_count(self):
        paths = ["skills/rust-tdd/SKILL.md", "checks/check.sh", "README.md", "research/notes.md"]
        self.assertEqual(agent_hook.catalog_paths(paths, ROOT), ["skills/rust-tdd/SKILL.md", "README.md"])

    def test_an_absolute_path_inside_the_checkout_counts(self):
        path = str(ROOT / ".claude-plugin" / "marketplace.json")
        self.assertEqual(agent_hook.catalog_paths([path], pathlib.Path("/")), [".claude-plugin/marketplace.json"])

    def test_a_path_in_another_checkout_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(agent_hook.catalog_paths(["skills/a/SKILL.md"], pathlib.Path(tmp)), [])


class TestFailures(unittest.TestCase):
    def test_the_problem_lines_after_fail_are_read(self):
        stdout = "descriptions: 1\n  warning: x\nFAIL: 2 problem(s) in 44 skill(s)\n\n  a: one\n  b: two\n"
        self.assertEqual(agent_hook.failures(stdout), ["a: one", "b: two"])

    def test_a_passing_run_has_no_problems(self):
        self.assertEqual(agent_hook.failures("OK: 44 skills valid\n"), [])


class TestMain(unittest.TestCase):
    def run_hook(self, event: object, validator_stdout: str | None = None, code: int = 1) -> tuple[int, str]:
        stdin = io.StringIO(event if isinstance(event, str) else json.dumps(event))
        stderr = io.StringIO()
        patches = [mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stderr(stderr)]
        if validator_stdout is not None:
            result = subprocess.CompletedProcess([], code, validator_stdout, "")
            patches.append(mock.patch.object(agent_hook.subprocess, "run", return_value=result))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return agent_hook.main(), stderr.getvalue()

    def edit(self, path: str) -> dict:
        return {"cwd": str(ROOT), "tool_name": "Edit", "tool_input": {"file_path": path}}

    def test_a_failing_catalog_edit_reports_to_the_model_with_exit_2(self):
        stdout = "FAIL: 1 problem(s) in 44 skill(s)\n\n  skills/rust-tdd/SKILL.md: description is too long\n"
        code, stderr = self.run_hook(self.edit("skills/rust-tdd/SKILL.md"), stdout)
        self.assertEqual(code, 2)
        self.assertIn("description is too long", stderr)
        self.assertIn("skills/rust-tdd/SKILL.md", stderr)

    def test_a_long_report_is_cut(self):
        stdout = "FAIL: 50 problem(s)\n" + "".join(f"  p{i}\n" for i in range(50))
        code, stderr = self.run_hook(self.edit("README.md"), stdout)
        self.assertEqual(code, 2)
        self.assertIn("and 10 more", stderr)

    def test_an_edit_outside_the_catalog_does_not_run_the_validator(self):
        with mock.patch.object(agent_hook.subprocess, "run") as run:
            code, stderr = self.run_hook(self.edit("checks/check.sh"))
        self.assertEqual((code, stderr), (0, ""))
        run.assert_not_called()

    def test_a_validator_crash_does_not_block_the_edit(self):
        code, stderr = self.run_hook(self.edit("README.md"), "Traceback (most recent call last):\n", code=1)
        self.assertEqual((code, stderr), (0, ""))

    def test_a_malformed_event_does_not_block_the_edit(self):
        self.assertEqual(self.run_hook("not json"), (0, ""))
        self.assertEqual(self.run_hook([1, 2]), (0, ""))

    def test_an_event_that_breaks_path_handling_does_not_block_the_edit(self):
        self.assertEqual(self.run_hook({"cwd": "/x", "tool_input": {"file_path": "a\u0000b"}}), (0, ""))

    def test_a_real_validator_failure_reaches_the_model(self):
        # End to end on a copy: the real validator, its real FAIL format, and exit 2.
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "target", "examples", "worktrees"))
            skill = copy / "skills" / "rust-tdd" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8").replace("red-green-refactor", "red-green", 1), encoding="utf-8")
            event = {"cwd": str(copy), "tool_name": "Edit", "tool_input": {"file_path": str(skill)}}
            result = subprocess.run(
                [sys.executable, str(copy / "scripts" / "agent-hook.py")],
                input=json.dumps(event),
                capture_output=True,
                text=True,
                timeout=120,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("routing phrase 'red-green-refactor'", result.stderr)

    def test_the_shipped_catalog_passes_through_the_real_validator(self):
        self.assertTrue(agent_hook.VALIDATOR.is_file())
        # End to end, as a client runs it: a catalog edit on a green checkout is silent.
        result = subprocess.run(
            [sys.executable, str(SOURCE)],
            input=json.dumps(self.edit("skills/rust-tdd/SKILL.md")),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))


class TestClientConfig(unittest.TestCase):
    """Both client configs run this hook after a file edit."""

    def test_claude_code_runs_the_hook_after_edits(self):
        config = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        group = config["hooks"]["PostToolUse"][0]
        self.assertEqual(set(group["matcher"].split("|")), {"Edit", "Write", "MultiEdit"})
        self.assertIn("scripts/agent-hook.py", group["hooks"][0]["command"])

    def test_codex_runs_the_hook_after_patches(self):
        config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        group = config["hooks"]["PostToolUse"][0]
        self.assertIn("apply_patch", group["matcher"].split("|"))
        self.assertIn("scripts/agent-hook.py", group["hooks"][0]["command"])

    def command(self, config: str) -> str:
        return json.loads((ROOT / config).read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"][0]["command"]

    def shell(self, command: str, cwd: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        import os

        edit = json.dumps({"cwd": str(cwd), "tool_input": {"file_path": str(ROOT / "README.md")}})
        return subprocess.run(
            ["sh", "-c", command], cwd=cwd, input=edit, capture_output=True, text=True, timeout=120,
            env={**os.environ, **env},
        )

    def test_a_missing_hook_script_stays_silent(self):
        # python3 on a missing file exits 2, which both clients would show to the model.
        with tempfile.TemporaryDirectory() as tmp:
            claude = self.shell(self.command(".claude/settings.json"), pathlib.Path(tmp), {"CLAUDE_PROJECT_DIR": tmp})
            codex = self.shell(self.command(".codex/hooks.json"), pathlib.Path(tmp), {"GIT_CEILING_DIRECTORIES": tmp})
        self.assertEqual((claude.returncode, claude.stderr), (0, ""))
        self.assertEqual((codex.returncode, codex.stderr), (0, ""))

    def test_both_commands_reach_the_hook_in_this_checkout(self):
        claude = self.shell(self.command(".claude/settings.json"), ROOT, {"CLAUDE_PROJECT_DIR": str(ROOT)})
        codex = self.shell(self.command(".codex/hooks.json"), ROOT, {})
        self.assertEqual((claude.returncode, codex.returncode), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
