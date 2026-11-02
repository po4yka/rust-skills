---
type: llm
focus: trace
---

PASS if REVIEW.md reports at least four of these five, in any section: the `String` error type of `take` (no `std::error::Error` type a caller can match), the `&String` parameter of `find`, the `bool` parameter of `report`, `Rc<RefCell<Vec<Item>>>` in the public `get_items` signature, and the `HashMap` iteration order that makes the `report` output nondeterministic. Where a finding sits is graded elsewhere.
FAIL if fewer than four of the five are reported.
