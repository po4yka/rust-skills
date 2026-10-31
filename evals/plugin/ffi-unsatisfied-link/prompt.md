---
description: The ffi bundle. A natural request that the rust-jni skill owns; the answer must cite that skill's verifier.
tags: [ffi, trigger]
runs: 2
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

The Android app crashes on the first call into our Rust library with `java.lang.UnsatisfiedLinkError: No implementation found for long com.example.core.NativeBridge.open(java.lang.String)`. The `.so` loads fine. How do I find out whether the Rust side exports the symbol the JVM is looking for?
