#!/usr/bin/env python3
"""Regression tests for executable Rust fences."""
import unittest

import gen


class TestRunFence(unittest.TestCase):
    def test_run_fence_is_known(self):
        self.assertEqual(gen.parse_fence("```rust,run"), ("run", []))

    def test_run_fence_accepts_a_complete_main(self):
        self.assertIsNone(gen.run_problem("fn main() { assert_eq!(2 + 2, 4); }"))

    def test_run_fence_requires_main(self):
        self.assertIn("fn main", gen.run_problem("assert!(true);") or "")

    def test_run_fence_rejects_placeholders(self):
        for marker in ("todo!()", "unimplemented!()", "// TODO", "// FIXME"):
            with self.subTest(marker=marker):
                self.assertIsNotNone(gen.run_problem(f"fn main() {{ {marker}; }}"))


class TestPrelude(unittest.TestCase):
    def test_setup_opens_the_statement_body(self):
        source, shape = gen.wrap("let n = conn.len();", "", "let conn: Vec<u8> = Vec::new();")
        self.assertEqual(shape, "async-body")
        self.assertLess(source.index("let conn"), source.index("let n = conn.len()"))
        self.assertLess(source.index(gen.WRAPPER_OPEN), source.index("let conn"))

    def test_items_go_after_the_block_at_the_crate_root(self):
        source, shape = gen.wrap("#![forbid(unsafe_code)]\nstruct A(B);", "struct B;")
        self.assertEqual(shape, "item")
        self.assertLess(source.index("#![forbid"), source.index("struct B;"))

    def test_setup_is_rejected_on_an_item_block(self):
        with self.assertRaises(ValueError):
            gen.wrap("fn main() {}", "", "let x = 1;")

    def test_items_that_define_result_suppress_the_alias(self):
        source, _ = gen.wrap("fn f() -> Result<()> { todo!() }", "type Result<T> = std::io::Result<T>;")
        self.assertNotIn(gen.RESULT_ALIAS, source)

    def test_bad_entries_are_reported(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "p.toml"
            path.write_text(
                '[[block]]\nfile = "a.md"\nsection = "S"\nblock = 1\n'
                '[[block]]\nfile = "a.md"\nsection = "S"\nblock = 1\nitems = "struct A;"\n'
                '[[block]]\nfile = "a.md"\nsection = "S"\nblock = 1\nitems = "struct B;"\n'
                '[[block]]\nfile = "a.md"\nsection = "T"\nblock = 1\nitems = "x"\nextra = 1\n',
                encoding="utf-8",
            )
            preludes, problems = gen.load_preludes(path)
        self.assertEqual(list(preludes), [("a.md", "S", 1)])
        self.assertEqual(len(problems), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
