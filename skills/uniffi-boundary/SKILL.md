---
name: uniffi-boundary
description: Use when writing or reviewing the exported Rust surface of a UniFFI crate for Kotlin and Swift, or fixing a UniFFI macro or bindgen error. Includes Record versus Object, callback traits, custom types, and async exports. Not for packaging or version skew (uniffi-packaging-versioning) or error, progress, and cancel semantics (ffi-error-progress-cancel). Triggers on uniffi::export, uniffi::Object, uniffi::Record, setup_scaffolding, UniFfiTag, export(foreign), callback_interface, custom_newtype, UnexpectedUniFFICallbackError, UDL, async_runtime, or there is no reactor running.
license: BSD-3-Clause
---

# UniFFI Boundary

A UniFFI boundary crate is a thin adapter. It declares the exported surface, and the
bindings generator produces Kotlin and Swift from the same Rust signatures. This skill owns
the shape of that surface. When installed, the `ffi-error-progress-cancel` skill owns error
taxonomy, progress, and cancel; the `uniffi-packaging-versioning` skill owns bindgen commands,
packaging, and version pins; `rust-jni` and `rust-swift-ffi` own a hand-written ABI.

## Version floor

The examples target UniFFI 0.32.x; Kotlin consumers need 0.32.1 or later. Read
`references/versions-and-sources.md` when `Cargo.lock` pins `uniffi` below 0.32, or for the
primary UniFFI documentation.

## Scaffolding: proc-macros, no UDL

1. Call `uniffi::setup_scaffolding!()` exactly once, at the top of the crate root (`lib.rs`).
2. Annotate exported functions, `impl` blocks, and traits with `#[uniffi::export]`.
3. Derive `uniffi::Record`, `uniffi::Object`, `uniffi::Enum`, or `uniffi::Error`.
4. Generate Kotlin and Swift from the compiled library of one build.

Do not add a `.udl` file to a proc-macro crate: two declarations of one surface drift.

## Object or Record

| | Object | Record |
|---|---|---|
| Derive | `uniffi::Object` | `uniffi::Record` |
| Foreign form | Opaque reference-counted handle | Kotlin `data class`, Swift `struct` |
| Crossing cost | One handle | Every field, on every call |
| Identity | Kept; the Rust value never moves | None; copied by value |
| Exposed through | Methods | Fields; since 0.31 also methods, on a copy |
| Field rule | Fields stay private to Rust | Every field is a UniFFI type |
| Thread bounds | `Send + Sync` | None |

State and behavior (an engine, a session, anything with interior mutability) are an Object.
Messages and data (a request, a result, an event payload) are a Record.

Do not export a free function that reads hidden global state: put the state in an Object, so
the platform owns its lifetime and a test can create a fresh one.

Read `references/type-mapping.md` when you choose a field or argument type, a custom type, or
a default argument. Read `references/interface-patterns.md` when you shape constructors, a
long-running job, a JSON payload, large data, a trait interface, or the boundary crate.

## `Send + Sync` on every exported Object

UniFFI rejects an Object that is not `Send + Sync`, because Kotlin and Swift call the handle
from any thread. The error names the field type at the derive
([references/interface-patterns.md](references/interface-patterns.md) has the example).

- Hold shared state behind `Mutex`, `RwLock`, or an atomic.
- Keep a type that cannot be `Send + Sync` in a deeper crate behind a `Send + Sync` facade.
- Treat a manual `unsafe impl Sync` as a soundness review item with a `SAFETY` comment.

## Ownership across the boundary

- **`Arc` identity, not bytes.** Returning an Object moves one strong reference into the
  foreign handle; the value drops after the last foreign and Rust owner release it.
- **Kotlin frees a handle deterministically only on `close()`.** Call `close()` or `use { }`
  on an Object that owns files, threads, or large memory; otherwise `Drop` waits for the JVM
  `Cleaner`. Swift frees the handle in `deinit`.
- **Borrowed arguments last for one call.** A top-level `&str`, `&[u8]`, `&Record`, or
  `&Object` argument is valid only during the Rust call: do not store or return it. `&mut T`,
  `Option<&T>`, and nested references do not cross.
- **`&[u8]` becomes a direct `java.nio.ByteBuffer` in Kotlin (0.32).** Kotlin must call
  `flip()` after `put()`, or pass `buf.slice()`, or Rust silently reads the wrong bytes.
  `&[u8]` flows only into Rust, not in an async export or a foreign-trait method. Read
  [references/type-mapping.md](references/type-mapping.md) for the buffer detail.
- **Records are copied.** A large `Vec<T>` field is a per-call cost, not a pointer handoff.
- **Cycles leak.** A foreign object that holds the Rust Object, and a Rust Object that holds
  the foreign callback, form a cycle that no runtime collects.

Do not model an Android `Activity`, a `ViewModel`, a Swift view controller, or a Swift task as
a Rust Object; export engine Objects whose lifetimes are independent of UI owners.

## Errors: the shape rule

The `ffi-error-progress-cancel` skill owns error semantics. This skill enforces two shape
rules:

1. Every fallible export returns `Result<_, E>`, and `E` derives `uniffi::Error`, never a
   sentinel or an out-parameter.
2. No panic reaches the foreign caller. The scaffolding catches an unwind, but Kotlin gets
   `InternalException` and a Swift `throws` function an internal error, both outside the
   declared error type. In a Swift non-throwing function, and anywhere under
   `panic = "abort"`, the process ends. A non-throwing export, such as `cancel_job`, must
   be panic-free by construction (the `rust-panic-safety` skill, when it is installed, owns
   the unwind policy).

Deny `clippy::unwrap_used`, `clippy::panic`, `clippy::unreachable`, and
`clippy::indexing_slicing` in `lib.rs`, and add `#![forbid(unsafe_code)]` when the crate has no
hand-written `unsafe`. The lints miss inner crates and panicking std APIs: keep a
non-throwing export total, or wrap the inner call in `std::panic::catch_unwind`
([references/panic-free-exports.md](references/panic-free-exports.md) has the full set).

## Codegen and bindgen failure triage

The Rust messages below are from Rust 1.99.1 with UniFFI 0.32.2.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `E0425` ``cannot find type `UniFfiTag` in the crate root`` | `setup_scaffolding!()` missing, or in a submodule | Call it once at the top of `lib.rs` |
| `E0428` ``the name `ffi_<crate>_rust_future_...` is defined multiple times`` | `setup_scaffolding!()` is called twice | Remove the second call |
| `E0277` ``… cannot be shared between threads safely`` (or ``sent``) at `derive(uniffi::Object)` | A field is not `Sync` or not `Send` | Put the state behind `Mutex` or an atomic |
| `E0277` ``the trait bound `usize: Lift<UniFfiTag>` is not satisfied`` (also `Lower`, `TypeId`) | The type has no UniFFI mapping | Convert to a mapped type with an explicit `From` |
| `E0277` ``the trait bound `&str: LowerReturn<UniFfiTag>` is not satisfied`` | A borrowed return | Return an owned value or an `Arc` |
| `E0277` `` `*const u8` cannot be sent between threads safely `` naming `ForeignBytes` | `&[u8]` in an async export | Take `Vec<u8>` |
| `E0053` ``method `…` has an incompatible type for trait`` at `#[uniffi::export(foreign)]` | A reference argument in a foreign-trait method | Pass the argument by value |
| `E0405` ``cannot find trait `UniffiCustomTypeConverter` in this scope`` | UniFFI 0.28 code | Use `uniffi::custom_type!` |
| Kotlin bindgen: `Async primary constructors not supported` | `async fn new` under `#[uniffi::constructor]` | Use a named async constructor |
| Async export panics on first poll: `there is no reactor running` | Tokio resources without a Tokio runtime | Add `async_runtime = "tokio"` and the `uniffi` `tokio` feature |
| Kotlin `IllegalArgumentException` about a direct `ByteBuffer`, or Rust gets an empty or short `&[u8]` | A heap buffer, or `put()` without `flip()` | The `&[u8]` section of `references/type-mapping.md` |
| Swift fatal error in a generated non-throwing call | A panic, or a failed custom-type lift, in a non-throwing export | Make it panic-free; declare an error on an export that takes a fallible custom type |
| Generated Swift fails with actor-isolation errors | `SWIFT_DEFAULT_ACTOR_ISOLATION=MainActor` (Swift 6.2+) | Compile it in a module with `nonisolated` default isolation |
| Generated Kotlin and Swift disagree | Generators at different versions, or a leftover `.udl` | Regenerate both from one build |
| Callback never fires on the foreign side | The handle was dropped, or the job already returned | Hold the callback for the job |
| Foreign object leaks after a job | A cycle across the boundary | Do not store the Rust Object in the foreign callback |

## Verify

| Claim | Check | When |
|-------|-------|------|
| The surface compiles | `cargo check -p <boundary-crate>` | While you iterate |
| No unguarded panic site; each kept `.expect` carries `#[expect(clippy::expect_used, reason = "...")]` | `cargo clippy --locked -p <boundary-crate> --all-targets -- -D warnings` | Before merge |
| Behavior and error mapping | `cargo test --locked -p <boundary-crate>`: call the exports directly, implement the callback traits in Rust, assert event order, error variants, and cancel | Every change |
| Error mapping is total | Each `From<InnerError>` matches every variant with no `_` arm | When an inner error enum changes |
| Custom types round trip | A property test that converts to the bridge type and back | A custom type changes |
| Bindings generate | Kotlin and Swift from one build in CI | Every boundary change |

A green clippy run does not prove that an export cannot panic. A green Rust run does not
prove that the generated Kotlin or Swift compiles or that Kotlin flips a direct buffer: only
a platform build and a smoke test on the pinned toolchain prove those.

## Foreign callbacks and listeners

Deliver progress and events through a foreign trait that the platform implements and Rust
calls. Read `references/interface-patterns.md` ("Minimal boundary crate") when you create a
boundary crate or write a foreign trait: it holds the full `ProgressListener` pattern.

- Put `Send + Sync` on the trait, take it as `Arc<dyn Trait>`, and pass every argument by
  value.
- Give every method a `Result<_, CallbackError>` return, where `CallbackError` implements
  `From<uniffi::UnexpectedUniFFICallbackError>`; without it, an undeclared foreign exception
  panics in the generated code. Never discard the callback result.
- Keep the trait coarse: one `on_progress(event)`, not a per-item callback. Coalesce and
  rate-limit in Rust, because a synchronous callback blocks the worker.
- Hold an `Arc<dyn Trait>` for one call or one job; never store one with no release path.

Its "Foreign trait rules" section has the export attributes, the listener-failure mapping,
and the migration away from `callback_interface`.

## Async exports

Prefer synchronous exports that the platform runs off the main thread. An exported
`async fn` must return a `Send` future and be drop-safe at every `.await`: Kotlin coroutine
cancellation drops the future there, and UniFFI sends Rust no cancel signal. Read the "Async
exports" section of `references/interface-patterns.md` when you add one.

## Stability rules for an existing surface

A reshaped export can break both consumers in one commit.

- Prefer a new coarse method, an argument with a generated default, or a wider JSON contract
  validated in Rust over a change of arity.
- Treat an added enum variant as a source break: an exhaustive Kotlin `when` or Swift
  `switch` stops compiling after regeneration.
- Treat a change from `Vec<u8>` to `&[u8]` as a Kotlin source break (`ByteArray` becomes
  `ByteBuffer`).
- Use one UniFFI version, runtime, and bindgen for both platforms.

## Review

Read `references/review-checklist.md` when you review a change to the boundary crate or gate
its merge.
