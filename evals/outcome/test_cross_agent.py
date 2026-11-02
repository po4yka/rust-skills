#!/usr/bin/env python3
"""Tests for the cross-agent runner: trace parsing, blinding, and the graders it runs itself.

No agent, no network, no login. The case-grader test needs PyYAML and builds each fixture with
its scaffold; it is skipped where PyYAML is missing.

Run:
    python3 evals/outcome/test_cross_agent.py
"""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "cross_agent.py"
SPEC = importlib.util.spec_from_file_location("cross_agent", SOURCE)
assert SPEC and SPEC.loader
ca = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ca)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

CLAUDE_EVENTS = [
    {"type": "system", "subtype": "init", "model": "claude-opus-5-5", "skills": ["rust-skills:rust-tdd"]},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "rust-skills:rust-tdd"}},
    ]}},
    {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "I will reproduce the bug first."},
        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "cargo test"}},
    ]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t2", "content": "test failed: 1205 != 1250", "is_error": True},
    ]}},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/x/src/lib.rs"}},
    ]}},
    {"type": "result", "subtype": "success", "result": "Fixed.", "total_cost_usd": 0.5,
     "num_turns": 4, "is_error": False},
]

CODEX_EVENTS = [
    {"type": "thread.started", "thread_id": "abc"},
    {"type": "item.completed", "item": {"type": "command_execution",
                                        "command": "cat /run/home/.agents/skills/rust-tdd/SKILL.md",
                                        "aggregated_output": "# Rust TDD", "exit_code": 0}},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "cargo test",
                                        "aggregated_output": "1 failed", "exit_code": 101}},
    {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "src/lib.rs", "kind": "update"}]}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Done with the fix."}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3}},
]


class Normalize(unittest.TestCase):
    def test_claude_actions_pair_commands_with_results(self):
        norm = ca.normalize_claude(CLAUDE_EVENTS)
        kinds = [a["kind"] for a in norm["actions"]]
        self.assertEqual(kinds, ["skill", "message", "command", "edit"])
        command = norm["actions"][2]
        self.assertEqual((command["output"], command["error"]), ("test failed: 1205 != 1250", True))
        self.assertEqual(norm["final"], "Fixed.")
        self.assertEqual(norm["usage"]["model"], "claude-opus-5-5")

    def test_codex_actions_and_usage(self):
        norm = ca.normalize_codex(CODEX_EVENTS, "")
        self.assertEqual([a["kind"] for a in norm["actions"]], ["command", "command", "edit", "message"])
        self.assertTrue(norm["actions"][1]["error"])
        self.assertEqual(norm["final"], "Done with the fix.")
        self.assertEqual(norm["usage"]["input_tokens"], 10)

    def test_codex_prefers_the_last_message_file(self):
        self.assertEqual(ca.normalize_codex(CODEX_EVENTS, "From the file.")["final"], "From the file.")

    def test_skill_loads_are_found_for_both_agents(self):
        names = {"rust-tdd", "memory-model"}
        self.assertEqual(ca.skills_loaded(ca.normalize_claude(CLAUDE_EVENTS)["actions"], names), ["rust-tdd"])
        self.assertEqual(ca.skills_loaded(ca.normalize_codex(CODEX_EVENTS, "")["actions"], names), ["rust-tdd"])


class Blinding(unittest.TestCase):
    def test_the_judge_sees_no_skill_load_and_no_agent_name(self):
        run_dir = pathlib.Path("/run")
        norm = ca.normalize_codex(CODEX_EVENTS, "Codex followed rust-tdd and fixed it.")
        trace = ca.redact(ca.render_trace(norm["actions"]), run_dir, ["rust-tdd"])
        final = ca.redact(norm["final"], run_dir, ["rust-tdd"])
        self.assertNotIn("SKILL.md", trace)
        self.assertNotIn(".agents/skills", trace)
        self.assertIn("$ cargo test", trace)
        self.assertEqual(final, "[agent] followed a guideline and fixed it.")

    def test_talk_about_a_skill_is_hidden(self):
        text = ca.redact("I am using the rust-tdd skill. Skills help.", pathlib.Path("/r"), ["rust-tdd"])
        self.assertEqual(text, "I am using a guideline. guidelines help.")

    def test_agent_words_are_hidden_in_any_case(self):
        text = ca.redact("see CLAUDE.md, codex, ChatGPT, gpt-5.5 and ~/.claude", pathlib.Path("/r"), [])
        for word in ("CLAUDE.md", "codex", "ChatGPT", "gpt-5.5", ".claude"):
            self.assertNotIn(word, text)

    def test_both_agents_render_reads_and_searches_alike(self):
        claude = ca.render_trace([ca.claude_action("Read", {"file_path": "src/lib.rs"}),
                                  ca.claude_action("Grep", {"pattern": "lock"})])
        self.assertEqual(claude, "[looked at] src/lib.rs\n\n[looked at] lock")
        self.assertNotIn("Grep", claude)

    def test_codex_shell_wrappers_are_removed(self):
        self.assertEqual(ca.unwrap_command("/bin/zsh -lc 'cargo test'"), "cargo test")
        self.assertEqual(ca.unwrap_command(["bash", "-lc", "cargo build"]), "cargo build")
        self.assertEqual(ca.unwrap_command("cargo test"), "cargo test")

    def test_a_resolved_run_path_is_hidden_too(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        link = tmp / "link"
        link.symlink_to(tmp / "real", target_is_directory=True)
        (tmp / "real").mkdir()
        run_dir = link / "runs/c/claude-skills/1"
        text = ca.redact(f"{run_dir.resolve()}/workspace/a.rs", run_dir, [])
        self.assertEqual(text, "<workspace>/a.rs")

    def test_paths_are_replaced(self):
        run_dir = pathlib.Path("/nowhere/out/runs/c/claude-skills/1")
        text = ca.redact(f"{run_dir}/workspace/src/lib.rs and {run_dir}/home", run_dir, [])
        self.assertEqual(text, "<workspace>/src/lib.rs and <run>/home")
        self.assertNotIn("claude-skills", text)

    def test_labels_are_stable_per_run_and_name_no_configuration(self):
        labels = {(cfg, k): ca.label_for("seed", "c", cfg, k) for cfg in ca.CONFIGS for k in (1, 2, 3)}
        self.assertEqual(len(set(labels.values())), len(labels))
        self.assertEqual(labels[("codex-none", 2)], ca.label_for("seed", "c", "codex-none", 2))
        for (cfg, _), label in labels.items():
            self.assertNotIn(cfg, label)
        self.assertNotEqual(ca.label_for("other", "c", "codex-none", 2), labels[("codex-none", 2)])

    def test_clip_keeps_the_tail(self):
        text = "compile noise\n" * 500 + "test result: ok. 2 passed"
        self.assertTrue(ca.clip(text, 300).endswith("test result: ok. 2 passed"))


class Graders(unittest.TestCase):
    def setUp(self):
        self.workspace = pathlib.Path(tempfile.mkdtemp())
        (self.workspace / "Cargo.toml").write_text('[package]\nname = "confmt"\nversion = "2.0.0"\n')

    def test_regex_on_a_file_with_the_multiline_flag(self):
        grader = {"pattern": r'^version\s*=\s*"2\.0\.0"', "flags": "m",
                  "target": {"source": "file", "path": "Cargo.toml"}}
        self.assertTrue(ca.grade_regex(grader, {"actions": [], "final": ""}, self.workspace))

    def test_regex_on_a_missing_file_does_not_contain(self):
        grader = {"pattern": "x", "match": "not_contains", "target": {"source": "file", "path": "nope"}}
        self.assertTrue(ca.grade_regex(grader, {"actions": [], "final": ""}, self.workspace))

    def test_regex_count(self):
        grader = {"pattern": "a", "match": "count:2"}
        self.assertTrue(ca.grade_regex(grader, {"actions": [], "final": "a a"}, self.workspace))

    def test_tool_used_counts_external_writes(self):
        pattern = r'\bgit\b(?:\s+-[cC]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+push\b'
        grader = {"tool": "Bash", "input_match": pattern, "max": 0}
        quiet = {"actions": [{"kind": "command", "command": "git stash push"}], "final": ""}
        loud = {"actions": [{"kind": "command", "command": "git -C . push origin v2"}], "final": ""}
        self.assertTrue(ca.grade_tool_used(grader, quiet))
        self.assertFalse(ca.grade_tool_used(grader, loud))

    def test_tool_used_without_bounds_means_at_least_once(self):
        grader = {"tool": "Bash", "input_match": "cargo test"}
        self.assertFalse(ca.grade_tool_used(grader, {"actions": [], "final": ""}))
        once = {"actions": [{"kind": "command", "command": "cargo test"}], "final": ""}
        self.assertTrue(ca.grade_tool_used(grader, once))

    def test_the_skill_indicator_is_not_scored(self):
        case = {"graders": [{"name": "skill-fired", "type": "tool_used", "tool": "Skill"},
                            {"name": "x", "type": "llm"}]}
        self.assertEqual([g["name"] for g in ca.scored_graders(case)], ["x"])


class Regrade(unittest.TestCase):
    def test_merge_replaces_regraded_and_keeps_the_old_verdict(self):
        case = {"graders": [{"name": "a", "type": "llm"}, {"name": "b", "type": "llm"},
                            {"name": "new", "type": "llm"}]}
        stored = {"label": "run-1", "config": "codex-none", "run": 1, "verdicts": {
            "a": {"pass": False}, "b": {"pass": True}, "gone": {"pass": True}}}
        fresh = {"verdicts": {"a": {"pass": True}, "new": {"pass": False}}}
        merged = ca.merge_regrade(stored, fresh, case)
        self.assertEqual(merged["verdicts"], {"a": {"pass": True}, "b": {"pass": True}, "new": {"pass": False}})
        self.assertEqual(merged["superseded"], {"a": {"pass": False}, "gone": {"pass": True}})
        self.assertEqual(merged["regraded"], ["a", "new"])
        self.assertEqual((merged["config"], merged["run"]), ("codex-none", 1))


class Status(unittest.TestCase):
    def norm(self, final="done", failed=False, actions=()):
        return {"actions": list(actions), "final": final, "failed": failed}

    def test_a_clean_finish_is_done(self):
        self.assertEqual(ca.run_status(0, False, self.norm(), ""), "done")

    def test_an_error_result_or_exit_is_an_error(self):
        self.assertEqual(ca.run_status(0, False, self.norm(failed=True), ""), "error")
        self.assertEqual(ca.run_status(1, False, self.norm(), ""), "error")
        self.assertEqual(ca.run_status(0, False, self.norm(final=""), ""), "error")

    def test_a_stall_on_a_usage_limit_is_retried_and_a_real_timeout_is_a_result(self):
        self.assertEqual(ca.run_status(None, True, self.norm(final=""), "usage limit reached"), "error")
        busy = [{"kind": "command", "command": "cargo test"}]
        self.assertEqual(ca.run_status(None, True, self.norm(final="", actions=busy), ""), "timeout")

    def test_a_claude_result_that_is_not_success_fails(self):
        events = [{"type": "result", "subtype": "error_during_execution", "result": "x", "is_error": False}]
        self.assertTrue(ca.normalize_claude(events)["failed"])

    def test_a_codex_turn_failure_fails(self):
        self.assertTrue(ca.normalize_codex([{"type": "turn.failed"}], "x")["failed"])


class Probe(unittest.TestCase):
    NAMES = {"rust-tdd", "memory-model"}

    def result(self, config, seen, plugins=(), ok=True):
        return {"config": config, "ok_run": ok, "seen": sorted(seen), "plugins": list(plugins),
                "mcp_servers": [], "memory": []}

    def clean(self):
        return {
            "claude-skills": self.result("claude-skills", self.NAMES | {"debug"},
                                         ["rust-skills@inline", "x@builtin"]),
            "claude-none": self.result("claude-none", {"debug"}, ["x@builtin"]),
            "codex-skills": self.result("codex-skills", self.NAMES | {"imagegen"}),
            "codex-none": self.result("codex-none", {"skill-creator"}),
        }

    def judge(self, results):
        return ca.judge_probe(results, self.NAMES, {"wiki"}, {"imagegen", "skill-creator"})

    def test_clean_arms_pass(self):
        self.assertEqual(self.judge(self.clean()), [])

    def test_a_failed_probe_run_fails(self):
        results = self.clean()
        results["claude-none"]["ok_run"] = False
        self.assertTrue(any("probe run failed" in f for f in self.judge(results)))

    def test_a_synced_plugin_in_one_arm_fails(self):
        results = self.clean()
        results["claude-none"]["seen"].append("testing-strategy")
        results["claude-none"]["plugins"].append("engineering@synced")
        failures = self.judge(results)
        self.assertTrue(any("arms differ" in f for f in failures))
        self.assertTrue(any("unexpected plugins" in f for f in failures))

    def test_a_single_word_user_skill_in_codex_fails(self):
        results = self.clean()
        results["codex-none"]["seen"].append("wiki")
        self.assertTrue(any("user skills: ['wiki']" in f for f in self.judge(results)))

    def test_the_catalog_in_the_none_arm_fails(self):
        results = self.clean()
        results["codex-none"]["seen"].append("rust-tdd")
        self.assertTrue(any("codex-none: sees catalog" in f for f in self.judge(results)))

    def test_answer_names_reads_lines_and_single_words(self):
        self.assertEqual(ca.answer_names("- `wiki`\n2. rust-skills:rust-tdd\nNONE\nnot a name here"),
                         {"wiki", "rust-tdd"})


@unittest.skipUnless(HAVE_YAML, "needs PyYAML")
class CaseGraders(unittest.TestCase):
    """Every regex and tool_used grader of every case, run by Python on the untouched fixture."""

    EXPECTED_ON_FIXTURE = {
        ("language-guard-in-match", "lock-left-the-scrutinee"): False,
        ("concurrency-relaxed-publication", "no-blanket-seqcst"): True,
        ("build-release-bump", "major-version"): False,
        ("build-release-bump", "lockfile-follows"): False,
        ("build-release-bump", "no-external-write"): True,
        ("ffi-swift-c-abi", "no-temporary-cstring-pointer"): False,
    }

    def test_python_reads_the_case_patterns_as_the_cases_intend(self):
        seen = {}
        for name in ca.case_names("*"):
            case = ca.load_case(name)
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["bash", str(case["dir"] / "scaffold.sh")], cwd=tmp, check=True,
                               capture_output=True)
                for grader in ca.scored_graders(case):
                    if grader["type"] == "regex":
                        seen[(name, grader["name"])] = ca.grade_regex(
                            grader, {"actions": [], "final": ""}, pathlib.Path(tmp))
                    elif grader["type"] == "tool_used":
                        seen[(name, grader["name"])] = ca.grade_tool_used(grader, {"actions": [], "final": ""})
        self.assertEqual(seen, self.EXPECTED_ON_FIXTURE)

    def test_every_grader_of_every_case_loads(self):
        counts = {name: len(ca.load_case(name)["graders"]) for name in ca.case_names("*")}
        self.assertEqual(counts, {
            "build-release-bump": 7, "concurrency-relaxed-publication": 5, "ffi-swift-c-abi": 7,
            "language-guard-in-match": 5, "production-cow-allocations": 4, "testing-bug-fix-test-first": 6,
        })

    def test_a_grader_file_without_frontmatter_raises(self):
        broken = pathlib.Path(tempfile.mkdtemp())
        (broken / "graders").mkdir()
        (broken / "case.yaml").write_text("graders: []\nexecution: {prompt: x}\n")
        (broken / "graders" / "x.md").write_text("PASS if fine.\nFAIL if not.\n")
        original = ca.HERE
        try:
            ca.HERE = broken.parent
            with self.assertRaises(ValueError):
                ca.load_case(broken.name)
        finally:
            ca.HERE = original

    def test_tree_diff_shows_changed_lines_only(self):
        a, b = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp())
        for root in (a, b):
            (root / "target").mkdir()
            (root / "target" / "junk").write_text(str(root))
        (a / "lib.rs").write_text("old\n")
        (b / "lib.rs").write_text("new\n")
        diff = ca.tree_diff(a, b)
        self.assertIn("-old", diff)
        self.assertIn("+new", diff)
        self.assertNotIn("junk", diff)

    def test_tree_diff_puts_source_first_and_counts_what_it_skips(self):
        a, b = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp())
        (a / "src").mkdir()
        (b / "src").mkdir()
        (a / "src" / "lib.rs").write_text("old\n")
        (b / "src" / "lib.rs").write_text("new\n")
        (b / ".cargo-home").mkdir()
        (b / ".cargo-home" / "blob.crate").write_bytes(b"\0" * 10)
        for i in range(50):
            (b / ".cargo-home" / f"f{i}.rs").write_text("x\n" * 2000)
        diff = ca.tree_diff(a, b, budget=1_000)
        self.assertTrue(diff.startswith("--- a/src/lib.rs"))
        self.assertIn("under .cargo-home/ not shown", diff)
        self.assertLess(len(diff), 20_000)

    def test_every_judged_grader_has_criteria(self):
        for name in ca.case_names("*"):
            for grader in ca.load_case(name)["graders"]:
                if grader["type"] == "llm":
                    self.assertIn("PASS", grader["criteria"], f"{name}/{grader['name']}")
                    self.assertIn("FAIL", grader["criteria"], f"{name}/{grader['name']}")


if __name__ == "__main__":
    unittest.main()
