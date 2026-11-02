---
type: llm
focus: trace
---

PASS if the agent measured heap allocations, not time: it ran code with a counting global allocator (a `#[global_allocator]` that counts calls to `alloc`) or an equivalent allocation counter on already-normalized header names, and the answer reports the count before and after the change (for example "one allocation per header before, zero after").
FAIL if the evidence is only a timing benchmark, only an argument from reading the code, or only the passing unit tests.
