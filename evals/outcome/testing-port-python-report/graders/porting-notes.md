---
type: llm
focus: trace
---

PASS if the final diff adds a `PORTING.md` (or an equivalent notes file named in the final answer) that maps the Python functions to the Rust ones, maps the Python tests to the Rust tests, records each deliberate difference or preserved quirk (at least the rounding and the floor division rules), and says how the port was checked.
FAIL if there are no porting notes, or if the notes leave out the test map or the record of how the port was checked.
