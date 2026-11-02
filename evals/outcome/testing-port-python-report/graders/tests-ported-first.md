---
type: llm
focus: trace
---

PASS if the Rust tests cover every test of `test_report.py` one for one (six tests, with names that map back to the Python names), they were written and run before or together with the first implementation of the three functions, and the last test run after the final edit is green.
FAIL if a Python test has no Rust counterpart, if the Rust tests were only written after the implementation was complete, or if no green test run follows the final edit.
