---
type: llm
focus: trace
---

PASS if the review in REVIEW.md (shown in the final diff) puts in its highest-priority section both the undefined behavior of `from_utf8_unchecked` on bytes read from a file (non-UTF-8 input makes an invalid `&str`) and the panics of `unwrap` and indexing on file input in `load` and `parse_line`, and ranks them above every API or style finding.
FAIL if either defect is missing, if the `from_utf8_unchecked` call is not called undefined behavior or unsound, or if a style or naming finding is ranked above them.
