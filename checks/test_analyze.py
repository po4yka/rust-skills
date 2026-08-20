#!/usr/bin/env python3
"""Regression tests for the classifier in analyze.py.

The classifier decides which compile failures the catalog is allowed to ignore.
Every entry in `RESOLUTION_CODES` and `ARTIFACT_CODES` silences a real compiler
error, so a wrong entry turns a broken example into a passing one. These tests
pin the boundary: a code that means "the block does not define this name" is
excused, everything else is a suspect.

Run:
    python3 checks/test_analyze.py
"""
import unittest

import analyze


def error(code: str | None, message: str = "", **extra) -> dict:
    return {
        "code": {"code": code} if code else None,
        "message": message,
        "level": "error",
        **extra,
    }


def entry(mode: str, **extra) -> dict:
    return {"file": "skill/SKILL.md", "line": 1, "section": "S", "mode": mode, **extra}


class TestExcuses(unittest.TestCase):
    """A code is excused only when it means the prose defines the name."""

    def test_undefined_name_is_a_fragment(self):
        for code, message in [
            ("E0425", "cannot find value `handle` in this scope"),
            ("E0412", "cannot find type `Session` in this scope"),
            ("E0433", "failed to resolve: use of undeclared crate or module `db`"),
            ("E0432", "unresolved import `crate::db`"),
        ]:
            with self.subTest(code=code):
                fragment, _, _, suspects = analyze.classify({"ex": [error(code, message)]})
                self.assertEqual((fragment, suspects), (1, {}))

    def test_uncoded_resolution_message_is_a_fragment(self):
        # A missing macro carries no error code, only the message.
        fragment, _, _, suspects = analyze.classify(
            {"ex": [error(None, "cannot find macro `criterion_main` in this scope")]}
        )
        self.assertEqual((fragment, suspects), (1, {}))

    def test_missing_required_external_crate_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {
                "ex": [
                    error(
                        "E0432",
                        "unresolved import `criterion`",
                    )
                ]
            }
        )
        self.assertIn("ex", suspects)

    def test_required_external_crates_are_declared(self):
        self.assertLessEqual(analyze.REQUIRED_EXTERNAL_CRATES, analyze.HARNESS_CRATES)

    def test_libfuzzer_runtime_is_not_built_for_type_checking(self):
        dependency = analyze.HARNESS_DEPENDENCIES["libfuzzer-sys"]
        self.assertIsInstance(dependency, dict)
        self.assertFalse(dependency.get("default-features", True))

    def test_disabled_feature_on_harness_crate_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E0432", "unresolved import `nix::sys::socket`")]}
        )
        self.assertIn("ex", suspects)

    def test_unstable_feature_is_a_suspect(self):
        # E0658 means the example uses nightly-only Rust on a stable pin. That
        # is a defect in the example, not a name the prose defines.
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E0658", "use of unstable library feature `portable_simd`")]}
        )
        self.assertIn("ex", suspects)

    def test_bad_function_pointer_type_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E0561", "patterns aren't allowed in function pointer types")]}
        )
        self.assertIn("ex", suspects)

    def test_non_type_used_as_type_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E0573", "expected type, found variant `Status::Ready`")]}
        )
        self.assertIn("ex", suspects)

    def test_unknown_code_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E9999", "a code this file has never seen")]}
        )
        self.assertIn("ex", suspects)

    def test_type_mismatch_is_a_suspect(self):
        _, _, _, suspects = analyze.classify({"ex": [error("E0308", "mismatched types")]})
        self.assertIn("ex", suspects)

    def test_one_real_error_beside_undefined_names_is_a_suspect(self):
        _, _, _, suspects = analyze.classify(
            {"ex": [error("E0425", "cannot find value `x`"), error("E0308", "mismatched types")]}
        )
        self.assertIn("ex", suspects)

    def test_wrapper_damage_is_not_a_suspect(self):
        _, artifact, _, suspects = analyze.classify(
            {"ex": [error("E0424", "expected value, found module `self`")]}
        )
        self.assertEqual((artifact, suspects), (1, {}))

    def test_missing_type_annotation_is_low_signal(self):
        _, _, low, suspects = analyze.classify(
            {"ex": [error("E0282", "type annotations needed")]}
        )
        self.assertEqual((low, suspects), (1, {}))


class TestCoverage(unittest.TestCase):
    """Every example cargo was asked to build has to appear in its output."""

    def test_example_that_never_reached_the_compiler_is_reported(self):
        manifest = {"a": entry("compile"), "b": entry("compile")}
        self.assertEqual(analyze.unbuilt(manifest, {"a"}), ["b"])

    def test_ignored_block_is_not_expected_to_build(self):
        manifest = {"a": entry("ignore")}
        self.assertEqual(analyze.unbuilt(manifest, set()), [])

    def test_compile_fail_example_must_reach_the_compiler(self):
        manifest = {"x": entry("compile_fail")}
        self.assertEqual(analyze.unbuilt(manifest, set()), ["x"])

    def test_run_example_must_reach_the_compiler(self):
        manifest = {"x": entry("run")}
        self.assertEqual(analyze.unbuilt(manifest, set()), ["x"])


class TestRun(unittest.TestCase):
    """A behavior probe cannot use the fragment excuse list."""

    def test_clean_run_block_passes(self):
        self.assertEqual(analyze.run_failures({"x": entry("run")}, {}), [])

    def test_any_run_compile_error_fails(self):
        manifest = {"x": entry("run")}
        errors = {"x": [error("E0425", "cannot find value `x`")]}
        problems = analyze.run_failures(manifest, errors)
        self.assertEqual(len(problems), 1)
        self.assertIn("E0425", problems[0])


class TestCompileFail(unittest.TestCase):
    """A compile_fail block that compiles is a claim the language dropped."""

    def test_block_that_compiles_is_reported(self):
        problems = analyze.compile_fail_failures({"x": entry("compile_fail")}, {})
        self.assertEqual(len(problems), 1)
        self.assertIn("it compiles", problems[0])

    def test_block_that_fails_passes(self):
        manifest = {"x": entry("compile_fail")}
        errors = {"x": [error("E0499", "cannot borrow `v` as mutable more than once")]}
        self.assertEqual(analyze.compile_fail_failures(manifest, errors), [])

    def test_expected_code_must_occur(self):
        manifest = {"x": entry("compile_fail", codes=["E0499"])}
        errors = {"x": [error("E0425", "cannot find value `v`")]}
        problems = analyze.compile_fail_failures(manifest, errors)
        self.assertEqual(len(problems), 1)
        self.assertIn("E0499", problems[0])

    def test_expected_code_that_occurs_passes(self):
        manifest = {"x": entry("compile_fail", codes=["E0499"])}
        errors = {"x": [error("E0425", "cannot find value `v`"), error("E0499", "borrow")]}
        self.assertEqual(analyze.compile_fail_failures(manifest, errors), [])

    def test_failure_on_an_undefined_name_alone_is_flagged_as_weak(self):
        manifest = {"x": entry("compile_fail")}
        errors = {"x": [error("E0425", "cannot find value `v`")]}
        self.assertEqual(len(analyze.weak_compile_fail(manifest, errors)), 1)

    def test_a_fence_that_names_its_code_is_not_weak(self):
        manifest = {"x": entry("compile_fail", codes=["E0499"])}
        errors = {"x": [error("E0425", "cannot find value `v`")]}
        self.assertEqual(analyze.weak_compile_fail(manifest, errors), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
