# Routing cases

An agent decides whether to open a skill from its `description` alone. Nothing else in the
repository is read first. This file records the phrases a user is expected to type, and the skill
that must answer each one.

`scripts/validate-skills.py` checks every row: the named skill must exist, and the phrase must
appear in that skill's `description`, case-insensitively. The check is static. It does not run a
model, so it cannot prove that routing works — it proves that a description edit did not silently
drop a term the catalog promised to answer.

Add a row when you add a skill. Add a row when you find a phrase a user typed that reached the
wrong skill, and put the phrase in the right description in the same change.

| Phrase a user types | Skill that must answer |
| --- | --- |
| Cargo.lock | cargo-workflows |
| cargo nextest | cargo-workflows |
| feature-unification | cargo-workflows |
| callbackFlow | ffi-error-progress-cancel |
| AsyncThrowingStream | ffi-error-progress-cancel |
| cancel_job | ffi-error-progress-cancel |
| Ordering::Relaxed | memory-model |
| happens-before | memory-model |
| compare-exchange | memory-model |
| 16 KiB page alignment | rust-android-build |
| jniLibs | rust-android-build |
| NDK | rust-android-build |
| tokio::select! | rust-async-internals |
| block_on | rust-async-internals |
| CancellationToken | rust-async-internals |
| shutdown hang | rust-async-internals |
| re-export | rust-code-style |
| import grouping | rust-code-style |
| E0382 | rust-compiler-errors |
| E0499 | rust-compiler-errors |
| borrow checker | rust-compiler-errors |
| does not live long enough | rust-compiler-errors |
| missing lifetime specifier | rust-compiler-errors |
| cannot be sent between threads | rust-compiler-errors |
| dependency cycle | rust-crate-architecture |
| layering violation | rust-crate-architecture |
| tombstone | rust-debugging |
| RUST_BACKTRACE | rust-debugging |
| addr2line | rust-debugging |
| tokio-console | rust-debugging |
| panic policy | rust-discipline |
| RAII | rust-discipline |
| UnsatisfiedLinkError | rust-jni |
| AttachCurrentThread | rust-jni |
| JNIEnv | rust-jni |
| GlobalRef | rust-jni |
| clippy.toml | rust-lints |
| deny.toml | rust-lints |
| rustfmt.toml | rust-lints |
| workspace.lints | rust-lints |
| tracing | rust-observability |
| telemetry snapshot | rust-observability |
| catch_unwind | rust-panic-safety |
| panic hook | rust-panic-safety |
| flamegraph | rust-performance |
| simpleperf | rust-performance |
| cargo-bloat | rust-performance |
| LTO | rust-performance |
| ThreadSanitizer | rust-sanitizers-miri |
| tree borrows | rust-sanitizers-miri |
| HWASan | rust-sanitizers-miri |
| MTE | rust-sanitizers-miri |
| RUSTSEC | rust-security |
| deny_unknown_fields | rust-serde |
| rename_all | rust-serde |
| untagged | rust-serde |
| serde(flatten) | rust-serde |
| skip_serializing_if | rust-serde |
| serde(try_from) | rust-serde |
| typosquat | rust-security |
| cargo-audit | rust-security |
| red-green-refactor | rust-tdd |
| golden-contract | rust-tdd |
| fault-injection | rust-tdd |
| cargo-mutants | rust-test-tools |
| proptest | rust-test-tools |
| cargo-fuzz | rust-test-tools |
| SAFETY comment | rust-unsafe |
| repr(packed) | rust-unsafe |
| improper_ctypes | rust-unsafe |
| OwnedFd | rust-unsafe |
| mem::zeroed | rust-unsafe |
| E0793 | rust-unsafe |
| uniffi::export | uniffi-boundary |
| callback_interface | uniffi-boundary |
| custom_newtype | uniffi-boundary |
| UDL | uniffi-boundary |
| XCFramework | uniffi-packaging-versioning |
| RustBuffer | uniffi-packaging-versioning |
| checksum mismatch | uniffi-packaging-versioning |
