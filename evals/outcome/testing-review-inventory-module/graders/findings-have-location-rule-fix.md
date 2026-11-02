---
type: llm
focus: trace
---

PASS if every finding in REVIEW.md gives a location (`src/lib.rs` with a line number, or a named function where no single line applies), names the rule it breaks in a way a reader can look up (a skill or guideline name, an API Guidelines code such as C-GETTER, or a clippy lint), and shows the fix as a short code change rather than prose alone or a rewrite of the whole module; and repeated `unwrap` calls are one grouped finding.
FAIL if any finding lacks a location or a rule, if most fixes are prose only, or if the review rewrites the whole module.
