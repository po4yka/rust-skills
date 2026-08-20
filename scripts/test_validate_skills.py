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
import tempfile
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
            fields = validate_skills.split_frontmatter(text, str(skill))
            assert fields is not None
            for key, value in fields.items():
                if isinstance(value, str):
                    with self.subTest(skill=skill.parent.name, key=key):
                        self.assertIsNone(problem(value))


class TestStructuralValidation(unittest.TestCase):
    def setUp(self):
        validate_skills.failures.clear()

    def test_duplicate_frontmatter_key_fails(self):
        text = """---
name: rust-example
description: Use when you need a complete example description for structural tests.
name: rust-other
license: BSD-3-Clause
---
# Example
"""
        validate_skills.split_frontmatter(text, "SKILL.md")
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("duplicate frontmatter key", validate_skills.failures[0])

    def test_name_with_consecutive_hyphens_fails(self):
        self.assertIsNotNone(validate_skills.NAME_RE.fullmatch("rust-example"))
        self.assertIsNone(validate_skills.NAME_RE.fullmatch("rust--example"))

    def run_skill(self, frontmatter: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            skill = root / "skills" / "rust-example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\n{frontmatter}\n---\n# Example\n", encoding="utf-8"
            )
            original_root = validate_skills.ROOT
            try:
                validate_skills.ROOT = root
                validate_skills.failures.clear()
                validate_skills.descriptions.clear()
                validate_skills.check_skill(skill)
                return list(validate_skills.failures)
            finally:
                validate_skills.ROOT = original_root

    def test_optional_spec_fields_are_supported(self):
        frontmatter = """name: rust-example
description: Use when you need a sufficiently detailed example for optional field validation.
license: BSD-3-Clause
compatibility: Requires Rust and network access
metadata:
  author: example-org
  version: v1.0
allowed-tools: Bash(cargo:*) Read"""
        self.assertEqual(self.run_skill(frontmatter), [])

    def test_metadata_must_be_a_mapping(self):
        frontmatter = """name: rust-example
description: Use when you need a sufficiently detailed example for optional metadata validation.
license: BSD-3-Clause
metadata: author"""
        found = self.run_skill(frontmatter)
        self.assertEqual(len(found), 1)
        self.assertIn("metadata must be a mapping", found[0])

    def test_quoted_metadata_strings_pass(self):
        frontmatter = """name: rust-example
description: Use when you need a sufficiently detailed example for quoted metadata validation.
license: BSD-3-Clause
metadata:
  version: "1.0"
  published: 'true'"""
        self.assertEqual(self.run_skill(frontmatter), [])

    def test_non_string_metadata_scalars_fail(self):
        for value in ("1.0", "42", "true", "false", "null", "~"):
            with self.subTest(value=value):
                frontmatter = f"""name: rust-example
description: Use when you need a sufficiently detailed example for typed metadata validation.
license: BSD-3-Clause
metadata:
  value: {value}"""
                found = self.run_skill(frontmatter)
                self.assertEqual(len(found), 1)
                self.assertIn("metadata.value must be a YAML string", found[0])

    def test_metadata_keys_must_be_yaml_strings(self):
        quoted = """name: rust-example
description: Use when you need a sufficiently detailed example for quoted metadata key validation.
license: BSD-3-Clause
metadata:
  "1": value"""
        self.assertEqual(self.run_skill(quoted), [])

        unquoted = """name: rust-example
description: Use when you need a sufficiently detailed example for typed metadata key validation.
license: BSD-3-Clause
metadata:
  true: value"""
        found = self.run_skill(unquoted)
        self.assertEqual(len(found), 1)
        self.assertIn("metadata key must be a YAML string", found[0])

    def test_compatibility_length_is_limited(self):
        frontmatter = """name: rust-example
description: Use when you need a sufficiently detailed example for optional compatibility validation.
license: BSD-3-Clause
compatibility: {}""".format("x" * 501)
        found = self.run_skill(frontmatter)
        self.assertEqual(len(found), 1)
        self.assertIn("limit is 500", found[0])

    def test_description_must_start_with_use_when(self):
        frontmatter = """name: rust-example
description: Covers an example with enough detail, but it does not use the required routing prefix.
license: BSD-3-Clause"""
        found = self.run_skill(frontmatter)
        self.assertEqual(len(found), 1)
        self.assertIn("must start with 'Use when '", found[0])

    def test_unclosed_rust_fence_fails(self):
        validate_skills.check_rust_fences("# Example\n\n```rust\nfn main() {}\n", "example.md")
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("Rust code fence is not closed", validate_skills.failures[0])

    def run_catalog(self, readme: str, skills: set[str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "README.md"
            path.write_text(readme, encoding="utf-8")
            original = validate_skills.README
            try:
                validate_skills.README = path
                validate_skills.failures.clear()
                validate_skills.check_readme_catalog(skills)
                return list(validate_skills.failures)
            finally:
                validate_skills.README = original

    def test_link_outside_catalog_does_not_satisfy_catalog(self):
        readme = """[rust-a](skills/rust-a/SKILL.md)

## Catalog

| Skill | What it covers |
| --- | --- |
"""
        found = self.run_catalog(readme, {"rust-a"})
        self.assertEqual(len(found), 1)
        self.assertIn("missing from the catalog table", found[0])

    def test_duplicate_catalog_row_fails(self):
        row = "| [rust-a](skills/rust-a/SKILL.md) | Description |\n"
        readme = "## Catalog\n\n| Skill | What it covers |\n| --- | --- |\n" + row + row
        found = self.run_catalog(readme, {"rust-a"})
        self.assertEqual(len(found), 1)
        self.assertIn("appears 2 times", found[0])


class TestRoutingGuard(unittest.TestCase):
    """A three-column row records a decision between two skills that both fit."""

    # Both skills carry a row of their own, as they do in the real corpus, so
    # the "every skill has a routing case" rule does not colour the result.
    CORPUS = """| Phrase a user types | Skill that must answer |
| --- | --- |
| API design | rust-discipline |

## Phrases that must not reach another skill

| Phrase a user types | Must answer | Must not answer |
| --- | --- | --- |
| panic policy | rust-panic-safety | rust-discipline |
"""

    def run_corpus(self, descriptions: dict, corpus: str | None = None) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "routing-cases.md"
            path.write_text(corpus or self.CORPUS, encoding="utf-8")
            validate_skills.ROUTING = path
            validate_skills.failures.clear()
            validate_skills.check_routing_cases(descriptions)
            return list(validate_skills.failures)

    def test_the_rival_keeping_the_phrase_fails(self):
        found = self.run_corpus(
            {
                "rust-panic-safety": "covers panic policy",
                "rust-discipline": "covers API design and panic policy",
            }
        )
        self.assertEqual(len(found), 1)
        self.assertIn("rust-discipline", found[0])

    def test_the_rival_without_the_phrase_passes(self):
        found = self.run_corpus(
            {"rust-panic-safety": "covers panic policy", "rust-discipline": "covers API design"}
        )
        self.assertEqual(found, [])

    def test_the_owner_losing_the_phrase_fails(self):
        found = self.run_corpus(
            {"rust-panic-safety": "covers catch_unwind", "rust-discipline": "covers API design"}
        )
        self.assertEqual(len(found), 1)
        self.assertIn("rust-panic-safety", found[0])

    def test_a_two_column_row_still_works(self):
        corpus = "| Phrase | Skill |\n| --- | --- |\n| catch_unwind | rust-panic-safety |\n"
        self.assertEqual(
            self.run_corpus({"rust-panic-safety": "covers catch_unwind"}, corpus), []
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
