---
name: uniffi-boundary
description: Use when you author, change, or review a UniFFI boundary that generates Kotlin and Swift bindings from Rust. Covers proc-macro scaffolding versus UDL, Record/Object/Enum/Error derives, Send + Sync, Arc ownership, callback_interface and foreign traits, custom_newtype converters, versioned JSON payloads, coarse APIs, async exports, and mobile engine and callback ownership shape. Triggers on uniffi, uniffi::export, uniffi::constructor, setup_scaffolding, uniffi-bindgen, UDL, callback_interface, with_foreign, custom_newtype, foreign trait, or what may cross an FFI boundary.
license: BSD-3-Clause
---

# UniFFI Boundary

## Purpose

Use this skill to design, author, and review a UniFFI boundary crate. A UniFFI boundary
crate is a thin adapter: it declares the exported surface, and one bindings generator
produces the Kotlin and the Swift side from the same Rust signatures.

This skill owns the *shape* of that surface:

- proc-macro scaffolding and the single-source-of-truth rule,
- the Record versus Object decision,
- `Send + Sync` on every exported interface,
- `Arc`-based object references and ownership,
- foreign callback traits,
- custom-type converters and JSON-string contracts,
- what is allowed to cross the boundary and what must stay in deeper crates.

This skill does **not** own the error, progress, and cancellation *semantics* — the error
variant taxonomy, forward-compatible catch-all variants, progress mapping to Kotlin `Flow`
or Swift `AsyncThrowingStream`, and cooperative cancel. Those are `ffi-error-progress-cancel`.
It does not own packaging of the generated artifacts — cdylib, staticlib, XCFramework, and
version skew. That is `uniffi-packaging-versioning` and `rust-android-build`. The atomics
under a cancel flag are `memory-model`. Unsafe blocks and FFI safety invariants are
`rust-unsafe`. Unwind policy is `rust-panic-safety`. General API-shape discipline is
`rust-discipline`.

## When to use

- You add, remove, or change any `#[uniffi::export]` function, method, or trait.
- You must decide whether a type is a UniFFI **Record** (by value, fields cross) or an
  **Object** (opaque, behind `Arc`, methods cross).
- You wire a foreign callback or listener that the platform implements and Rust calls.
- You must pass a complex or versioned payload across the boundary and choose a
  representation — JSON string versus exploded typed Record.
- You review a change to the FFI surface for `Send + Sync`, `Arc`, panic, or fat-boundary
  violations.
- You triage a UniFFI codegen error about missing trait bounds, non-`Send` types, or an
  unsupported signature.

## Canonical sources

Read the docs for the UniFFI version pinned in your lockfile. The surface changes between
minor versions.

| Topic | URL |
|-------|-----|
| Proc-macro guide: `#[uniffi::export]`, derives, `setup_scaffolding!` | <https://mozilla.github.io/uniffi-rs/latest/proc_macro/index.html> |
| Interfaces (Objects): opaque types, `Arc`, methods, constructors | <https://mozilla.github.io/uniffi-rs/latest/types/interfaces.html> |
| Object references: how `Arc` handles cross, lifecycle and ownership | <https://mozilla.github.io/uniffi-rs/latest/internals/object_references.html> |
| Custom types: `custom_type!` and newtype passthrough | <https://mozilla.github.io/uniffi-rs/latest/types/custom_types.html> |
| Async and futures: exporting `async fn` | <https://mozilla.github.io/uniffi-rs/next/futures.html> |
| Foreign traits and callback interfaces | <https://mozilla.github.io/uniffi-rs/latest/types/interfaces.html#exposing-traits-as-interfaces> |

## Scaffolding: proc-macro first, no UDL

Use the **proc-macro** path exclusively for a new boundary crate:

1. Call `uniffi::setup_scaffolding!()` **exactly once**, in the crate root (`lib.rs`).
2. Annotate exported functions, methods, and traits with `#[uniffi::export]`.
3. Annotate exported types with `#[derive(uniffi::Record)]`, `#[derive(uniffi::Object)]`,
   `#[derive(uniffi::Enum)]`, or `#[derive(uniffi::Error)]`.
4. Generate bindings with `uniffi-bindgen` against the compiled library, not against a
   hand-written interface file.

Do **not** add a `.udl` file to a proc-macro crate. Two declarations of the same surface
drift. The Rust signatures must be the single source of truth so the generated Kotlin and
the generated Swift stay in lockstep.

Duplicate `setup_scaffolding!()` calls, or a missing call, produce confusing link and
codegen failures rather than a clear error. Check the crate root first when the symbol
table looks wrong.

## Object versus Record: the core decision

| | Object | Record |
|---|---|---|
| Derive | `#[derive(uniffi::Object)]` | `#[derive(uniffi::Record)]` |
| Foreign representation | Opaque handle, reference counted | Plain data class or struct |
| Crossing cost | Pointer, once | Every field, every call |
| Identity | Preserved; the Rust value never moves | None; copied by value |
| Exposed through | Its methods | Its fields |
| Field requirement | Fields are private to Rust | Every field must itself be a UniFFI type |
| Bounds | Must be `Send + Sync` | No thread bounds needed |

Rule of thumb: **state and behavior are an Object; messages and data are a Record.**

An engine handle, a session, a connection pool, or anything with interior mutability is an
Object. A request, a result, a summary, or an event payload is a Record.

```rust
#[derive(uniffi::Object)]
pub struct Engine {
    // version metadata, plus a per-job cancel registry behind a Mutex
}

#[uniffi::export]
impl Engine {
    #[uniffi::constructor]
    pub fn new() -> Arc<Self> {
        // Infallible: building the handle allocates no external resource.
        Arc::new(Self { /* … */ })
    }

    pub fn inspect(&self, path: String) -> Result<Inspection, EngineError> { /* … */ }
}

#[derive(uniffi::Record)]
pub struct Inspection {
    pub name: String,
    pub size_bytes: u64,
    pub warnings: Vec<String>,
}
```

A constructor returns `Arc<Self>` when it is infallible. Fallible methods take `&self` and
return `Result<_, E>`. The foreign side receives a reference-counted handle, never the Rust
struct's bytes.

## `Send + Sync` on every exported Object

UniFFI requires an exported Object to be `Send + Sync`, because the foreign handle can be
used from any thread. Android code calls it from a background dispatcher; Swift code calls
it off the main actor.

Follow these rules:

- Hold shared state in `Arc<…>` plus interior synchronization: `Mutex`, `RwLock`, or
  lock-free atomics for a flag such as cancel. See `memory-model` for ordering choices.
- Never expose a `Cell`, `RefCell`, `Rc`, raw pointer, or any `!Sync` field through an
  exported Object.
- If a type cannot be `Send + Sync`, it does **not** belong at the boundary. Keep it in a
  deeper crate and expose a `Send + Sync` façade.

A missing bound shows up as a codegen or trait-bound error at the `#[uniffi::export]` site,
not at the call site. Read the error against the struct, not against the method.

## Ownership across the boundary

- **`Arc` identity, not bytes.** Returning an Object hands the caller an `Arc` handle. The
  Rust value never moves and is never copied. The foreign object holds one strong reference;
  the Rust side keeps its own. The value drops when both sides release it.
- **No borrows cross.** UniFFI has no borrow model. Do not put `&T`, `&mut T`, or a lifetime
  parameter in an exported signature. Return an owned Record, or an `Arc` handle to an Object.
  The one exception is the `&self` receiver of an exported method, which the generator turns
  into a call on the foreign handle.
- **Records are copied.** Every Record field is serialized on every call. A large `Vec<T>`
  field is a per-call cost, not a pointer handoff.
- **Foreign objects are owned by the foreign side.** A callback object passed into Rust is
  kept alive by the handle Rust holds. Drop that handle when the job ends, or the foreign
  object leaks.
- **Reference cycles cross the boundary.** A foreign object that holds the Rust Object, and
  a Rust Object that holds the foreign callback, form a cycle that no runtime collects. Break
  it: hold the callback for the duration of one call or one job, then release it.

### Mobile ownership shape

- Export engine Objects whose lifetimes are independent of UI owners. Multiple
  engine Objects can hold isolated state and share one process execution provider. Do not
  model an Android `Activity`, a `ViewModel`, a Swift view controller, or a Swift task as a
  Rust Object.
- Choose one execution model. Either export synchronous methods that the host runs on its
  worker scheduler, or use one shared runtime or executor provider for the process. Never
  create a runtime for each engine, call, screen, or job.
- Make process runtime or provider initialization idempotent. Keep engine construction
  instance-scoped. Mobile process death can skip every shutdown and destructor path.
- Give a stored callback registration a unique token or generation. Release it with an
  idempotent, non-blocking method. Do not expose a blocking `shutdown` or `join` method for a
  UI owner to call from `onCleared` or `deinit`.
- Keep UI-thread delivery, owner teardown, background deadlines, low-memory handling, and
  callback release races in `ffi-error-progress-cancel`.

## Foreign callbacks and listeners

Deliver progress and events through a **callback interface** that the platform implements and
Rust calls. Declare the trait once and take it as a parameter.

```rust
#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum ProgressCallbackError {
    #[error("foreign progress callback failed")]
    Unexpected,
}

impl From<uniffi::UnexpectedUniFFICallbackError> for ProgressCallbackError {
    fn from(_: uniffi::UnexpectedUniFFICallbackError) -> Self {
        Self::Unexpected
    }
}

#[uniffi::export(callback_interface)]
pub trait ProgressListener: Send + Sync {
    fn on_progress(&self, event: ProgressEvent) -> Result<(), ProgressCallbackError>;
}

#[uniffi::export]
impl Engine {
    pub fn run_job(
        &self,
        request: JobRequest,
        listener: Box<dyn ProgressListener>,
    ) -> Result<JobResult, EngineError> {
        listener
            .on_progress(ProgressEvent::started(&request))
            .map_err(EngineError::from)?;
        self.execute(request, listener)
    }
}
```

`ProgressCallbackError` is a `#[derive(uniffi::Error)]` boundary type. Its
`From<UnexpectedUniFFICallbackError>` implementation converts an undeclared
foreign exception into `Err` instead of letting UniFFI panic. Also implement an
exhaustive `From<ProgressCallbackError> for EngineError`. The generated foreign
method translates a declared platform error into that `Result` channel, and
`run_job` decides whether to stop, retry, or degrade. Do not use a unit-return
callback and assume that a Kotlin or Swift implementation cannot throw.

Two forms exist. Choose one and use it consistently:

| Form | Rust parameter type | Use it when |
|------|--------------------|-------------|
| `#[uniffi::export(callback_interface)]` | `Box<dyn Trait>` | The implementation is always foreign |
| `#[uniffi::export(with_foreign)]` | `Arc<dyn Trait>` | The implementation may be Rust **or** foreign, or you must share it |

Rules for callback traits:

- Add `Send + Sync` to the trait. Rust calls it from a worker thread, not from the thread
  that made the FFI call.
- Keep the trait **coarse**. One `on_progress(Event)` method, not a chatty per-item callback.
  Every call crosses the FFI and re-enters the foreign runtime; a per-pixel or per-row
  callback dominates the work it reports on.
- Coalesce and rate-limit inside Rust before you call out.
- Give every callback method a `Result<_, CallbackError>` return. The foreign
  implementation can throw. Map the callback error into the exported
  operation's typed error before it leaves Rust. Decide retry or degradation
  policy in `ffi-error-progress-cancel`; this skill fixes the error channel.

The mapping of these events to Kotlin `Flow` or Swift `AsyncThrowingStream` belongs to
`ffi-error-progress-cancel`.

## Versioned payloads cross as JSON strings

When a payload is a versioned shared contract that both platforms and Rust agree on, pass it
across the boundary as a JSON `String`, not as an exploded UniFFI Record.

Why:

- The FFI signature stays stable across contract versions. Adding a field to the contract
  never reshapes the generated Kotlin or Swift and never breaks the ABI.
- One validator. Rust owns `deserialize → validate → execute`, so both platforms get
  byte-identical behavior.
- The contract can be versioned, migrated, and tested independently of the binding
  generation.

Rules:

- Validate and deserialize **inside** Rust with `serde`. Return a typed error variant for a
  malformed or invalid payload.
- Do **not** parse the JSON on the platform side to "help". Validation lives behind the
  boundary. A platform-side parser is a second implementation that will disagree.
- Use this for complex, evolving, nested specs. Do **not** use it for a small fixed payload —
  a three-field Record is clearer and cheaper than a JSON round trip.

Give the string a distinct foreign type name with a custom newtype when you want the
generated API to be self-documenting:

```rust
pub struct SpecJson(pub String);

uniffi::custom_newtype!(SpecJson, String);
```

For a type that needs real conversion logic rather than a transparent newtype, implement the
custom-type converter form. See `references/type-mapping.md`.

## Coarse boundary, large data by path

The boundary is **coarse**. Expose whole operations, not fine-grained getters.

- Good: `inspect(path)`, `render_preview(request)`, `run_job(request, listener)`,
  `cancel_job(id)`.
- Bad: `get_width()`, `get_height()`, `get_pixel(x, y)`, `set_option(key, value)` — each one
  is a full boundary crossing plus a foreign runtime transition.

Move large data by **file path or URL string**, not by byte array:

- Never pass a raw `Vec<u8>` pixel buffer, decoded image, or multi-megabyte blob across the
  boundary. It is copied on every crossing and it doubles peak memory.
- Write the output file in Rust and return a small Record that describes it: output path,
  byte size, and any summary metadata the caller needs.
- Small `Vec<u8>` payloads — a hash, a signature, a short header — are fine.

## Thin adapter: what belongs in the boundary crate

The boundary crate is an adapter, not a place where work happens. It contains:

- request and response Records,
- the exported Object or Objects,
- the callback traits,
- error type and error mapping from inner crate errors,
- `setup_scaffolding!()`.

It contains **no** domain computation, parsing, rendering, or I/O logic. Those stay in the
inner crates. If a change adds real computation to the boundary crate, the change is in the
wrong crate.

Dependency direction is one way: the boundary crate depends on the inner crates. No inner
crate depends on the boundary crate, and no inner crate calls a platform API. See
`rust-crate-architecture`.

## Async surface

Prefer **synchronous** exported methods that the platform runs off the main thread, bridged
to `Flow` or `AsyncSequence` through the progress callback. This keeps the generated API
small and keeps the threading policy on the platform side, where the scheduler lives.

If you do export `async fn`:

- Keep the same `Send + Sync` and JSON-string rules. Async changes nothing about the shape
  rules.
- Do not split one contract into many fine-grained awaitable calls. The awaitable version of
  a chatty API is still chatty.
- The returned future must be `Send`. A `!Send` future does not cross.
- Check the futures documentation for your pinned UniFFI version before you add the first
  `async fn`; the async export attributes have changed across versions.

## Errors: the shape rule

Full error semantics belong to `ffi-error-progress-cancel`. Two rules are enforced **here**,
because they are shape rules:

1. **Every fallible exported function returns `Result<_, E>`** where `E` is a
   `#[derive(uniffi::Error)]` type. There is no other channel. A sentinel return value or an
   out-parameter is not acceptable.
2. **No panic reaches the foreign caller.** The generated scaffolding catches an unwind and
   reports it as an internal error, outside your `#[derive(uniffi::Error)]` enum. The foreign
   caller gets an opaque failure that it cannot match on, and the state after the panic is not
   defined. A crate built with `panic = "abort"` kills the process instead. Convert every
   failure into an error variant at the boundary, and catch what you cannot convert. See
   `rust-panic-safety` for the unwind policy and the abort profile choice.

Audit for the usual panic sources in exported code paths: `unwrap`, `expect`, slice indexing,
integer division, `Mutex` poisoning propagated by `lock().unwrap()`, and arithmetic overflow
in a debug build.

## Codegen failure triage

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Trait-bound error naming `Send` or `Sync` at an `#[uniffi::export]` site | The Object holds a `!Send` or `!Sync` field | Move the field behind `Arc<Mutex<…>>`, or keep the type out of the boundary crate |
| "not supported" or unknown-type error on a Record field | The field type has no UniFFI mapping | Convert it to a UniFFI type in an explicit `From` impl; do not leak inner-crate types |
| Lifetime or borrow error on an exported signature | You tried to export `&T`, `&mut T`, or a lifetime parameter | Return an owned Record or an `Arc` handle |
| Undefined or duplicate scaffolding symbols at link time | `setup_scaffolding!()` missing, or called more than once | Call it exactly once, in the crate root |
| Generated Kotlin and Swift disagree, or one is stale | Two generator runs at different crate versions, or a leftover `.udl` | Regenerate both from the same build; delete the `.udl`; see `uniffi-packaging-versioning` |
| Callback method never fires on the foreign side | The handle was dropped, or the call happens after the job returned | Hold the callback for the job duration; release it deterministically |
| Foreign object leaks after a job | Reference cycle across the boundary | Break the cycle: do not store the Rust Object inside the foreign callback implementation |
| Runtime crash on the first call from a background thread | Object is not truly thread safe despite the bounds | Audit interior mutability; a manual `unsafe impl Sync` is a `rust-unsafe` review item |

## Stability rules for an existing surface

Reshaping an exported function regenerates Kotlin *and* Swift, and can break both consumers
in the same commit. Before you change a signature:

- Prefer **adding** a new coarse method over changing the arity of an existing one.
- Prefer **widening the JSON contract**, validated in Rust, over adding a parameter.
- Keep enum variants additive. Removing or reordering a variant is a breaking change for both
  generated bindings.
- Use one UniFFI version for both platforms. The `uniffi` crate, the runtime, and the bindgen
  must match. Skew ownership is `uniffi-packaging-versioning`, but a boundary review must flag
  any per-platform divergence it sees.

## Review checklist

Answer every item before you merge a change to the boundary crate.

1. Is `setup_scaffolding!()` present exactly once, in the crate root?
2. Is there a `.udl` file in a proc-macro crate? Delete it.
3. Is every exported Object `Send + Sync` without a manual `unsafe impl`?
4. Does any exported Object hold a `Cell`, `RefCell`, `Rc`, or raw pointer?
5. Is every new type on the correct side of the Record/Object line — state and behavior are
   an Object, data is a Record?
6. Is every Record field itself a UniFFI type, with no inner-crate type leaking through?
7. Does any exported signature contain `&T`, `&mut T`, or a lifetime parameter, apart from the
   `&self` receiver?
8. Does every fallible exported function return `Result<_, E>` with a `uniffi::Error` type?
9. Can any exported path panic? Grep the new code for `unwrap`, `expect`, and
   `lock().unwrap()`.
10. Does any exported function pass a large `Vec<u8>` or byte array? Move it to a file path.
11. Is the new method coarse — a whole operation — or is it a getter that will be called in a
    loop?
12. Does every callback trait declare `Send + Sync`, return `Result` with a
    UniFFI error type, and stay coarse enough to not dominate the work it
    reports?
13. Is the callback handle released when the job ends? Is there a cycle across the boundary?
14. Does a job registry reject duplicate IDs without replacing an active entry,
    and does an RAII guard remove the entry on success, error, and unwind?
15. Does the change add real computation to the boundary crate instead of an inner crate?
16. Does an inner crate now depend on the boundary crate? Reverse it.
17. Does the change reshape an existing exported signature? Can it be an added method or a
    widened JSON contract instead?
18. Are enum and error variant changes additive?
19. Were both the Kotlin and the Swift bindings regenerated from the same build in this
    change?
20. Does a new `async fn` return a `Send` future, and does the pinned UniFFI version support
    the export form used?
21. Does any new custom type round trip losslessly in both directions?
22. Do all engine Objects use the host scheduler or one shared process runtime or provider,
    rather than a runtime per engine, call, or UI owner?
23. Is runtime or provider initialization idempotent after process death without forcing all
    product state into one engine singleton?
24. Can a UI owner release every stored callback without blocking its main thread or
    destructor?

If the answer to any item is wrong, revise the change before you merge it.

## References

| File | Contents |
|------|----------|
| `references/type-mapping.md` | Built-in type mapping to Kotlin and Swift, Option/Vec/HashMap rules, custom types and newtype converters, and what has no mapping |
| `references/interface-patterns.md` | Object lifecycle, constructor and factory patterns, callback and cancel-handle shapes, and boundary-crossing cost patterns |

## Related skills

| Skill | Use it for |
|-------|------------|
| `ffi-error-progress-cancel` | Error taxonomy, progress delivery, and cooperative cancellation semantics |
| `uniffi-packaging-versioning` | cdylib and staticlib packaging, XCFramework, and version skew |
| `rust-android-build` | Android target builds, JNI libs layout, and NDK toolchain |
| `rust-jni` | Hand-written JNI when UniFFI is not the right tool |
| `rust-unsafe` | FFI safety invariants, manual `Send`/`Sync` impls, and raw pointers |
| `rust-panic-safety` | Unwind policy, `catch_unwind`, and abort profiles |
| `memory-model` | Atomics and orderings behind cancel and progress flags |
| `rust-discipline` | General API-shape discipline |
| `rust-crate-architecture` | Crate splits, dependency direction, and visibility |
| `rust-observability` | Tracing and logging across a boundary crate |
| `cargo-workflows` | Workspace layout, cross-compilation, and target management |
