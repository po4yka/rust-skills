# UniFFI interface patterns

Use this file when you start a boundary crate or shape an exported Object, a constructor, a
long-running operation, an async export, a payload, or a trait interface. Every pattern assumes the proc-macro path and the rules in
[SKILL.md](../SKILL.md): exported Objects are `Send + Sync`, no borrow outlives the call, and
every fallible export returns `Result`.

Contents: Minimal boundary crate; Crate layout and thin adapter; Constructors; Long-running
operations with progress and cancel; Async exports; Versioned payloads cross as JSON strings;
Coarse boundary and crossing cost; Large data by path; Trait interfaces versus Objects.

## Minimal boundary crate

This block is a complete crate root. It compiles against UniFFI 0.32. Its `EngineError` and
two-field `ProgressEvent` are minimal. The `ffi-error-progress-cancel` skill owns the full
error taxonomy and the three-field event (`job_id`, `stage`, `fraction`). It is the single
full copy of the `ProgressListener` callback pattern in the catalog.

```rust
// src/lib.rs of the boundary crate. A real crate splits `engine` into files.
uniffi::setup_scaffolding!();

mod engine {
    use std::sync::Arc;

    #[derive(Debug, thiserror::Error, uniffi::Error)]
    pub enum EngineError {
        #[error("invalid spec: {reason}")]
        InvalidSpec { reason: String },
        #[error("unexpected engine failure")]
        Unexpected,
    }

    #[derive(uniffi::Record)]
    pub struct JobRequest {
        pub job_id: String,
        pub spec_json: String,
        pub output_path: String,
    }

    #[derive(uniffi::Record)]
    pub struct JobResult {
        pub output_path: String,
        pub byte_size: u64,
    }

    #[derive(uniffi::Record)]
    pub struct ProgressEvent {
        pub job_id: String,
        pub fraction: f64,
    }

    #[derive(Debug, thiserror::Error, uniffi::Error)]
    pub enum ProgressCallbackError {
        #[error("foreign progress callback failed")]
        Unexpected,
    }

    // An undeclared Kotlin or Swift exception becomes `Err`, not a Rust panic.
    impl From<uniffi::UnexpectedUniFFICallbackError> for ProgressCallbackError {
        fn from(_: uniffi::UnexpectedUniFFICallbackError) -> Self {
            Self::Unexpected
        }
    }

    impl From<ProgressCallbackError> for EngineError {
        fn from(err: ProgressCallbackError) -> Self {
            match err {
                ProgressCallbackError::Unexpected => Self::Unexpected,
            }
        }
    }

    #[uniffi::export(foreign)]
    pub trait ProgressListener: Send + Sync {
        fn on_progress(&self, event: ProgressEvent) -> Result<(), ProgressCallbackError>;
    }

    #[derive(uniffi::Object)]
    pub struct Engine {
        version: String,
    }

    #[uniffi::export]
    impl Engine {
        // Infallible: it opens no file, socket, or model.
        #[uniffi::constructor]
        pub fn new() -> Arc<Self> {
            Arc::new(Self { version: env!("CARGO_PKG_VERSION").to_owned() })
        }

        pub fn version(&self) -> String {
            self.version.clone()
        }

        pub fn run_job(
            &self,
            request: JobRequest,
            listener: Arc<dyn ProgressListener>,
        ) -> Result<JobResult, EngineError> {
            let started = ProgressEvent { job_id: request.job_id.clone(), fraction: 0.0 };
            listener.on_progress(started)?;
            todo!("validate spec_json in Rust, then call the inner crate")
        }
    }
}
```

## Crate layout and thin adapter

```text
your-ffi-crate/
  Cargo.toml        # keep the default lib; packaging selects cdylib/staticlib
  src/
    lib.rs          # uniffi::setup_scaffolding!() once, and the clippy lint set
    engine.rs       # the exported Object
    records.rs      # request and response Records
    events.rs       # callback traits and event Records
    error.rs        # the uniffi::Error enums and From impls from inner crates
```

Keep the exported surface in files that contain nothing else. A reviewer must be able to read
the whole boundary in one pass. The `uniffi-packaging-versioning` skill owns the cdylib and
staticlib artifacts.

The boundary crate contains request and response Records, the exported Objects, the callback
traits, the boundary error type with its `From` impls from inner-crate errors, and
`setup_scaffolding!()`. It contains no domain computation, parsing, rendering, or I/O. If a
change adds real computation to the boundary crate, move it to an inner crate.

The boundary crate depends on the inner crates. No inner crate depends on the boundary crate
or calls a platform API.

## Constructors

| Case | Shape |
|------|-------|
| Infallible | `#[uniffi::constructor] pub fn new() -> Arc<Self>`, or `-> Self` |
| Fallible | `#[uniffi::constructor] pub fn open(path: String) -> Result<Arc<Self>, EngineError>` |
| More than one | Give each a distinct name. The generator maps a named constructor to a named factory on the foreign class. |
| Async | Only a named constructor. Kotlin and Python bindgen reject an async primary constructor (`new`). |
| Default argument | `#[uniffi::constructor(default(size = 4))]`; see `type-mapping.md` |

Make the primary constructor infallible when it only allocates. Move anything that can fail,
such as opening a file, binding a socket, or loading a model, into a named fallible
constructor. A foreign caller handles an error from `Engine.open(path)` more clearly than an
exception from `Engine()`.

## Long-running operations with progress and cancel

Combine three pieces:

1. A coarse method, such as `run_job(request, listener) -> Result<JobResult, EngineError>`.
2. A foreign callback trait. The minimal crate at the top of this file has the full
   `ProgressListener` pattern.
3. A separate `cancel_job(&self, job_id: String)` that the platform calls from another thread
   while `run_job` blocks. It reaches the job's cancel flag without holding a lock on the job.

The `ffi-error-progress-cancel` skill owns the job registry design: reservation before launch,
pre-cancel, duplicate rejection, a TTL for abandoned reservations, and RAII removal. Two rules
come from the UniFFI boundary itself:

- `cancel_job` has no `Result`, so a panic in it ends a Swift app with a fatal error. Recover
  lock poison with `PoisonError::into_inner` in every non-throwing export. Do the same in a
  `Drop` that removes a registry entry: a second panic during unwinding aborts the process.
- The cancel flag is an `AtomicBool`, not a `Mutex<bool>`, because the worker reads it on
  the hot loop. `Relaxed` is correct only when the flag alone decides and publishes no other
  data. The `memory-model` skill has the ordering argument.

## Async exports

Prefer synchronous exports that the platform runs off the main thread, with progress through
the callback. The threading policy then stays on the platform side, where the scheduler
lives. When you export an `async fn`:

- The returned future must be `Send`.
- A future that uses a Tokio timer, socket, or `spawn` needs
  `#[uniffi::export(async_runtime = "tokio")]` and the `tokio` feature of `uniffi`. Without
  it, the crate compiles, and the first poll panics with `there is no reactor running, must be
  called from the context of a Tokio 1.x runtime`.
- The attribute runs Tokio resources on the fallback runtime of `async-compat`: one
  current-thread runtime on one dedicated thread, separate from any runtime the crate builds.
  `tokio::spawn` tasks from the export share that thread, and `block_in_place` panics there.
  When the crate owns a process runtime, spawn the work onto its `Handle` and await the
  `JoinHandle`. That needs no `async_runtime` attribute.
- Do not make the primary constructor (`new`) async. Kotlin and Python bindgen fail with
  `Async primary constructors not supported`. Use a named async constructor.
- UniFFI sends no cancel signal to Rust. Kotlin coroutine cancellation drops the Rust future
  at its current `.await`, and a Swift `Task` runs it to completion. Make every `.await`
  point drop-safe (RAII cleanup) and keep an explicit cancel method. The
  `ffi-error-progress-cancel` skill owns the details.
- Generated Swift async code does not conform to `Sendable`. Expect strict-concurrency
  diagnostics in the Swift consumer.
- Signal completion through one channel. Do not complete the job through the callback and
  the future at the same time.

## Versioned payloads cross as JSON strings

Pass a versioned, nested, evolving contract that Rust and both platforms share as a JSON
`String`, not as an exploded Record.

- The FFI signature stays stable across contract versions. A new contract field does not
  reshape the generated Kotlin or Swift.
- Rust owns deserialize, validate, execute. Both platforms get identical behavior.
- Deserialize and validate with `serde` inside Rust. Return a typed error variant for a
  malformed or invalid payload.
- Do not parse the JSON on the platform side. A second parser disagrees with the first.
- Use a Record for a small fixed payload. A three-field Record is clearer and cheaper than a
  JSON round trip.

Give the string a distinct foreign type name with `uniffi::custom_newtype!(SpecJson, String);`.
`type-mapping.md` has the converter form for a type that needs real conversion.

## Coarse boundary and crossing cost

Expose whole operations, not fine-grained getters.

- Good: `inspect(path)`, `render_preview(request)`, `run_job(request, listener)`,
  `cancel_job(id)`.
- Bad: `get_width()`, `get_pixel(x, y)`, `set_option(key, value)`. Each one is a full
  boundary crossing and a foreign runtime transition.

Order of magnitude, cheapest first:

1. A method call on an Object with scalar arguments.
2. A method call with a small Record.
3. A callback from Rust into the foreign runtime. It costs more than a call in, because it
   re-enters the foreign runtime and can attach a thread.
4. A Record with a large `Vec` field, in either direction.
5. A byte buffer of any real size, except a `&[u8]` argument, which is not copied.

Design consequences:

- Batch. One call that returns `Vec<Summary>` beats N calls that each return one `Summary`.
- Emit progress on a time or percentage threshold, not per item.
- Do not put a boundary crossing inside a loop on the foreign side; each iteration pays a full
  crossing. If a platform developer must write `for (x in items) engine.process(x)`, the
  missing API is `engine.processAll(items)`.

## Large data by path

Move large data by file path or URL string:

- Do not return a decoded image or a multi-megabyte `Vec<u8>`. It is copied on every
  crossing, and it doubles peak memory.
- Write the output file in Rust. Return a small Record with the path, the byte size, and the
  summary the caller needs.
- For a large input buffer that the platform already holds, a `&[u8]` argument avoids the
  copy. Kotlin callers then pass a direct `ByteBuffer` at position 0.
- A small `Vec<u8>`, such as a hash, a signature, or a short header, is fine.

## Trait interfaces versus Objects

| You want | Use |
|----------|-----|
| A concrete Rust type with methods | `#[derive(uniffi::Object)]` |
| A Rust trait with more than one Rust implementation, selected at runtime | `#[uniffi::export] trait`, taken and returned as `Arc<dyn Trait>` |
| A trait the foreign side implements and Rust calls | `#[uniffi::export(foreign)]`, taken as `Arc<dyn Trait>` |
| A trait either side may implement | `#[uniffi::export(rust, foreign)]`, taken as `Arc<dyn Trait>` |

Do not export a trait interface for one implementation. An Object is simpler to generate,
to read, and to version.

`callback_interface` is the older `Box<dyn Trait>` form and is soft-deprecated.
`with_foreign` is a deprecated alias for `rust, foreign`, and 0.32 accepts it without a
warning. Do not add either to new code. Keep them only in a surface that you migrate, or on a
crate pinned below 0.32, where `with_foreign` is the only spelling.
