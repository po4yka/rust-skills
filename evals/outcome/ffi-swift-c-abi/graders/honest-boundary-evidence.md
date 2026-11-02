---
type: llm
focus: last_message
---

PASS if the answer lists the checks it ran (at least a green `cargo test` after the final edit) and states that Rust unit tests do not prove that Swift uses the boundary correctly, naming at least one check for the cross-language side that it did not or could not run here: a Swift or C consumer test against the built library, a run under Address Sanitizer, or Miri on the Rust export code.
FAIL if the answer claims that the Rust tests prove the iOS crash is fixed, or names no check for the Swift side at all.
