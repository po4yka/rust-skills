---
type: llm
---

PASS if the answer gives `cargo +nightly miri test` (with or without `--locked`) for the default Stacked Borrows run, gives `MIRIFLAGS="-Zmiri-tree-borrows"` for the second run, and says the default Stacked Borrows run is the blocking gate.
FAIL if the answer omits the Miri command, or makes Tree Borrows the only gate.
