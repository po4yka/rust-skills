---
type: llm
focus: last_message
---

PASS if the explanation says that the temporary `MutexGuard` created in the `match` scrutinee lives until the end of the whole `match` (through every arm), so the second `lock()` in the miss arm waits on a guard that the same thread still holds.
FAIL if the explanation only says "the mutex is locked twice" without naming the scrutinee temporary or its drop scope, or if it claims that edition 2024 or non-lexical lifetimes should have released the guard.
