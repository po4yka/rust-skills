---
type: llm
focus: trace
---

PASS if the final state keeps a regression test for a one-digit fraction through `parse_amount` or `InvoiceLine` and a separate one for `parse_rate_bps` (for example "7.5" gives 750), and the last `cargo test` (or `cargo nextest run`) after the final edit is green with no original test removed or weakened.
FAIL if either regression test is missing or was deleted after use, or if no green test run follows the final edit.
