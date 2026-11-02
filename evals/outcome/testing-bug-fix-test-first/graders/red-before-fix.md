---
type: llm
focus: trace
---

PASS if, before its first change to the production code (the bodies of `parse_fixed`, `parse_amount`, `parse_rate_bps`, or `InvoiceLine`), the agent added a test that reproduces the report (a price or amount with one fraction digit, such as `12.5`, through `parse_amount` or `InvoiceLine`), ran it, and the run failed with the wrong value (1205 or an equivalent off-by-ten result). The test may live in `tests/` or in a `#[cfg(test)]` module of `src/lib.rs`.
FAIL if the production code changed before any such failing run, if the first run of the new test passed, or if no test for the reported case was written at all.
