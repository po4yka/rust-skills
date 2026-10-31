---
description: The language bundle. A natural request that the rust-lints skill owns; the answer must cite that skill's verifier.
tags: [language, trigger]
runs: 2
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Our CI started failing on a clippy job after I bumped the toolchain, and I am not sure which lints are new or how to stage them. The workspace has about twenty crates and `[workspace.lints]` in the root manifest. What exact command should the gate run, and how do I tighten the lint levels without breaking every crate at once?
