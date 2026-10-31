#!/usr/bin/env python3
"""Tests for the routing runner's lint and scorer. No network, no key, no SDK.

Run:
    python3 evals/routing/test_run.py
"""
import importlib.util
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parent / "run.py"
SPEC = importlib.util.spec_from_file_location("routing_run", SOURCE)
assert SPEC and SPEC.loader
run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run)

DESCRIPTIONS = {"rust-a": "Use when a borrow fails to compile.", "rust-b": "Use when a macro expands."}


def row(id_, skill, kind, expected, alternates=(), prompt="a plain question"):
    return {
        "id": id_, "skill": skill, "kind": kind, "prompt": prompt, "expected": expected,
        "accepted_alternates": list(alternates), "source": "x",
    }


def full_set():
    rows = []
    for skill, other in (("rust-a", "rust-b"), ("rust-b", "rust-a")):
        rows += [row(f"{skill}-p{i}", skill, "positive", skill) for i in (1, 2, 3)]
        rows.append(row(f"{skill}-n1", skill, "near-miss", other))
    return rows


class Lint(unittest.TestCase):
    def test_a_complete_blind_set_passes(self):
        self.assertEqual(run.lint(full_set(), DESCRIPTIONS), ([], []))

    def test_a_prompt_that_names_a_skill_fails(self):
        rows = full_set()
        rows[0]["prompt"] = "should rust-b handle this"
        problems, _ = run.lint(rows, DESCRIPTIONS)
        self.assertTrue(any("names the skill 'rust-b'" in p for p in problems))

    def test_description_wording_is_a_warning(self):
        rows = full_set()
        rows[0]["prompt"] = "it says a borrow fails to compile here"
        problems, warnings = run.lint(rows, DESCRIPTIONS)
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)

    def test_uneven_coverage_fails(self):
        problems, _ = run.lint(full_set()[1:], DESCRIPTIONS)
        self.assertTrue(any("needs 3 positives" in p for p in problems))

    def test_a_near_miss_that_expects_its_own_skill_fails(self):
        rows = full_set()
        rows[3]["expected"] = "rust-a"
        problems, _ = run.lint(rows, DESCRIPTIONS)
        self.assertTrue(any("near-miss expects" in p for p in problems))


class Score(unittest.TestCase):
    def test_top1_and_top2_per_set(self):
        rows = [
            row("p1", "rust-a", "positive", "rust-a"),
            row("p2", "rust-a", "positive", "rust-a"),
            row("n1", "rust-a", "near-miss", "none"),
            row("n2", "rust-b", "near-miss", "rust-a", alternates=["rust-b"]),
        ]
        answers = [{
            "p1": {"first": "rust-a", "second": "none"},
            "p2": {"first": "rust-b", "second": "rust-a"},
            "n1": {"first": "rust-a", "second": "none"},
            "n2": {"first": "rust-b", "second": "rust-a"},
        }]
        result = run.score(rows, answers)
        self.assertEqual((result["positive"]["top1"], result["positive"]["top2"]), (0.5, 1.0))
        self.assertEqual((result["near-miss"]["top1"], result["near-miss"]["top2"]), (0.5, 1.0))

    def test_a_missing_answer_counts_as_wrong(self):
        rows = [row("p1", "rust-a", "positive", "rust-a")]
        self.assertEqual(run.score(rows, [{}])["positive"]["top1"], 0.0)

    def test_scores_average_over_runs(self):
        rows = [row("p1", "rust-a", "positive", "rust-a")]
        answers = [{"p1": {"first": "rust-a", "second": "none"}}, {"p1": {"first": "none", "second": "none"}}]
        self.assertEqual(run.score(rows, answers)["positive"]["top1"], 0.5)


class Schema(unittest.TestCase):
    def test_choices_are_closed_over_the_catalog_and_none(self):
        schema = run.answer_schema(["rust-a"])
        item = schema["properties"]["answers"]["items"]
        self.assertEqual(item["properties"]["first"]["enum"], ["rust-a", "none"])
        self.assertFalse(item["additionalProperties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
