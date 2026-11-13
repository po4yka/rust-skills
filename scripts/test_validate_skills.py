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
import json
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

    def run_skill(self, frontmatter: str, body: str = "", files: dict[str, str] | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            skill = root / "skills" / "rust-example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\n{frontmatter}\n---\n# Example\n{body}", encoding="utf-8"
            )
            for name, content in (files or {}).items():
                (skill / name).parent.mkdir(parents=True, exist_ok=True)
                (skill / name).write_text(content, encoding="utf-8")
            original_root = validate_skills.ROOT
            try:
                validate_skills.ROOT = root
                validate_skills.failures.clear()
                validate_skills.descriptions.clear()
                validate_skills.check_skill(skill)
                return list(validate_skills.failures)
            finally:
                validate_skills.ROOT = original_root

    def test_optional_spec_fields_fail(self):
        # allowed-tools pre-approves tools in Claude Code; the other two are
        # free text no gate reads. AGENTS.md allows exactly three keys.
        for extra in (
            "allowed-tools: Bash(*)",
            "compatibility: Requires Rust",
            "metadata:\n  author: example-org",
        ):
            with self.subTest(extra=extra):
                frontmatter = (
                    "name: rust-example\n"
                    "description: Use when you need a sufficiently detailed example for frontmatter key validation.\n"
                    f"license: BSD-3-Clause\n{extra}"
                )
                found = self.run_skill(frontmatter)
                self.assertTrue(found)
                self.assertTrue(
                    any("outside the spec" in f or "indented frontmatter line" in f for f in found), found
                )

    def test_license_must_equal_repository_license(self):
        for value in ("", "MIT", "null", "BSD-3-Clause"):
            with self.subTest(value=value):
                frontmatter = (
                    "name: rust-example\n"
                    "description: Use when checking a complete example of the repository license validation contract.\n"
                    f"license: {value}"
                )
                found = self.run_skill(frontmatter)
                if value == "BSD-3-Clause":
                    self.assertEqual(found, [])
                else:
                    self.assertTrue(any("license is" in f for f in found), found)

    def test_description_must_start_with_use_when(self):
        frontmatter = """name: rust-example
description: Covers an example with enough detail, but it does not use the required routing prefix.
license: BSD-3-Clause"""
        found = self.run_skill(frontmatter)
        self.assertEqual(len(found), 1)
        self.assertIn("must start with 'Use when '", found[0])

    VALID = """name: rust-example
description: Use when you need a sufficiently detailed example for link and file size validation.
license: BSD-3-Clause"""

    def test_skill_over_the_line_limit_fails(self):
        found = self.run_skill(self.VALID, body="line\n" * validate_skills.MAX_SKILL_LINES)
        self.assertEqual(len(found), 1)
        self.assertIn("lines, the limit is", found[0])

    def test_links_resolve_from_the_file_that_holds_them(self):
        found = self.run_skill(
            self.VALID,
            body="Read [a](references/a.md) when needed. Read `references/b.md` when needed.\n",
            files={
                "references/a.md": "See [b](b.md#part) and [back](../SKILL.md) and [web](https://example.com).\n",
                "references/b.md": "# B\n",
            },
        )
        self.assertEqual(found, [])

    def test_missing_sibling_reference_fails(self):
        found = self.run_skill(
            self.VALID,
            body="Read [a](references/a.md) when needed.\n",
            files={"references/a.md": "See [b](b.md).\n"},
        )
        self.assertEqual(len(found), 1)
        self.assertIn("missing file: b.md", found[0])

    def test_link_into_another_skill_fails(self):
        # An install of one skill has no sibling skill directories.
        found = self.run_skill(self.VALID, body="See [x](../rust-other/SKILL.md).\n")
        self.assertEqual(len(found), 1)
        self.assertIn("outside its skill directory", found[0])

    def test_repository_path_to_a_skill_fails(self):
        found = self.run_skill(self.VALID, body="See `skills/rust-other/references/x.md`.\n")
        self.assertEqual(len(found), 1)
        self.assertIn("repository path", found[0])

    def test_unclosed_rust_fence_fails(self):
        validate_skills.failures.clear()
        validate_skills.check_fences("# Example\n\n```rust\nfn main() {}\n", "example.md")
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("code fence is not closed", validate_skills.failures[0])

    def fences(self, text: str) -> list[str]:
        validate_skills.failures.clear()
        validate_skills.check_fences(text, "example.md")
        return list(validate_skills.failures)

    def test_every_fence_spelling_gen_py_skips_fails(self):
        # checks/gen.py reads only a line that starts with ```rust. Each of these
        # once passed both gates while no cargo run ever saw the block.
        for opener in ("```rs", "```Rust", "~~~rust", "````rust", "``` rust", "```rust,no_run", "```"):
            with self.subTest(opener=opener):
                close = "~~~" if opener.startswith("~") else "````" if opener.startswith("````") else "```"
                found = self.fences(f"{opener}\nfn main() {{}}\n{close}\n")
                self.assertTrue(found, opener)

    def test_known_fences_pass(self):
        for opener in ("```rust", "```rust,run", "```rust,ignore", "```rust,compile_fail,E0499,E0502", "```bash", "```text"):
            with self.subTest(opener=opener):
                self.assertEqual(self.fences(f"{opener}\nx\n```\n"), [])

    def test_a_language_outside_the_list_fails(self):
        found = self.fences("```haskell\nmain = pure ()\n```\n")
        self.assertEqual(len(found), 1)
        self.assertIn("'haskell'", found[0])

    def test_invisible_characters_fail(self):
        for char in ("\u200b", "\u202e", "\U000e0041", "\x07"):
            with self.subTest(char=repr(char)):
                found = self.run_skill(self.VALID, body=f"Run the tests.{char}\n")
                self.assertEqual(len(found), 1)
                self.assertIn("invisible character", found[0])

    def test_a_file_outside_skill_md_and_references_fails(self):
        found = self.run_skill(self.VALID, files={"scripts/run.sh": "echo hi\n"})
        self.assertEqual(len(found), 1)
        self.assertIn("only SKILL.md and references/*.md", found[0])

    def test_a_reference_skill_md_never_names_fails(self):
        found = self.run_skill(self.VALID, files={"references/a.md": "# A\n"})
        self.assertEqual(len(found), 1)
        self.assertIn("is not linked from SKILL.md", found[0])

    def test_a_link_to_its_own_file_fails(self):
        found = self.run_skill(
            self.VALID,
            body="Read [a](references/a.md) when needed.\n",
            files={"references/a.md": "Read [a.md](a.md#part) when you write it.\n"},
        )
        self.assertEqual(len(found), 1)
        self.assertIn("links to itself", found[0])

    def test_reference_style_and_html_links_cannot_leave_the_skill(self):
        for body in ("See [other][o].\n\n[o]: ../rust-unsafe/SKILL.md\n", '<a href="../rust-unsafe/SKILL.md">x</a>\n'):
            with self.subTest(body=body):
                found = self.run_skill(self.VALID, body=body)
                self.assertEqual(len(found), 1)
                self.assertIn("links outside its skill directory", found[0])

    def test_link_syntax_inside_a_code_fence_is_code(self):
        found = self.run_skill(self.VALID, body="```rust\nlet y = table[0](arg);\n```\n")
        self.assertEqual(found, [])

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

    def run_graph(self, readme: str, skills: set[str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "README.md"
            path.write_text(readme, encoding="utf-8")
            original = validate_skills.README
            try:
                validate_skills.README = path
                validate_skills.failures.clear()
                validate_skills.check_readme_graph(skills)
                return list(validate_skills.failures)
            finally:
                validate_skills.README = original

    def test_graph_requires_every_skill_once(self):
        readme = """```mermaid
flowchart LR
    A[rust-a]
```
"""
        found = self.run_graph(readme, {"rust-a", "rust-b"})
        self.assertEqual(len(found), 1)
        self.assertIn("rust-b", found[0])
        self.assertIn("appears 0 times", found[0])

    def test_duplicate_graph_skill_fails(self):
        readme = """```mermaid
flowchart LR
    A[rust-a]
    B[rust-a]
```
"""
        found = self.run_graph(readme, {"rust-a"})
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

    def test_a_table_line_no_gate_reads_fails(self):
        for row in ("| catch_unwind | `rust-panic-safety` |", "| catch_unwind | rust-panic-safety | x | y |", " | catch_unwind | rust-panic-safety |"):
            with self.subTest(row=row):
                corpus = "| Phrase | Skill |\n| --- | --- |\n| catch_unwind | rust-panic-safety |\n" + row + "\n"
                found = self.run_corpus({"rust-panic-safety": "covers catch_unwind"}, corpus)
                self.assertTrue(any("not a routing row" in f for f in found), found)

    def test_a_phrase_every_description_shares_fails(self):
        corpus = "| Phrase | Skill |\n| --- | --- |\n| Use when | rust-panic-safety |\n| ab | rust-discipline |\n"
        found = self.run_corpus(
            {"rust-panic-safety": "Use when a panic crosses FFI", "rust-discipline": "Use when an API ab"}, corpus
        )
        self.assertTrue(any("'Use when'" in f and "claims it too" in f for f in found), found)
        self.assertTrue(any("shorter than" in f for f in found), found)

    def test_a_rival_mention_inside_not_for_is_allowed(self):
        corpus = "| Phrase | Skill |\n| --- | --- |\n| catch_unwind | rust-panic-safety |\n| API design | rust-discipline |\n"
        found = self.run_corpus(
            {
                "rust-panic-safety": "covers catch_unwind",
                "rust-discipline": "covers API design. Not for catch_unwind; use rust-panic-safety.",
            },
            corpus,
        )
        self.assertEqual(found, [])

    def test_a_two_column_row_still_works(self):
        corpus = "| Phrase | Skill |\n| --- | --- |\n| catch_unwind | rust-panic-safety |\n"
        self.assertEqual(
            self.run_corpus({"rust-panic-safety": "covers catch_unwind"}, corpus), []
        )


class HarnessRules(unittest.TestCase):
    """Rules that guard the install surface: bundles, budgets, router, references."""

    def setUp(self):
        self.saved = {
            k: getattr(validate_skills, k)
            for k in (
                "ROOT", "SKILLS_DIR", "README", "BUNDLES", "SNIPPET", "NEGATIVE", "CEILINGS",
                "PLUGIN_MANIFEST", "MARKETPLACE",
            )
        }
        validate_skills.failures.clear()
        validate_skills.warnings.clear()
        validate_skills.descriptions.clear()
        validate_skills.bodies.clear()

    def tearDown(self):
        for key, value in self.saved.items():
            setattr(validate_skills, key, value)
        validate_skills.descriptions.clear()
        validate_skills.bodies.clear()

    def use_tree(self, tmp: str, files: dict[str, str]) -> pathlib.Path:
        root = pathlib.Path(tmp)
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(content, encoding="utf-8")
        validate_skills.ROOT = root
        validate_skills.SKILLS_DIR = root / "skills"
        validate_skills.README = root / "README.md"
        validate_skills.BUNDLES = root / "bundles.toml"
        validate_skills.SNIPPET = root / "AGENTS.snippet.md"
        validate_skills.NEGATIVE = root / "negative-cases.md"
        validate_skills.CEILINGS = root / "ceilings.toml"
        validate_skills.PLUGIN_MANIFEST = root / ".claude-plugin" / "plugin.json"
        validate_skills.MARKETPLACE = root / ".claude-plugin" / "marketplace.json"
        return root

    BUNDLES = """[bundles.core]
skills = ["rust-a", "rust-b"]

[bundles.edge]
skills = ["rust-c"]
"""
    README = "## Install\n\n| Bundle |\n| --- |\n| `core` |\n| `edge` |\n\n## Next\n"

    # Bundle membership and the README install table.

    def test_bundles_that_cover_each_skill_once_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": self.BUNDLES, "README.md": self.README})
            bundles = validate_skills.load_bundles()
            validate_skills.check_bundles(bundles, {"rust-a", "rust-b", "rust-c"})
        self.assertEqual(validate_skills.failures, [])

    def test_a_skill_in_no_bundle_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": self.BUNDLES, "README.md": self.README})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c", "rust-d"})
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("'rust-d' is in no bundle", validate_skills.failures[0])

    def test_a_skill_in_two_bundles_fails(self):
        bundles = self.BUNDLES.replace('["rust-c"]', '["rust-c", "rust-a"]')
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": bundles, "README.md": self.README})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("2 bundles", validate_skills.failures[0])

    def test_a_bundle_missing_from_the_install_table_fails(self):
        readme = self.README.replace("| `edge` |\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": self.BUNDLES, "README.md": readme})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("'edge' has no row in the Install table", validate_skills.failures[0])

    COUNTED_README = ("## Install\n\n| Bundle | Subject | Skills | Plugin |\n| --- | --- | ---: | --- |\n"
                      "| `core` | Core | 2 | `p-core` |\n| `edge` | Edge | 1 | `p-edge` |\n\n## Next\n")

    def test_install_table_counts_that_match_the_bundles_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": self.BUNDLES, "README.md": self.COUNTED_README})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
        self.assertEqual(validate_skills.failures, [])

    def test_a_stale_install_table_count_fails(self):
        # A skill joins `core`, and the README row still says 2.
        bundles = self.BUNDLES.replace('["rust-a", "rust-b"]', '["rust-a", "rust-b", "rust-d"]')
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": bundles, "README.md": self.COUNTED_README})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c", "rust-d"})
        self.assertEqual(len(validate_skills.failures), 1)
        self.assertIn("'core' shows 2 skills in the Install table; bundles.toml lists 3",
                      validate_skills.failures[0])

    COMMANDS_README = (
        "## Install\n\n| Bundle |\n| --- |\n| `core` |\n| `edge` |\n\n```bash\n"
        "# core\nfor s in rust-a rust-b; do\n  gh skill install o/r \"$s\"\ndone\n"
        "# edge\nfor s in rust-c; do\n  gh skill install o/r \"$s\"\ndone\n```\n\n```bash\n"
        "# core\nnpx skills add o/r --skill rust-a rust-b\n# edge\nnpx skills add o/r --skill rust-c\n"
        "```\n\n## Next\n"
    )

    def check_commands(self, readme: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"bundles.toml": self.BUNDLES, "README.md": readme})
            validate_skills.check_bundles(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
        return list(validate_skills.failures)

    def test_install_commands_in_step_with_the_bundles_pass(self):
        self.assertEqual(self.check_commands(self.COMMANDS_README), [])

    def test_an_install_command_that_drops_a_skill_fails(self):
        found = self.check_commands(self.COMMANDS_README.replace("--skill rust-a rust-b", "--skill rust-a"))
        self.assertEqual(len(found), 1)
        self.assertIn("install command for bundle 'core'", found[0])

    def test_a_bundle_without_both_install_commands_fails(self):
        found = self.check_commands(self.COMMANDS_README.replace("# edge\nnpx skills add o/r --skill rust-c\n", ""))
        self.assertEqual(len(found), 1)
        self.assertIn("'edge' has 1 labelled install commands", found[0])

    # The plugin marketplace: one entry per bundle, in step with bundles.toml.

    def entries(self) -> list[dict]:
        license = {"license": "BSD-3-Clause"}
        return [
            {"name": "kit", "source": "./", "description": "All 3 Rust agent skills.", **license},
            {
                "name": "kit-core",
                "source": "./",
                "description": "Core: 2 Rust agent skills.",
                "skills": ["./skills/rust-a", "./skills/rust-b"],
                **license,
            },
            {
                "name": "kit-edge",
                "source": "./",
                "description": "Edge: 1 Rust agent skills.",
                "skills": ["./skills/rust-c"],
                **license,
            },
        ]

    def marketplace(self, entries: list[dict], manifest: dict | None = None, top: dict | None = None) -> list[str]:
        files = {
            "bundles.toml": self.BUNDLES,
            ".claude-plugin/marketplace.json": json.dumps({"name": "kit", **(top or {}), "plugins": entries}),
        }
        if manifest is not None:
            files[".claude-plugin/plugin.json"] = json.dumps(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, files)
            validate_skills.check_marketplace(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
        return list(validate_skills.failures)

    def test_a_marketplace_in_step_with_the_bundles_passes(self):
        self.assertEqual(self.marketplace(self.entries()), [])

    def test_bundle_skills_in_another_order_fail(self):
        entries = self.entries()
        entries[1]["skills"].reverse()
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("skills differ from bundles.toml", found[0])

    def test_a_stale_skill_count_fails(self):
        entries = self.entries()
        entries[1]["description"] = "Core: 3 Rust agent skills."
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("'2 Rust agent skills'", found[0])

    def test_a_version_field_fails(self):
        # One `version` that is not bumped freezes every consumer on it.
        entries = self.entries()
        entries[2]["version"] = "1.0.0"
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("`version`", found[0])

    def test_a_source_other_than_the_root_fails(self):
        # A github source with a ref loads every skill, not the bundle.
        entries = self.entries()
        entries[1]["source"] = {"source": "github", "repo": "owner/kit", "ref": "v1"}
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn('source must be "./"', found[0])

    def test_a_bundle_without_an_entry_fails(self):
        found = self.marketplace(self.entries()[:2])
        self.assertEqual(len(found), 1)
        self.assertIn("'kit-edge' appears 0 times", found[0])

    def test_an_entry_without_a_bundle_fails(self):
        entries = self.entries() + [{"name": "kit-extra", "source": "./", "skills": ["./skills/rust-a"]}]
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("'kit-extra' matches no bundle", found[0])

    def test_a_duplicate_entry_fails(self):
        entries = self.entries()
        found = self.marketplace(entries + [entries[2]])
        self.assertEqual(len(found), 1)
        self.assertIn("'kit-edge' appears 2 times", found[0])

    def test_an_entry_key_that_changes_what_a_consumer_runs_fails(self):
        for key, value in (("hooks", "./hooks/hooks.json"), ("mcpServers", {}), ("agents", []), ("strict", False)):
            with self.subTest(key=key):
                validate_skills.failures.clear()
                entries = self.entries()
                entries[1][key] = value
                found = self.marketplace(entries)
                self.assertEqual(len(found), 1)
                self.assertIn(f"sets {key!r}", found[0])

    def test_an_unknown_top_level_key_fails(self):
        found = self.marketplace(self.entries(), top={"metadata": {"pluginRoot": "./x"}})
        self.assertEqual(len(found), 1)
        self.assertIn("top-level key 'metadata'", found[0])

    def test_a_plugin_component_at_the_root_fails(self):
        for path in ("hooks/hooks.json", ".mcp.json", "commands/x.md", "agents/x.md"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                validate_skills.failures.clear()
                self.use_tree(
                    tmp,
                    {
                        "bundles.toml": self.BUNDLES,
                        ".claude-plugin/marketplace.json": json.dumps({"name": "kit", "plugins": self.entries()}),
                        path: "{}",
                    },
                )
                validate_skills.check_marketplace(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
                found = list(validate_skills.failures)
                self.assertEqual(len(found), 1)
                self.assertIn("must not exist at the repository root", found[0])

    def test_a_raised_or_added_ceiling_fails_against_the_base(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "scripts").mkdir()
            ceilings = root / "scripts" / "catalog-ceilings.toml"
            ceilings.write_text("[body_tokens]\nrust-a = 5000\n\n[cross_refs]\nrust-a = 3\n", encoding="utf-8")
            git = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True)
            git("init", "-q")
            git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", ".")
            git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
            validate_skills.ROOT = root
            cases = {
                "unchanged": ({"body_tokens": {"rust-a": 5000}, "cross_refs": {"rust-a": 3}}, 0),
                "lowered": ({"body_tokens": {"rust-a": 4900}, "cross_refs": {"rust-a": 3}}, 0),
                "raised": ({"body_tokens": {"rust-a": 5001}, "cross_refs": {"rust-a": 3}}, 1),
                "added": ({"body_tokens": {"rust-a": 5000, "rust-b": 4900}, "cross_refs": {"rust-a": 3}}, 1),
                # The documented exception: a fallback sentence for each resolved reference.
                "fallback": ({"body_tokens": {"rust-a": 5100}, "cross_refs": {"rust-a": 1}}, 0),
                "too much": ({"body_tokens": {"rust-a": 5200}, "cross_refs": {"rust-a": 2}}, 1),
            }
            for name, (current, expected) in cases.items():
                with self.subTest(case=name):
                    validate_skills.failures.clear()
                    validate_skills.check_ceilings_against("HEAD", current)
                    self.assertEqual(len(validate_skills.failures), expected, validate_skills.failures)

    def test_a_root_plugin_json_fails(self):
        # Codex refuses every bundle whose name differs from the root manifest.
        found = self.marketplace(self.entries(), {"name": "kit"})
        self.assertEqual(len(found), 1)
        self.assertIn("plugin.json: must not exist", found[0])

    def test_a_codex_or_portable_root_manifest_fails(self):
        for path in (".codex-plugin/plugin.json", "plugin.json"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                validate_skills.failures.clear()
                files = {
                    "bundles.toml": self.BUNDLES,
                    ".claude-plugin/marketplace.json": json.dumps({"name": "kit", "plugins": self.entries()}),
                    path: json.dumps({"name": "kit"}),
                }
                self.use_tree(tmp, files)
                validate_skills.check_marketplace(validate_skills.load_bundles(), {"rust-a", "rust-b", "rust-c"})
                self.assertEqual(len(validate_skills.failures), 1)
                self.assertTrue(validate_skills.failures[0].startswith(f"{path}: must not exist"))

    def test_an_entry_without_the_license_fails(self):
        entries = self.entries()
        del entries[1]["license"]
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn('license must be "BSD-3-Clause"', found[0])

    def test_a_top_level_marketplace_version_fails(self):
        found = self.marketplace(self.entries(), top={"version": "1"})
        self.assertEqual(len(found), 1)
        self.assertIn("top-level `version`", found[0])

    def test_a_name_that_is_not_a_string_fails_without_a_crash(self):
        entries = self.entries()
        entries[2]["name"] = ["kit-edge"]
        found = self.marketplace(entries)
        self.assertTrue(any("plugins[2] name must be a string" in f for f in found))
        self.assertTrue(any("'kit-edge' appears 0 times" in f for f in found))

    def test_a_description_that_is_not_a_string_fails(self):
        # str() of a list would still contain the count and pass.
        entries = self.entries()
        entries[1]["description"] = ["Core: 2 Rust agent skills."]
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("'2 Rust agent skills'", found[0])

    def test_a_full_catalog_entry_that_lists_skills_fails(self):
        entries = self.entries()
        entries[0]["skills"] = ["./skills/rust-a"]
        found = self.marketplace(entries)
        self.assertEqual(len(found), 1)
        self.assertIn("must not list skills", found[0])

    # Description budget: total and per bundle, with the ratchet.

    def budget(self, sizes: dict[str, int], ceilings: dict | None = None) -> list[str]:
        validate_skills.descriptions.update({name: "x" * n for name, n in sizes.items()})
        bundles = {"core": ["rust-a", "rust-b"], "edge": ["rust-c"]}
        validate_skills.check_description_budget(bundles, ceilings or {})
        return list(validate_skills.failures)

    def test_a_catalog_under_the_total_passes(self):
        self.assertEqual(self.budget({"rust-a": 2000, "rust-b": 2000, "rust-c": 2000}), [])

    def test_the_catalog_total_is_reported_not_capped(self):
        # Each bundle is capped; the full catalog is documented as over budget.
        found = self.budget({"rust-a": 4900, "rust-b": 0, "rust-c": 4900} | {f"rust-{i}": 1100 for i in range(10)})
        self.assertEqual(found, [])

    def test_a_stale_total_ceiling_is_flagged(self):
        self.budget({"rust-a": 100, "rust-b": 0, "rust-c": 100}, {"description": {"total": 21000}})
        self.assertTrue(any("remove [description]" in w for w in validate_skills.warnings))

    def test_a_bundle_over_the_listing_budget_fails(self):
        found = self.budget({"rust-a": 2600, "rust-b": 2600, "rust-c": 100})
        self.assertEqual(len(found), 1)
        self.assertIn("bundle 'core'", found[0])

    def test_a_ratcheted_bundle_may_stay_but_not_grow(self):
        sizes = {"rust-a": 2600, "rust-b": 2600, "rust-c": 100}
        self.assertEqual(self.budget(sizes, {"bundle_descriptions": {"core": 5200}}), [])
        validate_skills.failures.clear()
        self.assertEqual(len(self.budget(sizes, {"bundle_descriptions": {"core": 5199}})), 1)

    # Body token cap, with the ratchet.

    def body_check(self, chars: int, ceilings: dict | None = None) -> list[str]:
        validate_skills.bodies["rust-a"] = "x" * chars
        validate_skills.check_body_tokens(ceilings or {})
        return list(validate_skills.failures)

    def test_a_body_under_the_cap_passes(self):
        self.assertEqual(self.body_check(int(validate_skills.MAX_BODY_TOKENS * validate_skills.CHARS_PER_TOKEN)), [])

    def test_a_body_over_the_cap_fails(self):
        found = self.body_check(int(validate_skills.MAX_BODY_TOKENS * validate_skills.CHARS_PER_TOKEN) + 3)
        self.assertEqual(len(found), 1)
        self.assertIn("the limit is 4,800", found[0])

    def test_a_body_over_the_warning_line_warns(self):
        self.assertEqual(self.body_check(int(4600 * validate_skills.CHARS_PER_TOKEN)), [])
        self.assertTrue(any("over 4,500" in w for w in validate_skills.warnings))

    def test_a_ratcheted_body_may_shrink_but_not_grow(self):
        chars = 6000 * 2.5
        self.assertEqual(self.body_check(int(chars), {"body_tokens": {"rust-a": 6000}}), [])
        self.assertEqual(self.body_check(int(chars) - 250, {"body_tokens": {"rust-a": 6000}}), [])
        self.assertTrue(any("lower body_tokens.rust-a" in w for w in validate_skills.warnings))
        found = self.body_check(int(chars) + 3, {"body_tokens": {"rust-a": 6000}})
        self.assertEqual(len(found), 1)
        self.assertIn("accepted ceiling is 6,000", found[0])

    # The router snippet.

    def snippet(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"AGENTS.snippet.md": text})
            validate_skills.check_snippet({"rust-a", "rust-b"})
        return list(validate_skills.failures)

    def test_a_snippet_that_routes_to_each_skill_once_passes(self):
        self.assertEqual(self.snippet("| E0382 | rust-a |\n| a macro | rust-b |\n"), [])

    def test_a_snippet_missing_a_skill_fails(self):
        found = self.snippet("| E0382 | rust-a |\n")
        self.assertEqual(len(found), 1)
        self.assertIn("'rust-b' appears 0 times", found[0])

    def test_a_snippet_naming_a_skill_twice_fails(self):
        found = self.snippet("| E0382 | rust-a |\n| a macro | rust-b |\n| also | rust-a |\n")
        self.assertEqual(len(found), 1)
        self.assertIn("'rust-a' appears 2 times", found[0])

    def test_a_skill_name_inside_a_longer_name_does_not_count(self):
        found = self.snippet("| E0382 | rust-a |\n| a macro | rust-b |\n| x | rust-a-extra |\n")
        self.assertEqual(found, [])

    def test_a_long_snippet_fails(self):
        found = self.snippet("| E0382 | rust-a |\n| a macro | rust-b |\n" + "filler\n" * 59)
        self.assertEqual(len(found), 1)
        self.assertIn("limit is 60", found[0])

    # Cross-bundle references and their fallback.

    def cross_refs(self, body: str, ceilings: dict | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"skills/rust-a/SKILL.md": body, "skills/rust-b/SKILL.md": "", "skills/rust-c/SKILL.md": ""})
            bundles = {"core": ["rust-a", "rust-b"], "edge": ["rust-c"]}
            validate_skills.check_cross_refs(bundles, ceilings or {})
        return list(validate_skills.failures)

    def test_a_same_bundle_reference_needs_no_fallback(self):
        self.assertEqual(self.cross_refs("The `rust-b` skill owns that.\n"), [])

    def test_a_bare_cross_bundle_reference_fails(self):
        found = self.cross_refs("# T\n\nRead on.\nThe `rust-c` skill owns that.\n")
        self.assertEqual(len(found), 1)
        self.assertIn("SKILL.md:4", found[0])
        self.assertIn("`rust-c`", found[0])

    def test_a_fallback_in_the_same_sentence_passes(self):
        self.assertEqual(self.cross_refs("Run `cargo deny check` (the `rust-c` skill owns the policy).\n"), [])

    def test_a_fallback_in_the_next_sentence_passes(self):
        self.assertEqual(self.cross_refs("The `rust-c` skill owns it. Without it, run `cargo audit`.\n"), [])

    def test_a_fallback_two_sentences_away_does_not_count(self):
        found = self.cross_refs("The `rust-c` skill owns it. Read on. Run `cargo audit`.\n")
        self.assertEqual(len(found), 1)

    def test_a_skill_name_is_not_a_fallback(self):
        found = self.cross_refs("The `rust-c` skill owns it, with `rust-b`.\n")
        self.assertEqual(len(found), 1)

    def test_a_reference_inside_a_code_block_is_ignored(self):
        self.assertEqual(self.cross_refs("```text\nthe `rust-c` skill\n```\n"), [])

    def test_a_table_cell_is_its_own_sentence(self):
        found = self.cross_refs("| Miri | the `rust-c` skill | on a schedule |\n")
        self.assertEqual(len(found), 1)

    def test_a_name_in_a_list_or_table_counts_too(self):
        # The old pattern saw only "the `x` skill"; a list or a table cell escaped it.
        for body in ("Use these when installed: `rust-b` (async), `rust-c` (FFI).\n",
                     "| `rust-c` | the aliasing rules |\n"):
            with self.subTest(body=body):
                validate_skills.failures.clear()
                found = self.cross_refs(body)
                self.assertEqual(len(found), 1)
                self.assertIn("`rust-c`", found[0])

    def test_a_table_boundary_cell_with_a_command_passes(self):
        self.assertEqual(self.cross_refs("| `rust-c` | dependency vetting: `cargo deny check` |\n"), [])

    def test_the_description_is_not_checked(self):
        body = "---\nname: rust-a\ndescription: Use when x. Not for FFI; use `rust-c`.\nlicense: BSD-3-Clause\n---\n# T\n"
        self.assertEqual(self.cross_refs(body), [])

    def test_the_cross_ref_ceiling_accepts_known_gaps_but_not_new_ones(self):
        body = "The `rust-c` skill owns it.\n"
        self.assertEqual(self.cross_refs(body, {"cross_refs": {"rust-a": 1}}), [])
        found = self.cross_refs(body + "\nThe `rust-c` skill again.\n", {"cross_refs": {"rust-a": 1}})
        self.assertEqual(len(found), 1)
        self.assertIn("accepted ceiling is 1", found[0])

    # Negative routing cases.

    NEGATIVE = """| Phrase | Must not appear in | Owner | Collision |
| --- | --- | --- | --- |
| loom | rust-a | rust-b | test tool |
"""

    def negative(self, descriptions: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.use_tree(tmp, {"negative-cases.md": self.NEGATIVE})
            validate_skills.check_negative_cases(descriptions)
        return list(validate_skills.failures)

    def test_a_rival_without_the_phrase_passes(self):
        self.assertEqual(self.negative({"rust-a": "Use when writing tests first.", "rust-b": "Use for loom."}), [])

    def test_a_rival_claiming_the_phrase_fails(self):
        found = self.negative({"rust-a": "Use when writing tests or a Loom model.", "rust-b": "Use for loom."})
        self.assertEqual(len(found), 1)
        self.assertIn("rust-a", found[0])

    def test_a_not_for_boundary_may_name_the_phrase(self):
        found = self.negative({"rust-a": "Use when writing tests first. Not for loom; use rust-b.", "rust-b": "loom"})
        self.assertEqual(found, [])

    def test_an_unknown_skill_fails(self):
        found = self.negative({"rust-a": "Use when writing tests first."})
        self.assertEqual(len(found), 1)
        self.assertIn("'rust-b'", found[0])


class TestRealCatalogHarness(unittest.TestCase):
    """The shipped bundles, snippet, and negative cases satisfy their own rules."""

    def test_the_repository_passes_the_harness_rules(self):
        validate_skills.failures.clear()
        validate_skills.warnings.clear()
        validate_skills.descriptions.clear()
        validate_skills.bodies.clear()
        for skill_dir in sorted(validate_skills.SKILLS_DIR.iterdir()):
            validate_skills.check_skill(skill_dir)
        names = set(validate_skills.descriptions)
        bundles = validate_skills.load_bundles()
        ceilings = validate_skills.load_ceilings()
        validate_skills.check_bundles(bundles, names)
        validate_skills.check_marketplace(bundles, names)
        validate_skills.check_snippet(names)
        validate_skills.check_negative_cases(validate_skills.descriptions)
        validate_skills.check_body_tokens(ceilings)
        validate_skills.check_cross_refs(bundles, ceilings)
        self.assertEqual(validate_skills.failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
