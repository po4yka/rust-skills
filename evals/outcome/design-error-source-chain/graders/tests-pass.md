---
type: llm
focus: trace
---

PASS if the trace shows a `cargo test` run after the last edit to `src/lib.rs` that completes with the three original tests intact and no failure, and some test now checks that the io cause of a read failure is reachable through `Error::source`.
FAIL if no `cargo test` run follows the last edit, if an original test was removed or weakened, or if no test covers the source chain.
