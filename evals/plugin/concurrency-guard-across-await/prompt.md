---
description: The concurrency bundle. A natural request that the rust-async-internals skill owns; the answer must cite that skill's verifier.
tags: [concurrency, trigger]
runs: 2
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Our tokio service deadlocks under load. In one handler I lock a `std::sync::Mutex`, call `.await` on a database query, and then write to the guarded map. How do I fix it, and how do I make CI catch this pattern before it ships again?
