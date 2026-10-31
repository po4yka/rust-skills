<!-- rust-skills router. Paste into AGENTS.md or CLAUDE.md. Source: github.com/po4yka/rust-skills -->
## Rust skills: which one to load

Find the symptom, then load the named skill before you change code. Load a skill only if it is
installed. If none fits, continue without one.

| Symptom | Skill |
| --- | --- |
| A pasted rustc error: `E0382`, `E0499`, `E0282`, `does not live long enough` | rust-compiler-errors |
| Temporary lifetime, drop scope, two-phase borrow, or autoref depends on syntax | rust-borrow-semantics |
| Match guard, partial move, binding mode, or match ergonomics surprise | rust-pattern-semantics |
| Guard or `RefCell` borrow across `.await`, `select!` side effects, shutdown hang | rust-async-internals |
| `Ordering::Relaxed` vs `SeqCst`, fences, `static mut`, `OnceLock`, `thread_local!` | memory-model |
| `macro_rules!`, a derive, `cargo expand` | rust-macros |
| A hand-written `Iterator` or `IntoIterator` | rust-iterator-impl |
| Module file layout, `unreachable_pub`, `lib.rs` re-exports | rust-code-style |
| Red clippy, `cargo fmt`, or `cargo doc` gate | rust-lints |
| `SAFETY` comment, `MaybeUninit`, provenance, `repr(packed)`, `unsafe impl Send` | rust-unsafe |
| Miri, ThreadSanitizer, HWASan, or MTE report | rust-sanitizers-miri |
| No profile yet: flamegraph, simpleperf, `cargo-bloat` | rust-performance |
| Profile names the hot spot: allocations, type size, hasher | rust-hot-path |
| `Cow<str>`, `to_mut`, clone cost at an API boundary | rust-copy-on-write |
| Tombstone, stripped backtrace, `addr2line` | rust-debugging |
| `SetLoggerError`, a silent `tracing` subscriber, metrics | rust-observability |
| `UnsatisfiedLinkError`, `AttachCurrentThread`, `FindClass` | rust-jni |
| Swift over a C ABI, opaque handle, `@MainActor` callback | rust-swift-ffi |
| `uniffi::export` error, `UnexpectedUniFFICallbackError`, Record vs Object | uniffi-boundary |
| UniFFI checksum mismatch, `RustBuffer` error, binding version skew | uniffi-packaging-versioning |
| `Activity` lifecycle, `ViewModel.onCleared`, callback release race | ffi-error-progress-cancel |
| `RUSTSEC` advisory, `cargo-deny`, a new unvetted dependency | rust-security |
| `DeserializeOwned`, JSON map key, large integer, `rename_all` | rust-serde |
| Method ambiguity, autoderef, UFCS, `E0034`, blanket-impl overlap, pub API shape | rust-discipline |
| `catch_unwind`, unwind vs abort, a panic at an FFI boundary | rust-panic-safety |
| Reproduce a bug as a failing test, or refactor under a safety net | rust-tdd |
| loom, proptest, cargo-fuzz, cargo-mutants | rust-test-tools |
| `is invariant over the parameter`, `borrowed for 'static` | rust-variance |
| Callback bound rejects `\|o\| &o.field`, a closure stored in a struct | rust-callback-bounds |
| `Pin<&mut Self>`, `PhantomPinned`, `#[pin]` projection | rust-pin-projection |
| `cannot be sent between threads safely`, `MutexGuard` is not `Send` | rust-send-sync |
| `HashMap<TypeId, _>` with borrowed values, `dyn Any`, `downcast_ref` | rust-type-erasure |
| Every handler in an event loop needs `&mut` to one state | rust-event-loop-state |
| 16 KiB page alignment, Android AAR or Prefab, NDK flags | rust-android-build |
| `IPHONEOS_DEPLOYMENT_TARGET`, XCFramework, SwiftPM | rust-ios-build |
| `--locked` failure, feature unification, `Cargo.lock`, cargo-nextest | cargo-workflows |
| SemVer bump, `cargo publish`, trusted publishing, a yank | rust-crate-release |
| `build.rs`, `pkg-config`, undefined symbol, DLL not found | rust-native-linking |
| New workspace crate, layering violation, crate dependency cycle | rust-crate-architecture |
| HTTP timeout, retries, TLS verification, body limits | rust-networking |
| Pool exhaustion, transaction rollback, migration order | rust-database |
| `wasm32-unknown-unknown`, WASI, `wasm-bindgen`, Wasm size | rust-wasm |
| `no_std`, `memory.x`, interrupts, Embassy, RTIC, `defmt` | rust-embedded-no-std |
| `clap`, stdout and exit-code contract, Ctrl-C, shell completions | rust-cli |
