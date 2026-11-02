---
type: llm
focus: trace
---

PASS if the final diff of the workspace adds or changes only the review file (REVIEW.md, and at most a build artifact or lockfile that a cargo command wrote), and changes no line of `src/lib.rs`, `Cargo.toml`, or any other source file.
FAIL if the final diff changes any line of a source file, including a fix of one of the reviewed defects or a formatting change.
