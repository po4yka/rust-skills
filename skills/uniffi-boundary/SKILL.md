---
name: uniffi-boundary
description: Use when authoring, changing, or reviewing the exported Rust surface of a UniFFI crate that generates Kotlin and Swift bindings, or when fixing a UniFFI macro or bindgen error. Includes the Record versus Object choice, foreign callback traits, custom types, and borrowed or async arguments. Not for packaging or version skew (uniffi-packaging-versioning) or for error, progress, and cancel semantics (ffi-error-progress-cancel). Triggers on uniffi::export, uniffi::Object, uniffi::Record, setup_scaffolding, UniFfiTag, export(foreign), callback_interface, with_foreign, custom_newtype, custom_type!, UnexpectedUniFFICallbackError, or UDL.
license: BSD-3-Clause
---

# UniFFI Boundary

A UniFFI boundary crate is a thin adapter. It declares the exported surface, and the
bindings generator produces Kotlin and Swift from the same Rust signatures. This skill owns
the shape of that surface. These skills, when installed, own the adjacent topics:

| Topic | Skill |
|-------|-------|
| Error taxonomy, progress delivery to `Flow` or `AsyncThrowingStream`, cancel, job registry | `ffi-error-progress-cancel` |
| cdylib and staticlib, bindgen commands, header and modulemap, UniFFI version pins and skew | `uniffi-packaging-versioning` |
| XCFramework assembly and SwiftPM `binaryTarget` | `rust-ios-build` |
| Hand-written JNI or C ABI without UniFFI | `rust-jni`, `rust-swift-ffi` |
| Unwind policy and the `panic` profile | `rust-panic-safety` |
| Atomics behind a cancel or progress flag | `memory-model` |
| A manual `unsafe impl Send` or `Sync`, raw pointers | `rust-unsafe` |
| Crate split and dependency direction | `rust-crate-architecture` |

## Version floor

The examples target UniFFI 0.32.x. The proc-macro surface changes between minor versions.
When `Cargo.lock` pins a `uniffi` version below the floor of a row, use the older form or
upgrade. The `uniffi-packaging-versioning` skill owns the upgrade.

| Form | Needs |
|------|-------|
| `uniffi::custom_type!(T, Bridge, { lower, try_lift })`. `UniffiCustomTypeConverter` is removed. | 0.29 |
| `#[uniffi::export] impl` on a Record or an Enum (methods on data types) | 0.31 |
| `#[uniffi::export(foreign)]` and `#[uniffi::export(rust, foreign)]`. Before 0.32, write `with_foreign`. | 0.32 |
| `&[u8]` argument without a copy (Kotlin direct `java.nio.ByteBuffer`) | 0.32 |
| `HashSet<T>`, `Box<T>` (parameters, enum variants, recursive types), `async_runtime` on a trait export | 0.32 |

Kotlin consumers need 0.32.1 or later for the device checksum fixes. The
`uniffi-packaging-versioning` skill owns version pins.

## Scaffolding: proc-macros, no UDL

1. Call `uniffi::setup_scaffolding!()` exactly once, at the top of the crate root (`lib.rs`).
2. Annotate exported functions, `impl` blocks, and traits with `#[uniffi::export]`.
3. Derive `uniffi::Record`, `uniffi::Object`, `uniffi::Enum`, or `uniffi::Error` on exported
   types.
4. Generate Kotlin and Swift from the compiled library of one build. The
   `uniffi-packaging-versioning` skill has the commands.

Do not add a `.udl` file to a proc-macro crate. Two declarations of one surface drift, and
the generated Kotlin and Swift then disagree.

## Object or Record

| | Object | Record |
|---|---|---|
| Derive | `uniffi::Object` | `uniffi::Record` |
| Foreign form | Opaque reference-counted handle | Kotlin `data class`, Swift `struct` |
| Crossing cost | One handle | Every field, on every call |
| Identity | Kept; the Rust value never moves | None; copied by value |
| Exposed through | Methods | Fields; since 0.31 also methods, which run on a copy |
| Field rule | Fields stay private to Rust | Every field is a UniFFI type |
| Thread bounds | `Send + Sync` | None |

State and behavior are an Object. Messages and data are a Record. An engine handle, a
session, a connection pool, or anything with interior mutability is an Object. A request, a
result, a summary, or an event payload is a Record.

Do not export a free function that reads hidden global state. Put the state in an Object:
the platform then owns its lifetime, and a test can create a fresh one.

Read `references/type-mapping.md` when you choose the type of a field or argument, add a
custom type, or add a default argument. Read `references/interface-patterns.md` when you shape
constructors, a long-running job, an async export, a versioned JSON payload, large data,
crossing cost, a trait interface, or the content of the boundary crate.

## `Send + Sync` on every exported Object

UniFFI rejects an Object that is not `Send + Sync`, because the foreign handle is used from
any thread. Kotlin calls it from a dispatcher thread. Swift calls it from any task.

```rust,compile_fail,E0277
uniffi::setup_scaffolding!();

mod counter {
    #[derive(uniffi::Object)]
    pub struct Counter {
        hits: std::cell::Cell<u32>, // `Cell` is not `Sync`
    }
}
```

The error names the field type at the derive, not at a call site. Here it is
`` `Cell<u32>` cannot be shared between threads safely ``.

- Hold shared state behind `Mutex`, `RwLock`, or an atomic.
- If a type cannot be `Send + Sync`, keep it in a deeper crate and export a `Send + Sync`
  facade.
- Treat a manual `unsafe impl Sync` as a soundness review item for the `rust-unsafe` skill.

## Ownership across the boundary

- **`Arc` identity, not bytes.** Returning an Object moves one strong reference into the
  foreign handle. The value drops after the last foreign handle and the last Rust owner
  release it.
- **Kotlin frees a handle deterministically only on `close()`.** Generated Kotlin Object
  classes implement `AutoCloseable`. Call `close()` or `use { }` on an Object that owns files,
  threads, or large memory. Otherwise the Rust `Drop` waits for the JVM `Cleaner`. Swift frees
  the handle in `deinit`.
- **Borrowed arguments last for one call.** A top-level shared reference argument, such as
  `&str`, `&[u8]`, `&Record`, or `&Object`, is valid only during the Rust call. Do not store it
  or return it. A borrowed return fails with an unsatisfied `LowerReturn<UniFfiTag>` bound.
  `&mut T`, `Option<&T>`, and nested references do not cross.
- **`&[u8]` changes the Kotlin type.** In 0.32, a `&[u8]` argument becomes a direct
  `java.nio.ByteBuffer` in Kotlin, and a heap buffer throws `IllegalArgumentException`. The
  generated converter sends the base address of the buffer with `remaining()` bytes, so the
  position must be 0: call `flip()` after `put()`, or pass `buf.slice()`. Otherwise Rust
  silently reads the wrong bytes. Swift passes `Data`. `&[u8]` flows only from the foreign
  side into Rust. It does not work in an async export or in a foreign-trait method.
- **Records are copied.** Every Record field is converted on every call. A large `Vec<T>`
  field is a per-call cost, not a pointer handoff.
- **Cycles leak.** A foreign object that holds the Rust Object, and a Rust Object that holds
  the foreign callback, form a cycle that no runtime collects. UniFFI does not detect it.

### Mobile ownership shape

- Export engine Objects whose lifetimes are independent of UI owners. Several engine Objects
  can hold isolated state and share one process execution provider. Do not model an Android
  `Activity`, a `ViewModel`, a Swift view controller, or a Swift task as a Rust Object.
- The `ffi-error-progress-cancel` skill owns the execution model, idempotent initialization,
  and non-blocking callback release.

## Errors: the shape rule

The `ffi-error-progress-cancel` skill owns error semantics. This skill enforces two shape
rules:

1. Every fallible export returns `Result<_, E>`, and `E` derives `uniffi::Error`. Do not use a
   sentinel return value or an out-parameter.
2. No panic reaches the foreign caller. The scaffolding catches an unwind, but the foreign
   side cannot match on the result:

| Caller | Result of a Rust panic |
|--------|------------------------|
| Kotlin | `InternalException`, outside the declared error type |
| Swift `throws` function | An internal error, outside the declared error type |
| Swift non-throwing function | A fatal error that the app cannot catch; the process ends |
| Any, with `panic = "abort"` | The process ends |

A non-throwing export, such as `cancel_job(&self, id: String)`, must therefore be panic-free by
construction. The `rust-panic-safety` skill owns the unwind policy.

Apply the FFI-path panic lint set from the `rust-panic-safety` skill in `lib.rs`. For a
UniFFI adapter, also deny `clippy::unreachable` and `clippy::indexing_slicing`, because a
panic in a non-throwing export is a Swift fatal error. Add `clippy::arithmetic_side_effects`
when the crate does arithmetic.

Add `#![forbid(unsafe_code)]` when the crate has no hand-written `unsafe`. The generated
scaffolding does not trip it (rustc 1.98.1, UniFFI 0.32.2). The `rust-unsafe` skill owns
that rule.

The lints do not see a panic inside an inner crate that the adapter calls, or inside a
panicking std API such as `split_at`, `Vec::remove`, or `copy_from_slice`. Keep the body of a
non-throwing export total: an atomic store, or a lock that recovers poison with
`PoisonError::into_inner`. Otherwise wrap the inner call in `std::panic::catch_unwind` and map
a panic to a no-op or a logged event.

## Codegen and bindgen failure triage

The Rust messages below are from rustc 1.98.1 with UniFFI 0.32.2.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `E0425` ``cannot find type `UniFfiTag` in the crate root`` | `setup_scaffolding!()` is missing, or it is in a submodule | Call it once at the top of `lib.rs` |
| `E0428` ``the name `ffi_<crate>_rust_future_...` is defined multiple times`` | `setup_scaffolding!()` is called twice | Remove the second call |
| `E0277` ``… cannot be shared between threads safely`` or ``… cannot be sent between threads safely`` at `derive(uniffi::Object)` | A field is not `Sync` or not `Send` | Put the state behind `Mutex` or an atomic, or keep the type out of the boundary crate |
| `E0277` ``the trait bound `usize: Lift<UniFfiTag>` is not satisfied`` (also `Lower`, `TypeId`) | The field or argument type has no UniFFI mapping | Convert to a mapped type with an explicit `From`; see `references/type-mapping.md` |
| `E0277` ``the trait bound `&str: LowerReturn<UniFfiTag>` is not satisfied`` | A borrowed return | Return an owned value or an `Arc` handle |
| `E0277` `` `*const u8` cannot be sent between threads safely `` naming `ForeignBytes` | `&[u8]` in an async export | Take `Vec<u8>` |
| `E0053` ``method `…` has an incompatible type for trait`` at `#[uniffi::export(foreign)]` (for `&[u8]` also `E0277` ``the trait bound `ForeignBytes: uniffi::Lower<UniFfiTag>` is not satisfied``) | A reference argument in a foreign-trait method | Pass the argument by value |
| `E0405` ``cannot find trait `UniffiCustomTypeConverter` in this scope`` | Code for UniFFI 0.28 or older | Use `uniffi::custom_type!` |
| Kotlin bindgen: `Async primary constructors not supported` | `async fn new` under `#[uniffi::constructor]` | Rename it to a named async constructor |
| Async export panics on first poll: `there is no reactor running` | A Tokio timer, socket, or `spawn` without a Tokio runtime | Add `async_runtime = "tokio"` and the `uniffi` `tokio` feature, or spawn onto the process runtime `Handle` |
| Kotlin runtime: `IllegalArgumentException` about a direct `ByteBuffer` | A heap buffer passed to a `&[u8]` argument | Use `ByteBuffer.allocateDirect` on the caller side |
| Rust gets an empty or shifted `&[u8]` from Kotlin | The direct buffer has a non-zero position, often `put()` without `flip()` | Call `flip()` after `put()`, or pass `buf.slice()` |
| Swift app ends with a fatal error in a generated non-throwing call | A Rust panic, or a failed custom-type lift, in a non-throwing export | Make the export panic-free; declare an error on any export that takes a fallible custom type |
| Generated Swift fails to compile with actor-isolation errors | The module uses `SWIFT_DEFAULT_ACTOR_ISOLATION=MainActor` (Swift 6.2+, uniffi-rs#2818) | Compile the generated Swift in a module with `nonisolated` default isolation; see `uniffi-packaging-versioning` |
| Generated Kotlin and Swift disagree, or one is stale | Two generator runs at different versions, or a leftover `.udl` | Regenerate both from one build; delete the `.udl` |
| Callback never fires on the foreign side | The handle was dropped, or the call happens after the job returned | Hold the callback for the job duration |
| Foreign object leaks after a job | A reference cycle across the boundary | Do not store the Rust Object inside the foreign callback |

## Verify

| Claim | Check | When |
|-------|-------|------|
| The surface compiles | `cargo check -p <boundary-crate>` | While you iterate |
| No unguarded panic site; each kept `.expect` carries `#[expect(clippy::expect_used, reason = "...")]` | `cargo clippy --locked -p <boundary-crate> --all-targets -- -D warnings`, with the lint set above | Before merge |
| Behavior and error mapping | `cargo test --locked -p <boundary-crate>`. Call the exported methods directly, implement the callback traits in Rust, and assert the event order, the error variants, and cancel | Every change |
| Error mapping is total | Each `From<InnerError>` impl matches every variant with no `_` arm, so a new variant fails to compile | When an inner error enum changes |
| Custom types round trip | A property test that converts to the bridge type and back | When you add or change a custom type |
| Bindings generate | Generate Kotlin and Swift from one build in CI; `uniffi-packaging-versioning` has the commands | Every change to the boundary crate |

A green clippy run does not prove that an export cannot panic: the lints do not see inner
crates or panicking std APIs. A green Rust run does not prove that the generated Kotlin or
Swift compiles, that Kotlin callers pass a direct buffer at position 0, or that a Swift
module's isolation accepts the generated code. Only a platform build and a smoke test on the
pinned toolchain prove those. For a `&[u8]` export, the Kotlin smoke test fills a direct
buffer with `put()`, sends it through the app's own call path, and asserts the length and
the bytes that Rust received.

## Foreign callbacks and listeners

Deliver progress and events through a foreign trait that the platform implements and Rust
calls. Read `references/interface-patterns.md` ("Minimal boundary crate") when you create a
boundary crate or write a foreign trait. It holds the complete crate root, compiled against
UniFFI 0.32, with the full `ProgressListener` pattern.

- Put `Send + Sync` on the trait. Rust calls it from a worker thread.
- Give every method a `Result<_, CallbackError>` return. The callback error is a
  `uniffi::Error` type that implements `From<uniffi::UnexpectedUniFFICallbackError>`.
  Without that impl, an undeclared foreign exception panics in the generated code.
- Map the callback error into the operation's error with an exhaustive `From`. Never discard
  the callback result. The `ffi-error-progress-cancel` skill owns the listener-failure
  policy: by default the job fails with `EngineError::Unexpected`.
- Pass every argument by value. Foreign-trait methods do not accept references
  (uniffi-rs#2263).
- Keep the trait coarse: one `on_progress(event)`, not a per-item or per-row callback. A
  synchronous callback blocks the Rust worker until Kotlin or Swift returns. Coalesce and
  rate-limit in Rust before you call out.
- An `Arc<dyn Trait>` keeps the foreign object alive. Hold it for one call or one job, then
  drop it. A listener that must outlive a job needs a registration token and an idempotent
  release method (the `ffi-error-progress-cancel` skill owns it). Never store it with no
  release path; the platform cannot see or break that reference.
- Take the trait as `Arc<dyn Trait>`. Use `#[uniffi::export(foreign)]` when only foreign
  implementations cross, and `#[uniffi::export(rust, foreign)]` when both sides implement it.
  Do not add `callback_interface` (soft-deprecated) to new code. On 0.32 or later, do not add
  `with_foreign` (deprecated alias). Below 0.32, `with_foreign` is the only spelling.
  `references/interface-patterns.md` has the migration rule.

## Async exports

Prefer synchronous exports that the platform runs off the main thread, with progress through
the callback. An exported `async fn` must return a `Send` future. It needs
`#[uniffi::export(async_runtime = "tokio")]` when it uses Tokio resources, or the first poll
panics. It must be drop-safe at every `.await`, because Kotlin coroutine cancellation drops the
future there and UniFFI sends Rust no cancel signal. Read `references/interface-patterns.md`
("Async exports") when you add or review an async export.

## Stability rules for an existing surface

A reshaped export regenerates Kotlin and Swift and can break both consumers in one commit.

- Prefer a new coarse method, or an argument with a generated default, over a change of
  arity. `references/type-mapping.md` has the default forms.
- Prefer a wider JSON contract, validated in Rust, over a new parameter.
- Treat an added enum variant as a source break. An exhaustive Kotlin `when` or Swift
  `switch` stops compiling after regeneration. Removing or changing a variant is breaking.
- Treat a change from `Vec<u8>` to `&[u8]` as a Kotlin source break: `ByteArray` becomes
  `ByteBuffer`.
- Use one UniFFI version for both platforms. The `uniffi` crate, the runtime, and the bindgen
  must match. A boundary review flags any per-platform divergence.

## Review

Read `references/review-checklist.md` when you review a change to the boundary crate or gate
its merge.

## Sources

Read the pages for the UniFFI version in `Cargo.lock`. `latest` tracks the newest release.

| Topic | URL |
|-------|-----|
| Proc-macros, derives, `setup_scaffolding!` | <https://mozilla.github.io/uniffi-rs/latest/proc_macro/index.html> |
| Interfaces (Objects), constructors, `Arc` | <https://mozilla.github.io/uniffi-rs/latest/types/interfaces.html> |
| Foreign traits, `UnexpectedUniFFICallbackError`, cycles | <https://mozilla.github.io/uniffi-rs/latest/foreign_traits.html> |
| `&[u8]` arguments | <https://mozilla.github.io/uniffi-rs/latest/types/bytes.html> |
| Custom types | <https://mozilla.github.io/uniffi-rs/latest/types/custom_types.html> |
| Async and futures | <https://mozilla.github.io/uniffi-rs/latest/futures.html> |
| Kotlin object lifetimes | <https://mozilla.github.io/uniffi-rs/latest/kotlin/lifetimes.html> |
| Swift panics and `Sendable` | <https://mozilla.github.io/uniffi-rs/latest/swift/overview.html> |
| CHANGELOG | <https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md> |
