---
type: llm
focus: trace
---

PASS if the final diff adds a `PORTING.md` (or an equivalent notes file named in the final answer) that maps the Python functions to the Rust ones, maps the Python tests to the Rust tests, records the Python rules the port keeps (at least floor division and half-to-even rounding) as preserved behavior, quirks, or differences, and names checks that the trace shows the agent ran.
FAIL if there are no porting notes, if the notes leave out the test map, or if they claim a check that the trace does not show.
