---
type: llm
focus: trace
---

PASS if the final state keeps a regression test for a one-digit fraction through `parse_amount` or `InvoiceLine` and a separate one for `parse_rate_bps` (for example "7.5" gives 750), the last `cargo test` run after the final edit is green with no original test removed or weakened, and the final answer states the red failure it saw and the number of tests that passed.
FAIL if either regression test is missing or was deleted after use, if no green `cargo test` run follows the final edit, or if the answer gives no red failure or no test count.
