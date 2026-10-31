---
type: llm
---

PASS if the answer says not to hold the guard across `.await` (scope or drop the guard first, or use an async-aware lock where the guard must cross the await) and gives a clippy command that denies `clippy::await_holding_lock`.
FAIL if the answer does not name `await_holding_lock`, or it suggests only a bigger thread pool or a timeout.
