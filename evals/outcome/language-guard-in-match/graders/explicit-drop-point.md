---
type: llm
focus: {source: file, path: src/lib.rs}
---

PASS if, in `get_or_render`, no guard from the lookup is still alive when the miss path locks the same mutex again. Any of these passes: the lookup result is read out (for example with `.cloned()`) in its own `let` statement or block before the second `lock()`; a named guard is dropped or goes out of scope first; one `lock()` serves both the lookup and the insert (for example through `entry`); or an `if let` on the lookup with the second `lock()` in its `else` branch, which releases the guard before `else` on this crate's edition 2024.
FAIL if a `match` scrutinee, or a named guard, still holds the lock while another `lock()` on the same mutex runs in the same call, or if the deadlock is avoided by a change that the request did not allow, such as a different public signature.
