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

One ring per domain. Each ring owns a bounded channel and a drop counter.

```rust
use core::sync::atomic::{AtomicU64, Ordering};
use flume::TrySendError;

pub struct EventRing {
    tx: flume::Sender<Record>,
    rx: flume::Receiver<Record>,
    dropped: AtomicU64,
}

impl EventRing {
    pub fn with_capacity(capacity: usize) -> Self {
        let (tx, rx) = flume::bounded(capacity);
        Self { tx, rx, dropped: AtomicU64::new(0) }
    }

    /// Never blocks. On a full ring the oldest record is evicted.
    pub fn push(&self, record: Record) {
        // `TrySendError::Full` hands the record back, so the fast path does not
        // clone. The ring owns both ends, so `Disconnected` cannot happen.
        let record = match self.tx.try_send(record) {
            Ok(()) => return,
            Err(TrySendError::Full(record)) => record,
            Err(TrySendError::Disconnected(_)) => return,
        };
        // Full: drop the oldest, count it, retry once.
        if self.rx.try_recv().is_ok() {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
        // Another producer can refill the slot first. Count that loss too.
        if self.tx.try_send(record).is_err() {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn drain(&self) -> Vec<Record> {
        self.rx.try_iter().collect()
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
5. `push` never blocks and never allocates on the steady path.

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
pub extern "system" fn Java_com_example_app_TelemetryNative_jniSnapshot(
    mut env: EnvUnowned<'_>,
    _thiz: JObject,
) -> JString {
    env.with_env(|env| -> jni::errors::Result<JString> {
        let snap = TelemetrySnapshot {
            counters: COUNTERS.read(),
            events: EVENT_RING.drain(),
            dropped_events: EVENT_RING.dropped(),
        };
        let json = serde_json::to_string(&snap)
            .map_err(|_| jni::errors::Error::JavaException)?;
        env.new_string(json)
    })
    .into_outcome()
    .ok_or_throw(env, JString::default())
}
```

The exact env wrapper and outcome helpers depend on your JNI binding version.
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

A platform log writer truncates long lines. Android's `liblog` is the common
case. A panic payload plus a backtrace exceeds the limit, so the root cause is
the part that gets cut.

Install a hook when the library loads — in `JNI_OnLoad` on Android, or in your
init entry point elsewhere — and write the payload in chunks of 4 KiB or less.

```rust
std::panic::set_hook(Box::new(|info| {
    let text = format!("{info}");
    let mut rest = text.as_str();
    while !rest.is_empty() {
        // Cut at a char boundary at or below 4 KiB. Byte chunking splits a
        // multi-byte character and corrupts the payload.
        let mut end = rest.len().min(4096);
        while !rest.is_char_boundary(end) {
            end -= 1;
        }
        let (chunk, tail) = rest.split_at(end);
        write_platform_log(chunk);
        rest = tail;
    }
}));
```

Two constraints:

- The hook runs on the panicking thread. Keep it allocation-light and
  lock-free where you can. A lock held by the panicking thread deadlocks here.
- The hook writes to the platform log, not to a redacting sink. A panic message
  is free text by definition. Treat it as a debug-build or opt-in surface if
  your privacy floor forbids free text in production.

See the `rust-panic-safety` skill for unwinding across a boundary.

## Stall detection

A host-side "not responding" state has no direct Rust signal. The measurable
proxy is an async runtime that stops making progress.

```rust
tokio::spawn(async move {
    loop {
        tokio::time::sleep(Duration::from_secs(1)).await;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        HEARTBEAT.store(now, Ordering::Relaxed);
    }
});
```

The host reads `HEARTBEAT` through the same snapshot it already polls. A value
older than a threshold — ten seconds is a workable default — means the runtime
is not scheduling. Raise the alert on the host side.

This detects a stalled scheduler. It does not detect a blocked worker thread
that still lets the timer task run. For that, add a per-worker last-progress
timestamp on the same relaxed atomic pattern.

## Privacy floor for telemetry

Everything in the snapshot crosses a boundary and often ends up in a bug report.
Apply the same floor as for events:

- No raw device or network identifiers. Contribute them to a salted hash and
  emit the hash.
- No hardware or subscriber identifiers under any encoding.
- No addresses that identify a user's device or its location.
- No secrets, key material, or handshake payload bytes.
- No payload bytes. Sizes, counts, and opaque flow identifiers are allowed.

Audit before every release, and remember that the grep is a floor, not a proof.

```bash
rg -i 'bssid|ssid|imei|imsi|raw_ip|latitude|longitude' \
  . --type rust -n | grep -v '// allow:'
```
