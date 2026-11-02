---
type: llm
focus: trace
---

PASS if the trace shows a `cargo test` run after the last edit to `src/lib.rs` that completes, runs at least the two original tests, and reports no failure.
FAIL if no `cargo test` run follows the last edit, if that run times out or fails, or if an original test was deleted or weakened (for example by removing an assertion) to make it pass.
