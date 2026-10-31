---
type: llm
---

PASS if the answer gives a workspace clippy gate command that includes `cargo clippy`, `--locked`, `--workspace`, `--all-targets`, and `-D warnings`.
FAIL if the answer gives no clippy command, or gives one without `-D warnings` or without `--workspace`.
