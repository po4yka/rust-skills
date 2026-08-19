# UniFFI interface patterns

Use this file when you shape an exported Object, a constructor, a callback, or a long-running
operation. Every pattern below assumes the proc-macro path and the rules in the main skill:
exported Objects are `Send + Sync`, nothing borrows across the boundary, and every fallible
export returns `Result`.

## Crate layout

```text
your-ffi-crate/
  Cargo.toml        # crate-type = ["cdylib", "staticlib", "lib"]
  src/
    lib.rs          # uniffi::setup_scaffolding!() — exactly once
    engine.rs       # the exported Object
    records.rs      # request and response Records
    events.rs       # callback traits and event Records
    error.rs        # the uniffi::Error enum and From impls from inner crates
```

Keep the exported surface in files that contain nothing else. A reviewer must be able to read
the whole boundary in one pass. Packaging of the cdylib and staticlib artifacts belongs to
`uniffi-packaging-versioning`.

## The single-handle pattern

Export one Object that owns the process-wide state, and hang the operations off it. One handle
gives you one place for configuration, one place for a cancel registry, and one lifetime the
platform can reason about.

```rust
#[derive(uniffi::Object)]
pub struct Engine {
    version: String,
    jobs: Mutex<HashMap<String, Arc<AtomicBool>>>,
}

#[uniffi::export]
impl Engine {
    #[uniffi::constructor]
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            version: env!("CARGO_PKG_VERSION").to_string(),
            jobs: Mutex::new(HashMap::new()),
        })
    }

    pub fn version(&self) -> String {
        self.version.clone()
    }
}
```

Do not export free functions that hold hidden global state. A `static` behind an exported
function is invisible to the platform, untestable from the platform, and impossible to reset
between tests. Put the state in the Object.

## Constructors

| Case | Shape |
|------|-------|
| Infallible | `#[uniffi::constructor] pub fn new() -> Arc<Self>` |
| Fallible | `#[uniffi::constructor] pub fn new(cfg: Config) -> Result<Arc<Self>, EngineError>` |
| More than one | Give each a distinct name; the generator maps a named constructor to a named factory on the foreign class |

Make the primary constructor infallible when it only allocates. Move anything that can fail —
opening a file, binding a socket, loading a model — into a named fallible constructor or an
explicit `open` method. A foreign caller that must handle an exception from `Engine()` will
write worse code than one that handles it from `Engine.open(path)`.

## Long-running operations with progress and cancel

Combine three pieces: a coarse method, a callback trait, and a cancel token that the caller
can reach without holding a lock on the job.

```rust
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
    pub duration_ms: u64,
}

#[uniffi::export(callback_interface)]
pub trait ProgressListener: Send + Sync {
    fn on_progress(&self, event: ProgressEvent);
}

#[uniffi::export]
impl Engine {
    pub fn run_job(
        &self,
        request: JobRequest,
        listener: Box<dyn ProgressListener>,
    ) -> Result<JobResult, EngineError> {
        let flag = Arc::new(AtomicBool::new(false));
        self.jobs
            .lock()
            .expect("jobs registry poisoned")
            .insert(request.job_id.clone(), Arc::clone(&flag));

        let outcome = self.execute(&request, &*listener, &flag);

        self.jobs
            .lock()
            .expect("jobs registry poisoned")
            .remove(&request.job_id);
        outcome
    }

    pub fn cancel_job(&self, job_id: String) {
        if let Some(flag) = self.jobs.lock().expect("jobs registry poisoned").get(&job_id) {
            flag.store(true, Ordering::Relaxed);
        }
    }
}
```

Points that matter in that shape:

- The registry entry is removed on **every** exit path, including the error path. A leaked
  entry keeps an `Arc` alive and grows the map for the life of the process.
- `cancel_job` is separate from `run_job`, so the platform can cancel from a different thread
  while `run_job` is still blocked.
- The cancel flag is an `AtomicBool`, not a `Mutex<bool>`. The read is on the hot loop. See
  `memory-model` for the ordering argument; `Relaxed` is correct only when the flag alone
  decides, with no other data published through it.
- The two `expect` calls on a poisoned lock are panics inside an exported function. Decide the
  policy deliberately: either make the registry poison-proof, or catch at the boundary. See
  `rust-panic-safety`. Do not leave the decision implicit.

## Callback lifetime

A `Box<dyn ProgressListener>` keeps the foreign object alive for as long as Rust holds it.

- Hold it for one call or one job. Release it when the operation returns.
- Do not store the listener inside the Object for the life of the process. That is a leak the
  platform cannot see and cannot break.
- Do not let the foreign implementation of the listener hold a strong reference back to the
  Rust Object while the Rust Object holds the listener. That cycle is not collectable from
  either side.
- Assume the foreign implementation can be slow. A synchronous callback into Kotlin or Swift
  blocks the Rust worker thread. Coalesce events before you emit.

## Boundary crossing cost

Order of magnitude, cheapest first:

1. A method call on an Object with scalar arguments.
2. A method call with a small Record.
3. A callback from Rust into the foreign runtime — more expensive than a call in, because it
   re-enters the foreign runtime and may need to attach a thread.
4. A Record with a large `Vec` field, in either direction.
5. A byte buffer of any real size.

Design consequences:

- Batch. One call that returns `Vec<Summary>` beats N calls that each return one `Summary`.
- Emit progress on a time or percentage threshold, not per item.
- Return a path, not bytes, for anything over a few kilobytes.
- Never put a boundary crossing inside a loop written on the foreign side. If a platform
  developer must write `for (x in items) engine.process(x)`, the missing API is
  `engine.processAll(items)`.

## Trait interfaces versus Objects

Two ways exist to hand the foreign side something callable:

| You want | Use |
|----------|-----|
| A concrete Rust type with methods | `#[derive(uniffi::Object)]` |
| A Rust trait with more than one Rust implementation, selected at runtime | An exported trait interface |
| A trait the foreign side implements and Rust calls | `#[uniffi::export(callback_interface)]`, taken as `Box<dyn Trait>` |
| A trait either side may implement, or that must be shared | `#[uniffi::export(with_foreign)]`, taken as `Arc<dyn Trait>` |

Do not reach for a trait interface when there is one implementation. An Object is simpler to
generate, simpler to read, and simpler to version. See `rust-discipline`.

## Async exports

Prefer synchronous exports plus a platform-side dispatcher. When you do export `async fn`:

- The future must be `Send`. A future that holds a `!Send` value across an await point does not
  cross.
- An async export that needs a reactor — timers, sockets, or any Tokio-driven resource —
  needs the runtime declared on the export. Check the futures documentation for your pinned
  UniFFI version for the exact attribute, because this has changed across versions.
- Cancellation of an async export is not automatic and is not the same as dropping the foreign
  task. Keep the explicit cancel token pattern above even when the method is `async`.
- Do not mix: an operation that reports progress through a callback and also returns a future
  gives the platform two completion signals to reconcile. Pick one.

## Testing the boundary

- Unit test the boundary crate in Rust. Exported functions are ordinary Rust functions; call
  them directly from `#[test]` and assert on the Records.
- Implement the callback traits in Rust inside the test to check the event sequence and the
  cancel behaviour without any foreign runtime.
- Property test every custom type for a lossless round trip.
- Assert that error mapping is total: a test that matches every inner-crate error variant and
  checks it maps to a boundary variant fails to compile when someone adds a variant, which is
  the point.
- Generate the bindings in CI on every change to the boundary crate. A change that breaks
  codegen must fail before it reaches a platform build. See `cargo-workflows`.
