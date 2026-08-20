---
name: rust-observability
description: Use when you add a log field, production metric, OpenTelemetry exporter, context propagation across an async, HTTP, or FFI boundary, host or embedded log sink, hot-path telemetry, telemetry snapshot for a foreign caller, or sensitive-data review. Covers Rust diagnostics, tracing, metric names and units, counters, gauges, histograms, cardinality, exemplars, redaction, bounded export, and deterministic emission order. Triggers on "production metrics", "metric naming", "histogram boundaries", "label cardinality", "OpenTelemetry context propagation", or "exporter shutdown".
license: BSD-3-Clause
---

# Rust Observability

This skill covers diagnostic emission in a Rust library that other processes,
languages, or runtimes embed. It applies to a cdylib behind an FFI boundary, a
staticlib linked into an application, and a plain crate consumed by a host CLI.

## The six rules that are not style

1. **One dispatcher install per process.** Call
   `tracing::subscriber::set_global_default` once during process bootstrap. The
   installed subscriber owns a fan-out registry for all embedded sinks. Never
   call `set_global_default` once per sink or once per FFI boundary.
2. **`skip_all` on every `#[instrument]`.** Without it the macro records every
   argument through `Debug`.
3. **No `?` and no `%` sigils, and no `format!` inside an emission** that can
   reach a sink you do not control. All three produce free text.
4. **Field names come from one declared vocabulary.** A name that is not in the
   vocabulary does not compile past the gate.
5. **Nothing on the data plane emits an event.** Data-plane work increments an
   atomic counter or pushes into a bounded queue. It never calls a log macro.
6. **Diagnostics are observational.** No code path reads the outcome of an
   emission. Turning a subscriber on must not change a single output byte.

## Add an emission

```rust
#[tracing::instrument(skip_all, fields(stage = stage.code()))]
fn decode(stage: DecodeStage, items: &[Item]) -> Result<Output, EngineError> {
    tracing::debug!(item_count = items.len(), "decoding");
    // ...
}
```

Work through this list each time.

1. Write `skip_all`. Then name each field you want. `fields(stage =
   stage.code())` records a small closed enum code, not the whole argument.
2. Use no sigils. `?value` and `%value` serialize through `Debug` and `Display`.
   Both are unbounded channels into the record.
3. Take the field name from the vocabulary tables in your observability crate.
   Adding a name means adding it to the table. Ask what value the name will
   carry, not what the name looks like. A field called `count` that holds a
   fixed-point coordinate is a leak with a safe-looking name.
4. **Verify the call chain before you instrument.** Many crates have two entry
   points for the same work: a budgeted or cancellable entry used by the FFI
   boundary, and a plain entry used by the CLI. Instrumenting the wrong one
   compiles, passes unit tests, and emits nothing at run time. Exercise the path
   with the host tool before you trust it.
5. Watch `clippy::large_stack_frames`. The lint is off by default. Enable it and
   set `stack-size-threshold` in `clippy.toml`. A span or an event macro can push
   a frame past a small threshold such as 4096 bytes. For a once-per-operation
   call, an `#[expect]` with a reason is correct. In a hot loop, move the
   emission into an `#[inline(never)]` helper, or delete it.

## Severity

| Level | Use for |
|-------|---------|
| `error` | The operation failed. |
| `warn` | Recoverable degradation. The operation continues. |
| `info` | A boundary event: start, stop, configuration applied. |
| `debug` | Detail for one operation. |
| `trace` | Per-item work inside a loop. Off in release. |

Cancellation is `debug`. A cancelled operation is the caller getting what it
asked for. Reporting it as an error teaches readers to ignore the severity that
matters.

## Control plane and data plane

Pick the channel by the path, not by the information you want.

| Channel | Use for | Forbidden for | Cost |
|---------|---------|---------------|------|
| `tracing` events and spans through a registered subscriber, for example `tracing-android` or `tracing-logcat` on Android | Control plane: lifecycle, configuration, errors, single-shot diagnostics, control-flow spans | Per-packet, per-byte, per-item paths | Formatting plus an atomic load on the callsite cache; roughly a few microseconds per event when a platform log writer is behind it |
| The `log` crate forwarded to a platform logger, for example `android_logger` | Control plane in code you do not own, or a dependency that only speaks `log` | The same hot paths | Roughly 1 µs per event with no arguments, roughly 3 µs with formatted arguments, when a syscall or FFI call is behind it |
| A native trace backend, for example Perfetto through `tracing-android-trace` | Performance investigation only | Anything enabled by default in release | Heavy. Put it behind a debug-only feature flag |
| `AtomicU64::fetch_add` | Data-plane counters: items, bytes, drops, errors | Anything that is not a count | One instruction on ARM64 with LSE (`LDADD`) |
| A bounded queue drained by a poller | Data-plane events that a consumer must see individually | Anything that must never be dropped | One bounded push, no allocation on the steady path |

Re-measure the microsecond figures on your own target. Treat them as orders of
magnitude, not as constants.

**Rule:** any `tracing::event!`, `tracing::span!`, `log::info!`, or
`log::debug!` inside a per-item or per-byte path is rejected in review. The one
exception is an error path, where the slow case is acceptable.

Find violations before review does.

```bash
rg 'tracing::(event|span|info|debug|trace)!|log::(info|debug|trace)!' \
  <hot-path-crate>/src --type rust -n \
  | grep -vE 'control|lifecycle|error'
```

## One dispatcher install, multiple sinks

An application can load two FFI crates from the same workspace. Each one
installs a subscriber. The second install returns an error that an init function
usually discards, and that boundary then stays silent for the life of the
process.

Put the dispatcher and the sink registry in one shared observability crate.
Install the dispatcher once. Let every boundary add its sink to the registry
owned by that installed subscriber.

```text
install_dispatcher() -> Result<(), InstallError>         process bootstrap, once
register_sink(id, sink, level) -> Result<(), SinkError>   shared sink registry
init_core_logging(sink, level)                           registers sink "core"
init_render_logging(sink, level)                         registers sink "render"
```

`install_dispatcher` is the only function that calls `set_global_default`. Store
its result in a one-time state. Do not retry a failed global install from a
boundary. `register_sink` only mutates the installed subscriber's fan-out
registry. Reject a duplicate sink ID, and report a missing or failed dispatcher
separately from a duplicate registration.

Keep callsite interest valid when the sink set can change. Make the fan-out
subscriber's `register_callsite` return `Interest::sometimes()` for every
callsite. Do not return `Interest::never()` only because the registry is empty.
The callsite caches that result, so a sink registered later cannot receive that
callsite. If the subscriber instead caches interest from the current sinks,
release the registry lock and call
`tracing_core::callsite::rebuild_interest_cache()` after every sink, level, or
filter mutation. Rebuild after a change to `max_level_hint` too.

Logging remains optional for application start-up. Return installation and
registration status to the host, but do not panic or turn a diagnostic failure
into a domain-operation failure.

Cover this with one process-level test. Install once with no sinks. Call one
`emit_probe` helper and assert that no record arrives. Register a sink. Call the
same helper again and assert that exactly one record arrives. This sequence uses
the same static callsite and catches a stale cached `Interest::never()` result.
Then register the other boundary sink, emit through both boundaries, and assert
that both sinks receive their records. Also assert that a duplicate ID is
rejected without replacing the original sink.

## Host and embedded sink see different things

This is the part reviewers get wrong.

- **Host** (a CLI or a test binary): a `tracing-subscriber` formatting layer
  renders the full event, including an error's `Display` message. Keep it off
  unless an environment filter is set. Write to stderr so stdout stays
  machine-readable.

  ```bash
  RUST_LOG=my_pipeline=debug my-cli render input.toml
  ```

- **Embedded sink** (a callback registered across FFI): receives a redacted
  record — severity, target, callsite name, and the fields that survive the
  visitor. **Never the message.** An error arrives as its kind, a frozen
  enumeration case, and nothing else.

No engine crate and no FFI crate depends on `tracing-subscriber`. Only the host
binary does. If you find yourself adding that dependency to a library crate,
stop and put the layer in the host instead.

See [references/redaction-and-field-vocabulary.md](references/redaction-and-field-vocabulary.md)
for the visitor contract, the field tables, and the gate.

## Bounded event queue

A data-plane event that a consumer must see individually goes into a bounded
queue, not into a log macro.

Contract:

- The queue is **bounded**. Pick the capacity per domain.
- Emission is **non-blocking**. A producer never waits for a consumer.
- On a full queue, **remove the oldest record and retry the push**.
- Increment a **dropped-event counter** on every eviction, and expose it.
- Retained records keep **FIFO order**.
- Use **one queue per domain**. A consumer drains one domain into a snapshot.

Use a bounded MPMC channel, for example `flume` or `crossbeam-channel`, or a
fixed-size ring behind a lock that is never held across a syscall.

Do not replace this with `tokio::sync::broadcast`, an unbounded queue, or a
blocking mutex-backed buffer.

- `broadcast` gives every subscriber every message and reports `Lagged`. That is
  a different contract. Consumers here drain, they do not subscribe.
- An unbounded queue converts a slow consumer into an out-of-memory kill.
- A blocking buffer converts a slow consumer into a stalled data plane.

If you change the implementation, preserve the capacity bound, the FIFO order
among retained events, the drop-oldest behavior, and the observable drop count.

## Data-plane counters

```rust
use core::sync::atomic::{AtomicU64, Ordering};

pub struct DataPlaneCounters {
    pub tx_items: AtomicU64,
    pub tx_bytes: AtomicU64,
    pub rx_items: AtomicU64,
    pub rx_bytes: AtomicU64,
    pub drops: AtomicU64,
}

impl DataPlaneCounters {
    pub fn record_tx(&self, n: usize) {
        self.tx_items.fetch_add(1, Ordering::Relaxed);
        self.tx_bytes.fetch_add(n as u64, Ordering::Relaxed);
    }
}
```

`Relaxed` is correct for a counter. You need atomicity, not a happens-before
edge. See the `memory-model` skill for the rationale.

A counter read is a snapshot of independent values. Two counters read in one
pass are not consistent with each other. Do not derive an invariant from a
ratio of two relaxed counters.

## Production metrics and distributed context

Treat a metric and its labels as a public resource contract. Choose the
instrument from the value semantics. Set the unit, histogram boundaries, and a
numeric series budget before you emit it. Do not use an identifier, free-text
error, URL, or trace ID as a label.

Preserve one OpenTelemetry context across each logical operation. Make the
handoff explicit at async task, HTTP, message, callback, and FFI boundaries.
Do not keep a thread-local context guard alive across `.await`.

Keep exporter work outside request and data-plane paths. Bound its queue,
batch, export time, retry time, and shutdown time. Export failure never changes
the domain result.

Read
[references/production-metrics-and-propagation.md](references/production-metrics-and-propagation.md)
before you add a production metric, propagate OpenTelemetry context, or change
an exporter.

## Snapshot polling, not per-event callbacks

Keep the telemetry surface coarse-grained and pull-based. The host polls one
serialized snapshot that carries the counters and the drained queue.

Never call across the FFI boundary per item or per telemetry event. The
per-call cost is the whole budget on a hot path.

One deliberate exception is readiness. A one-shot readiness callback beats
polling for a sentinel, because it removes the latency of the next poll
interval. Keep readiness registration and its generation token separate from
the periodic snapshot. Never reintroduce a readiness flag that only becomes
visible on the next poll.

See [references/embedded-telemetry-surface.md](references/embedded-telemetry-surface.md)
for the snapshot entry point, panic reporting, and stall detection.

## Deterministic ordering

Two properties, both testable.

**Emission must not change results.** Run the same operation twice in one
process: once with no subscriber, once with a subscriber at the most verbose
level. Byte-compare every output artifact. Add a negative control, so a pass
cannot be vacuous — mutate one input and assert that the comparison fails.

**Serialized telemetry must be stable across runs.** Goldens compare snapshots.

```rust
use serde::Serialize;
use serde_json::ser::{PrettyFormatter, Serializer};

fn to_golden_json<T: Serialize>(value: &T) -> Result<String, serde_json::Error> {
    let mut buf = Vec::new();
    let mut ser = Serializer::with_formatter(&mut buf, PrettyFormatter::with_indent(b"  "));
    value.serialize(&mut ser)?;
    Ok(String::from_utf8(buf).expect("valid UTF-8"))
}
```

`serde_json` does not sort keys. Get a stable order in one of three ways:

- Derive `Serialize` on a struct and keep the field order alphabetical.
- Use `BTreeMap<String, T>` instead of `HashMap`.
- Post-process the value through a sorting step before you compare.

Scrub the volatile fields before the diff. Keep the list in one file next to the
goldens.

```json
{
  "scrub_paths": [
    "$.events[*].timestamp_ms",
    "$.events[*].request_id",
    "$.counters.uptime_ms"
  ]
}
```

Any tool or reviewer that classifies a golden diff as semantic or volatile reads
that file. Do not restate the list anywhere else.

## Privacy floor

Diagnostic emission must not carry:

- Device or network identifiers, raw or hashed. A salted hash still supports
  correlation and dictionary attacks. Emit only aggregate counts or a local
  non-identifying category.
- Hardware and subscriber identifiers under any encoding.
- Addresses that identify a user's device or its location.
- Secrets, key material, or handshake payload bytes.
- Message or packet payloads. Counters and sizes are allowed. An opaque flow
  identifier must be random, short-lived, and scoped to one process or session.
  Never derive it from a forbidden value. Bytes are not allowed.

Audit before every release.

```bash
rg -i 'bssid|ssid|imei|imsi|raw_ip|latitude|longitude' \
  . --type rust -n | grep -v '// allow:'
```

The grep is a floor, not a proof. See the reference for the two leaks that no
regex finds.

## "It emits nothing"

Work down this list before you suspect the instrumentation.

| Check | Symptom when it is the cause |
|-------|------------------------------|
| Is a sink registered at all? | With no sink the dispatcher's level ceiling is off, and `enabled` rejects every callsite by design. |
| Was this callsite emitted before the first sink was registered? | The subscriber cached `Interest::never()` from the empty registry. Return `Interest::sometimes()` for a mutable registry, or rebuild the interest cache after each mutation. |
| Did the one-time dispatcher install fail? | Another global subscriber won. Report the bootstrap error; do not retry from each boundary. |
| Did sink registration fail? | The dispatcher is unavailable or the sink ID is already registered. Inspect the distinct registration status. |
| Is the sink's level above the emission's level? | Higher-severity events still arrive; the quiet ones do not. |
| On a host, is the env filter set and valid? | An invalid filter is reported on stderr and leaves diagnostics off. |
| Is the instrumented function on the path you exercise? | Unit tests pass, the CLI prints nothing. See step 4 of *Add an emission*. |
| Is the emission in a `#[cfg(test)]` module? | The release build drops it. |
| Is the crate target in the filter? | `RUST_LOG=debug` is not the same as `RUST_LOG=my_crate=debug` when a dependency floods the output. |

## Gates and lints

Run these before you push.

```bash
cargo test -p <observability-crate>
cargo clippy --workspace --all-targets -- -D warnings
```

Add a repository gate that reads the field tables from the observability crate
rather than repeating them, so the gate and the runtime visitor cannot disagree.
The gate rejects:

- a `?` or `%` sigil in an emission,
- `format!` inside an emission,
- `#[instrument]` without `skip_all`,
- a field name that is not declared in the vocabulary,
- a crate whose declared coverage state disagrees with the coverage record.

Give the gate a `--self-test` mode that runs it against one known-bad fixture per
rule, and run that mode first. A gate with no self-test rots into a no-op after
the first refactor of its patterns.

Deny stdio macros in every workspace.

```toml
# clippy.toml
allow-print-in-tests = true
```

```rust
// crate root: lib.rs or main.rs
#![deny(clippy::print_stdout, clippy::print_stderr, clippy::dbg_macro)]
```

Stdio bypasses the redacting visitor. On a mobile or embedded target it reaches
no reader at all. Grant exemptions as inner attributes with a written reason, in
host-side tools only. Use `allow-print-in-tests` for test code that lives inside
`src/`, where a path rule cannot see it.

## Review checklist

- [ ] Every `#[instrument]` has `skip_all` and names its fields.
- [ ] No sigil and no `format!` in any emission that can reach an embedded sink.
- [ ] Every new field name exists in the vocabulary tables.
- [ ] The instrumented entry point is the one the boundary actually calls.
- [ ] No log macro on a per-item or per-byte path.
- [ ] Only one bootstrap path installs the dispatcher. Boundary initializers
      only register sinks in its fan-out registry.
- [ ] A mutable fan-out returns `Interest::sometimes()`, or every mutation
      rebuilds the callsite interest cache after it releases the registry lock.
- [ ] The same callsite emits before registration and reaches the new sink after
      registration in a process-level test.
- [ ] No library crate depends on `tracing-subscriber`.
- [ ] Counters use `Relaxed`. The drop counter is exposed.
- [ ] The queue is bounded, drops the oldest, and counts the drop.
- [ ] The determinism test still passes, with its negative control.
- [ ] No correlation identifier is derived from a forbidden value.
- [ ] A panic hook emits only bounded structured fields. It never formats raw
      `PanicHookInfo`, its payload, or a backtrace.

## Related skills

- `memory-model` — why `Relaxed` is correct for counters.
- `rust-async-internals` — `broadcast` `Lagged` handling, task shutdown.
- `rust-security` — what must not leave the process.
- `rust-panic-safety` — panic hooks and unwinding across a boundary.
- `rust-jni` — FFI call cost, thread naming for readable logs.
- `ffi-error-progress-cancel` — error kinds, progress, cancellation at a boundary.
- `rust-lints` — enforcing the clippy configuration above.
- `rust-performance` — measuring the cost an emission adds.
