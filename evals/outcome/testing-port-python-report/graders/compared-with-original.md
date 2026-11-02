---
type: llm
focus: trace
---

PASS if the agent compared the port with `report.py` itself on inputs beyond the six original tests: it ran the Python code (for example `python3 -c ...` or a script) on cases such as a negative total, an exact half, repeated or non-ASCII names, or amounts with spaces, and checked that the Rust results match, or turned those recorded outputs into Rust tests.
FAIL if the only evidence of equivalence is the ported tests, or if the agent reasons about Python's behavior without running the original on any input.
