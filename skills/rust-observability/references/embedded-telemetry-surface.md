# The Embedded Telemetry Surface

This reference expands the queue, snapshot, and crash sections in `SKILL.md`. It
applies when a Rust library runs inside a host process — a mobile application, a
game engine, a daemon plugin — and the host reads telemetry across a boundary.

## Why the shape differs from a server

- A boundary crossing per event is a measurable cost. On Android a JNI call into
  the platform logger costs roughly a microsecond with no arguments and roughly
  three with formatted arguments. At a million items per second that is the
  whole budget.
- Several consumers want the same stream: a UI, a golden-test harness, an
  exporter. The channel choice decides whether a slow consumer blocks the
  producer.
- The host can kill the process at any moment. A low-memory killer needs no
  warning. Any "exactly once" delivery assumption is wrong. Design for loss and
  report the loss.
- Privacy rules constrain what may be emitted at all, before performance is even
  a question.

## The bounded event ring

One ring per domain. Each ring owns an atomic bounded queue and a drop counter.

```rust
use core::sync::atomic::{AtomicU64, Ordering};
use crossbeam_queue::ArrayQueue;

pub struct Record;

pub struct EventRing {
    queue: ArrayQueue<Record>,
    dropped: AtomicU64,
}

impl EventRing {
    pub fn with_capacity(capacity: usize) -> Self {
        assert!(capacity > 0, "event ring capacity must be non-zero");
        Self {
            queue: ArrayQueue::new(capacity),
            dropped: AtomicU64::new(0),
        }
    }

    /// Takes no mutex and never sleeps. On a full ring the oldest record is
    /// evicted. Call from task context, not an interrupt or signal handler.
    pub fn push(&self, record: Record) {
        // `force_push` atomically inserts the new record and returns the oldest
        // record only when the queue was full. A concurrent drain cannot split
        // eviction from insertion.
        if self.queue.force_push(record).is_some() {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn drain(&self) -> Vec<Record> {
        std::iter::from_fn(|| self.queue.pop()).collect()
    }

    pub fn dropped(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }
}
```

Invariants to preserve if you change the implementation:

1. The capacity bound holds.
2. Retained records keep FIFO order.
3. A full ring drops the oldest, not the newest.
4. Every drop increments a counter that the snapshot exposes.
5. `push` takes no mutex, does not deliberately sleep, and never allocates on
   the steady path. It can spin behind a preempted peer and has no formal
   lock-free progress guarantee. Exclude interrupt, reentrant, and real-time
   contexts.

Normalize domain aliases at the boundary, so a caller that names a domain
slightly differently lands in the right ring instead of creating a new one.

### What not to use

| Alternative | Failure |
|-------------|---------|
| `tokio::sync::broadcast` | Fan-out semantics. Every subscriber gets every message and must handle `Lagged`. Consumers here drain one ring; they are not independent subscribers. |
| An unbounded channel | A slow consumer becomes an out-of-memory kill. |
| A blocking mutex-backed buffer | A slow consumer stalls the data plane. |
| A ring with drop-newest | The most recent events are the ones you need after a fault. |

## The snapshot entry point

The host polls. It does not receive pushes per event.

```rust
#[unsafe(no_mangle)]
pub extern "system" fn Java_com_example_app_TelemetryNative_jniSnapshot<'local>(
    mut env: EnvUnowned<'local>,
    _thiz: JObject<'local>,
) -> JString<'local> {
    env.with_env(|env| -> jni::errors::Result<JString<'local>> {
        let snap = TelemetrySnapshot {
            counters: COUNTERS.read(),
            events: EVENT_RING.drain(),
            dropped_events: EVENT_RING.dropped(),
        };
        let json = serde_json::to_string(&snap)
            .map_err(|_| jni::errors::Error::JavaException)?;
        env.new_string(json)
    })
    .resolve::<jni::errors::ThrowRuntimeExAndDefault>()
}
```

`resolve` is the exit: it rebuilds an `Env`, throws for an error or a caught
panic, and returns the default. The helper names differ per binding version.
See the `rust-jni` skill for the binding rules and the `uniffi-boundary` skill
if you generate the surface instead of writing it.

What matters, independent of binding:

- One call returns counters and drained events together.
- The drain empties the ring, so a slow poller loses only through the ring's own
  drop-oldest rule, and the drop count says how much.
- The serialized form is stable enough to golden-test. See the determinism
  section in `SKILL.md`.
- Nothing in the data plane calls into the host.

### Readiness is the exception

Polling for a readiness sentinel adds the whole poll interval to start-up
latency. Use a one-shot readiness callback instead.

Keep the readiness path separate from the snapshot path:

- Register the readiness callback with its own generation token, so a callback
  from a previous runtime instance is ignored.
- Fire it once per runtime generation.
- Do not put a readiness flag in the snapshot. If both exist, the two disagree
  during the window between them.

## Panic reporting

Install a hook when the library loads — in `JNI_OnLoad` on Android, or in your
init entry point elsewhere. Emit one bounded structured record. Do not format
`PanicHookInfo`, inspect its payload, or emit a backtrace. A panic payload is
arbitrary application text and can contain input data, paths, identifiers, or
secrets.

```rust
#[derive(Clone, Copy)]
enum PanicSite {
    Boundary,
    Engine,
    Unknown,
}

fn classify_site(file: &str) -> PanicSite {
    if file.starts_with("src/boundary/") {
        PanicSite::Boundary
    } else if file.starts_with("src/engine/") {
        PanicSite::Engine
    } else {
        PanicSite::Unknown
    }
}

std::panic::set_hook(Box::new(|info| {
    let (site, line, column) = info
        .location()
        .map(|location| {
            (
                classify_site(location.file()),
                location.line(),
                location.column(),
            )
        })
        .unwrap_or((PanicSite::Unknown, 0, 0));

    write_platform_panic("rust_panic", site, line, column);
}));
```

The event name and site code come from closed vocabularies. The line and column
are bounded integers. Unknown paths collapse to `Unknown`; never use an unknown
path as a fallback field value.

Three constraints:

- The hook runs on the panicking thread. Keep it allocation-light and
  lock-free where you can. A lock held by the panicking thread deadlocks here.
- The platform writer accepts structured fields, not one formatted string. Cap
  the encoded record before it reaches a platform-specific line limit.
- A debug or opt-in build does not make a raw panic payload safe. Keep the same
  redaction contract in every profile.

See the `rust-panic-safety` skill for unwinding across a boundary.

## Stall detection

A host-side "not responding" state has no direct Rust signal. The measurable
proxy is an async runtime that stops making progress.

```rust
tokio::spawn(async move {
    loop {
        tokio::time::sleep(Duration::from_secs(1)).await;
        HEARTBEAT_TICK.fetch_add(1, Ordering::Relaxed);
    }
});
```

The host reads `HEARTBEAT_TICK` through the same snapshot it already polls. It
records the last observed value and the host's own monotonic time when that
value changes. An unchanged value for a threshold — ten seconds is a workable
default — means the runtime is not scheduling. Raise the alert on the host
side. Do not compare wall-clock timestamps: clock corrections can create false
stalls or hide real ones.

This detects a stalled scheduler. It does not detect a blocked worker thread
that still lets the timer task run. For that, add a per-worker last-progress
timestamp on the same relaxed atomic pattern.

## Privacy floor for telemetry

Everything in the snapshot crosses a boundary and often ends up in a bug report.
Apply the same floor as for events:

- No device or network identifiers, raw or hashed. A salted hash remains a
  stable correlation value and can permit dictionary attacks. Emit aggregate
  counts or a local non-identifying category instead.
- No hardware or subscriber identifiers under any encoding.
- No addresses that identify a user's device or its location.
- No secrets, key material, or handshake payload bytes.
- No payload bytes. Sizes and counts are allowed. Opaque flow identifiers must
  be random, short-lived, session-scoped, and unrelated to forbidden values.

Audit before every release, and remember that the grep is a floor, not a proof.

```bash
rg -i 'bssid|ssid|imei|imsi|raw_ip|latitude|longitude' \
  . --type rust -n | grep -v '// allow:'
```
