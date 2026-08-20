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
| publish a Rust crate | rust-crate-release |
| cargo publish | rust-crate-release |
| cargo package | rust-crate-release |
| SemVer bump | rust-crate-release |
| MSRV change | rust-crate-release |
| yank a crate version | rust-crate-release |
| Rust binary release | rust-crate-release |
| release archive | rust-crate-release |
| release checksum | rust-crate-release |
| release SBOM | rust-crate-release |
| sign release artifact | rust-crate-release |
| build.rs | rust-native-linking |
| rustc-link-lib | rust-native-linking |
| pkg-config | rust-native-linking |
| undefined reference | rust-native-linking |
| library not loaded | rust-native-linking |
| DLL not found | rust-native-linking |
| windows-msvc | rust-native-linking |
| windows-gnu | rust-native-linking |
| LNK2019 | rust-native-linking |
| ERROR_BAD_EXE_FORMAT | rust-native-linking |
| import library | rust-native-linking |
| PDB | rust-native-linking |
| HTTP timeout | rust-networking |
| Retry-After | rust-networking |
| TLS verification | rust-networking |
| connection pool | rust-networking |
| response body limit | rust-networking |
| graceful shutdown | rust-networking |
| database pool exhaustion | rust-database |
| transaction rollback | rust-database |
| database migration ordering | rust-database |
| transaction cancellation safety | rust-database |
| serialization failure | rust-database |
| schema integration test | rust-database |
| wasm32-unknown-unknown | rust-wasm |
| wasm32-wasip1 | rust-wasm |
| wasm32-wasip2 | rust-wasm |
| wasm-bindgen | rust-wasm |
| WebAssembly Component Model | rust-wasm |
| wasm binary size | rust-wasm |
| no_std | rust-embedded-no-std |
| embedded Rust | rust-embedded-no-std |
| memory.x | rust-embedded-no-std |
| embedded-hal | rust-embedded-no-std |
| Embassy | rust-embedded-no-std |
| probe-rs | rust-embedded-no-std |
| Rust CLI | rust-cli |
| clap arguments | rust-cli |
| CLI exit codes | rust-cli |
| config precedence | rust-cli |
| broken pipe | rust-cli |
| atomic file replacement | rust-cli |
| Ctrl-C | rust-cli |
| shell completions | rust-cli |
| callbackFlow | ffi-error-progress-cancel |
| AsyncThrowingStream | ffi-error-progress-cancel |
| cancel_job | ffi-error-progress-cancel |
| Ordering::Relaxed | memory-model |
| happens-before | memory-model |
| compare-exchange | memory-model |
| 16 KiB page alignment | rust-android-build |
| jniLibs | rust-android-build |
| NDK | rust-android-build |
| native debug symbols | rust-android-build |
| Prefab | rust-android-build |
| Rust for iOS | rust-ios-build |
| IPHONEOS_DEPLOYMENT_TARGET | rust-ios-build |
| SwiftPM binaryTarget | rust-ios-build |
| dSYM UUID checks | rust-ios-build |
| PrivacyInfo.xcprivacy | rust-ios-build |
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
| dependency cycle | rust-crate-architecture |
| layering violation | rust-crate-architecture |
| tombstone | rust-debugging |
| RUST_BACKTRACE | rust-debugging |
| addr2line | rust-debugging |
| tokio-console | rust-debugging |
| RAII | rust-discipline |
| UnsatisfiedLinkError | rust-jni |
| AttachCurrentThread | rust-jni |
| JNIEnv | rust-jni |
| GlobalRef | rust-jni |
| Swift calls Rust through a C ABI | rust-swift-ffi |
| hand-written Swift FFI | rust-swift-ffi |
| opaque Rust handle in Swift | rust-swift-ffi |
| @MainActor Rust callback | rust-swift-ffi |
| AsyncStream over a C callback | rust-swift-ffi |
| clippy.toml | rust-lints |
| deny.toml | rust-lints |
| rustfmt.toml | rust-lints |
| workspace.lints | rust-lints |
| tracing | rust-observability |
| telemetry snapshot | rust-observability |
| production metrics | rust-observability |
| metric naming | rust-observability |
| histogram boundaries | rust-observability |
| label cardinality | rust-observability |
| OpenTelemetry context propagation | rust-observability |
| exporter shutdown | rust-observability |
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
| reduce allocations | rust-hot-path |
| too many allocations | rust-hot-path |
| this type is too big | rust-hot-path |
| large_enum_variant | rust-hot-path |
| which hasher | rust-hot-path |
| FxHashMap | rust-hot-path |
| bounds check | rust-hot-path |
| inline always | rust-hot-path |
| cold path | rust-hot-path |
| BufWriter | rust-hot-path |
| clone_from | rust-hot-path |
| SmallVec | rust-hot-path |
| swap_remove | rust-hot-path |
| with_capacity | rust-hot-path |
| reserve_exact | rust-hot-path |
| print-type-sizes | rust-hot-path |
| ThinVec | rust-hot-path |
| memcpy | rust-hot-path |
| workhorse | rust-hot-path |
| macro_rules | rust-macros |
| write a derive macro | rust-macros |
| proc macro | rust-macros |
| macro hygiene | rust-macros |
| fragment specifier | rust-macros |
| cannot find macro in this scope | rust-macros |
| cyclic package dependency | rust-macros |
| cargo expand | rust-macros |
| Cow<str> | rust-copy-on-write |
| copy-on-write | rust-copy-on-write |
| to_mut | rust-copy-on-write |
| borrowed or owned | rust-copy-on-write |
| clone cost | rust-copy-on-write |
| persistent collection | rust-copy-on-write |
| structural sharing | rust-copy-on-write |
| rpds | rust-copy-on-write |
| implement Iterator | rust-iterator-impl |
| custom iterator | rust-iterator-impl |
| IntoIterator | rust-iterator-impl |
| FromIterator | rust-iterator-impl |
| size_hint | rust-iterator-impl |
| ExactSizeIterator | rust-iterator-impl |
| lending iterator | rust-iterator-impl |
| unconditional_recursion | rust-iterator-impl |
| E0207 | rust-iterator-impl |
| global state | memory-model |
| static mut | memory-model |
| OnceLock | memory-model |
| LazyLock | memory-model |
| thread_local | memory-model |
| lazy_static | memory-model |
| pin projection | rust-pin-projection |
| structural pinning | rust-pin-projection |
| pin-project-lite | rust-pin-projection |
| PhantomPinned | rust-pin-projection |
| Pin::new_unchecked | rust-pin-projection |
| self-referential struct | rust-pin-projection |
| std::pin::pin! | rust-pin-projection |
| PinnedDrop | rust-pin-projection |
| address-sensitive | rust-pin-projection |
| covariant | rust-variance |
| contravariant | rust-variance |
| subtyping | rust-variance |
| is invariant over the parameter | rust-variance |
| unbounded lifetime | rust-variance |
| phantomdata variance | rust-variance |
| &mut is invariant | rust-variance |
| sender is invariant | rust-variance |
| one type is more general than the other | rust-callback-bounds |
| borrowed data escapes outside of closure | rust-callback-bounds |
| callback returns a reference | rust-callback-bounds |
| store a closure in a struct | rust-callback-bounds |
| fn pointer field | rust-callback-bounds |
| function item types cannot be named directly | rust-callback-bounds |
| TypeId | rust-type-erasure |
| dyn Any | rust-type-erasure |
| downcast_ref | rust-type-erasure |
| type erasure | rust-type-erasure |
| anymap | rust-type-erasure |
| extensions map | rust-type-erasure |
| resource registry | rust-type-erasure |
| cannot be shared between threads safely | rust-send-sync |
| MutexGuard is not Send | rust-send-sync |
| auto trait | rust-send-sync |
| Arc vs Rc | rust-send-sync |
| thread::scope | rust-send-sync |
| event loop | rust-event-loop-state |
| tick loop | rust-event-loop-state |
| handler registry | rust-event-loop-state |
| shared mutable state | rust-event-loop-state |
| god object | rust-event-loop-state |
| system and world | rust-event-loop-state |
| E0499 in my dispatch loop | rust-event-loop-state |
| coroutine resume | rust-event-loop-state |

## Phrases that must not reach another skill

Two skills can both look right for one phrase. Where the choice has been made, record it here.
`scripts/validate-skills.py` then checks both halves: the phrase is in the description that must
answer, and it is absent from the description that must not. That keeps the decision alive
through a later edit to either skill.

A phrase that appears in two descriptions is not automatically a conflict. A description may
name a term to hand it away, as `rust-crate-architecture` does with "A cyclic package dependency
that involves a proc-macro crate belongs to rust-macros." Add a row here only when one skill was
claiming a phrase the other owns.

| Phrase a user types | Must answer | Must not answer |
| --- | --- | --- |
| cannot be sent between threads safely | rust-send-sync | rust-compiler-errors |
| panic policy | rust-panic-safety | rust-discipline |
