---
type: llm
focus: trace
---

PASS if REVIEW.md has a section that names two or more specific things the code does well, and the trace shows the agent ran `cargo clippy` and `cargo test` before or while it wrote the review and reports their results in REVIEW.md (or states why it could not run them).
FAIL if there is no such section, if it is generic praise, or if the review says nothing about which tools ran.
