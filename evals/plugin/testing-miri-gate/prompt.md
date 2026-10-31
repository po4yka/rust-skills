---
description: The testing bundle. A natural request that the rust-sanitizers-miri skill owns; the answer must cite that skill's verifier.
tags: [testing, trigger]
runs: 2
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

I rewrote our arena allocator with raw pointers and want CI to catch undefined behaviour in it. Someone said to run the tests under both Stacked Borrows and Tree Borrows. Which run should block a merge, and what are the exact commands?
