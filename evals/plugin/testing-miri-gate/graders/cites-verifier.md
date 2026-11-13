---
type: llm
---

PASS only if the answer meets all three conditions:

1. Give a `cargo +nightly miri test` command for Stacked Borrows, without
   `-Zmiri-tree-borrows` on that run.
2. Give a second Miri test command with `-Zmiri-tree-borrows` in `MIRIFLAGS`.
3. State that the Stacked Borrows run blocks a merge. Tree Borrows can also block,
   but it cannot replace the Stacked Borrows gate.

Judge the options and the gate policy, not an exact command string. Accept a
pinned `+nightly-YYYY-MM-DD`, `--locked`, package or test filters, and shell line
continuations. Accept additional `MIRIFLAGS` such as `-Zmiri-strict-provenance` or
`-Zmiri-symbolic-alignment-check`, in either flag order. These options do not
change which aliasing model runs.

FAIL if either model's Miri test command is absent, if Stacked Borrows is optional
or non-blocking, or if Tree Borrows is the only blocking gate.
