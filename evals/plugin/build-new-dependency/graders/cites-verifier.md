---
type: llm
---

PASS if the answer tells the user to run `cargo deny` (for example `cargo deny check advisories` or `cargo deny check`) or `cargo audit` as the CI gate, and flags the crate name as a possible typosquat of `serde_json`.
FAIL if the answer names neither `cargo deny` nor `cargo audit`, or it approves the crate without questioning the name.
