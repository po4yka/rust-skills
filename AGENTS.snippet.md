<!-- rust-skills router. Paste into AGENTS.md or CLAUDE.md. Source: github.com/po4yka/rust-skills -->
## Rust skills: which one to load

Find the symptom, then load the named skill before you change code. Load a skill only when your
skill list names it; otherwise continue without one. Rows follow the bundles in order: language,
design, build, testing, concurrency, production, ffi. Delete the rows of a bundle you did not install.

| Symptom | Skill |
| --- | --- |
| A pasted rustc error: `E0382`, `E0499`, `E0282`, `does not live long enough` | rust-compiler-errors |
| A hang on a second `lock()` in a `match`; drop scope or temporary lifetime depends on syntax | rust-borrow-semantics |
| Match guard, partial move, binding mode, or match ergonomics surprise | rust-pattern-semantics |
| `is invariant over the parameter`, `borrowed for 'static` | rust-variance |
| Callback bound rejects `\|o\| &o.field`, a closure stored in a struct | rust-callback-bounds |
| A hand-written `Iterator` or `IntoIterator` | rust-iterator-impl |
| `HashMap<TypeId, _>` with borrowed values, `dyn Any`, `downcast_ref` | rust-type-erasure |
| `macro_rules!`, a derive, `cargo expand` | rust-macros |
| Method ambiguity, autoderef, UFCS, `E0034`, blanket-impl overlap, pub API shape | rust-discipline |
| Module file layout, `unreachable_pub`, `lib.rs` re-exports | rust-code-style |
| New workspace crate, layering violation, crate dependency cycle | rust-crate-architecture |
| Red clippy, `cargo fmt`, or `cargo doc` gate | rust-lints |
| `clap`, stdout and exit-code contract, Ctrl-C, shell completions | rust-cli |
| "`?` couldn't convert the error", `.context` not found, a thiserror or anyhow error type, an error chain or source | rust-error-handling |
| `--locked` failure, feature unification, `Cargo.lock`, cargo-nextest | cargo-workflows |
| SemVer bump, `cargo publish`, trusted publishing, a yank | rust-crate-release |
| `build.rs`, `pkg-config`, undefined symbol, DLL not found | rust-native-linking |
| `DeserializeOwned`, JSON map key, large integer, `rename_all` | rust-serde |
| `RUSTSEC` advisory, `cargo-deny`, a new unvetted dependency | rust-security |
| 16 KiB page alignment, Android AAR or Prefab, NDK flags | rust-android-build |
| `IPHONEOS_DEPLOYMENT_TARGET`, XCFramework, SwiftPM | rust-ios-build |
| `wasm32-unknown-unknown`, WASI, `wasm-bindgen`, Wasm size | rust-wasm |
| `no_std`, `memory.x`, interrupts, Embassy, RTIC, `defmt` | rust-embedded-no-std |
| Reproduce a bug as a failing test, or refactor under a safety net | rust-tdd |
| loom, proptest, cargo-fuzz, cargo-mutants | rust-test-tools |
| Miri, ThreadSanitizer, HWASan, or MTE report | rust-sanitizers-miri |
| `catch_unwind`, unwind vs abort, a panic at an FFI boundary | rust-panic-safety |
| Port a C, Python, Go, or JavaScript module to Rust; output must not change | rust-port |
| Review a pull request, a file, or a crate; write findings worst first | rust-review |
| `Ordering::Relaxed` vs `SeqCst`, fences, `static mut`, `OnceLock`, `thread_local!` | memory-model |
| Guard or `RefCell` borrow across `.await`, `select!` side effects, shutdown hang | rust-async-internals |
| `SAFETY` comment, `MaybeUninit`, provenance, `repr(packed)`, `unsafe impl Send` | rust-unsafe |
| `Pin<&mut Self>`, `PhantomPinned`, `#[pin]` projection | rust-pin-projection |
| `cannot be sent between threads safely`, `MutexGuard` is not `Send` | rust-send-sync |
| Every handler in an event loop needs `&mut` to one state | rust-event-loop-state |
| No profile yet: flamegraph, simpleperf, `cargo-bloat` | rust-performance |
| Profile names the hot spot: allocations, type size, hasher | rust-hot-path |
| `Cow<str>`, clone cost at an API boundary, an allocation on input that comes back unchanged | rust-copy-on-write |
| Tombstone, stripped backtrace, `addr2line` | rust-debugging |
| `SetLoggerError`, a silent `tracing` subscriber, metrics | rust-observability |
| HTTP timeout, retries, TLS verification, body limits | rust-networking |
| Pool exhaustion, transaction rollback, migration order | rust-database |
| `UnsatisfiedLinkError`, `AttachCurrentThread`, `FindClass` | rust-jni |
| Swift over a C ABI: garbage string, abort at an export, opaque handle, `@MainActor` callback | rust-swift-ffi |
| `uniffi::export` error, `UnexpectedUniFFICallbackError`, Record vs Object | uniffi-boundary |
| UniFFI checksum mismatch, `RustBuffer` error, binding version skew | uniffi-packaging-versioning |
| `Activity` lifecycle, `ViewModel.onCleared`, callback release race | ffi-error-progress-cancel |
