---
description: The production bundle. A natural request that the rust-performance skill owns; the answer must cite that skill's verifier.
tags: [production, trigger]
runs: 2
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

I profiled our release build with `cargo flamegraph` and the graph is mostly hex addresses with almost no function names. I need a usable profile of the hot loop. What should I change in the build, and how do I confirm the profiled binary has what it needs?
