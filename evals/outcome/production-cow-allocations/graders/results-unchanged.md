---
type: llm
focus: trace
---

PASS if the last `cargo test` run after the final edit is green with the three original tests intact, and some test still exercises a name that needs lowercasing or trimming (for example `" Content-Length "`), so the owned path is covered.
FAIL if no `cargo test` run follows the final edit, if an original test was removed or weakened, or if a name with uppercase letters or surrounding whitespace now gives a different result than before.
