---
name: rust-observability
description: Use when adding or reviewing tracing, logging, or production metrics in Rust, especially in a library or cdylib behind FFI that exposes a telemetry snapshot to its host. Also for metric naming, histogram boundaries, label cardinality, OpenTelemetry context propagation, and exporter shutdown. Triggers on tracing-subscriber, set_global_default, LogTracer, SetLoggerError, EnvFilter, instrument skip_all, android_logger, tracing-opentelemetry, opentelemetry_sdk.
license: BSD-3-Clause
---

# Rust Observability

These rules assume a Rust library that another process, language, or runtime
embeds: a cdylib behind FFI, a staticlib, or a crate that a host CLI or service
links. The host owns the process. The library owns only its emissions.

## The six rules that are not style

1. **One dispatcher install per process.** Only the host calls
   `tracing::subscriber::set_global_default`, once, during process bootstrap.
   The host is the binary, or the application-owned outermost bootstrap
   `cdylib` that plays that role. The installed subscriber owns a fan-out
   registry for all embedded sinks. Do not install once per sink or once per
   FFI boundary: the second install fails, and that boundary stays silent.
2. **`skip_all` plus explicit `fields(...)` on every `#[instrument]`.** Without
   `skip_all` the macro records every argument, through `Debug` for any
   non-primitive type. Do not add `err` or `ret` on a path that can reach a sink
   you do not control. They record the error through `Display` and the return
   value through `Debug`.
3. **No `?` and no `%` sigils, and no `format!` inside an emission** that can
   reach a sink you do not control. All three produce free text.
4. **Field names come from one declared vocabulary.** A name that is not in the
   vocabulary fails the gate.
5. **Nothing on the data plane emits an event.** Data-plane work increments an
   atomic counter or pushes into a bounded queue. It never calls a log macro,
   except an `error!` or `warn!` on an error path, where the slow case is
   acceptable.
6. **Diagnostics are observational.** No code path reads the outcome of an
   emission. Turning a subscriber on must not change a single output byte.

The gates below enforce rules 1 to 4 and the `max_level_*` rule in *Severity*.
The hot-path search in *Gates and what they prove* finds rule 5 violations,
and the determinism test in *Done when* proves rule 6.

## Gates and what they prove

Run these before you push a change to the observability crate or to an
emission.

```bash
cargo test --locked -p <observability-crate>
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo tree -p <library-crate> -e normal -i tracing-subscriber  # expect "nothing to print"
cargo tree -e features -i tracing --workspace  # no library under a max_level_* feature
cargo tree -e features -i log --workspace      # the same for log
```

Run the `tracing-subscriber` check once for each engine crate and inner FFI
crate. When no workspace crate uses `tracing-subscriber`, it exits 101 with
"did not match any packages". That is also a pass.

Run the hot-path search on each crate that does per-item or per-byte work. It
finds rule 5 candidates for review. The pattern leaves out `error!` and `warn!`,
and catches both the qualified and the imported macro forms.

```bash
rg -n --type rust \
  '\b(trace|debug|info|event|span|trace_span|debug_span|info_span)!|#\[(tracing::)?instrument' \
  <hot-path-crate>/src
```

The test proves the install sequence and the redaction visitor. The `cargo tree`
checks prove the dependency rules. None of them proves that a field value is
safe. That stays a review task.

Add a repository gate that reads the field tables from the observability crate
rather than repeating them, so the gate and the runtime visitor cannot disagree.
The gate rejects:

- a `?` or `%` sigil in an emission,
- `format!` inside an emission,
- `#[instrument]` without `skip_all`, or with `err` or `ret` on a path to an
  embedded sink,
- a field name that is not declared in the vocabulary,
- a crate whose declared coverage state disagrees with the coverage record.

Give the gate a `--self-test` mode that runs it against one known-bad fixture per
rule, and run that mode first. A gate with no self-test rots into a no-op after
the first refactor of its patterns.

Deny stdio macros in library, FFI, and embedded crates. Stdio bypasses the
redacting visitor, and on a mobile or embedded target it reaches no reader.

```toml
# clippy.toml
allow-print-in-tests = true
```

```rust
// crate root: lib.rs or main.rs
#![deny(clippy::print_stdout, clippy::print_stderr, clippy::dbg_macro)]
```

Exempt only a host-side tool whose job is to write to a terminal. Put
`#![expect(clippy::print_stdout, reason = "...")]` after the `#![deny]` line, or
leave `print_stdout` out of that crate's deny list. An `expect` before the
`deny` loses: clippy reports the `println!` and an unfulfilled expectation.
`allow-print-in-tests` covers test code inside `src/`, where a path rule cannot
see it.

## Done when

The gates are green. Then review what they cannot see:

- [ ] Each field value is safe, not only its name. No correlation identifier
      is derived from a forbidden value.
- [ ] The instrumented entry point is the one the boundary actually calls.
- [ ] No event, span, or `#[instrument]` sits on a per-item or per-byte path,
      except an `error!` or `warn!` on an error path.
- [ ] Only one bootstrap path installs the dispatcher: `set_global_default`,
      then `LogTracer::init()`. A library bootstrap never calls `init()` or
      `try_init()`. An `init()` in `JNI_OnLoad` or an FFI init export panics on
      a second install and can abort the process. Boundary initializers only
      register sinks.
- [ ] An embedded sink record holds only declared fields and no message.
- [ ] The queue is bounded, drops the oldest, and counts the drop. The drop
      counter is in the snapshot.
- [ ] The determinism test passes. It runs the same operation twice in one
      process, once with no subscriber and once with a subscriber at the most
      verbose level, and byte-compares every output artifact. Its negative
      control mutates one input and asserts that the comparison fails, so a
      pass cannot be vacuous.
- [ ] A panic hook emits only bounded structured fields. It never formats raw
      `PanicHookInfo`, its payload, or a backtrace.

## "It emits nothing"

Work down this list before you suspect the instrumentation.

| Check | Symptom when it is the cause |
|-------|------------------------------|
| Is a sink registered at all? | With no sink the dispatcher's level ceiling is off, and `enabled` rejects every callsite by design. |
| Was this callsite emitted before the first sink was registered? | The subscriber cached `Interest::never()` from the empty registry. Return `Interest::sometimes()` for a mutable registry, or rebuild the interest cache after each mutation. |
| Did the one-time dispatcher install fail? | Another global subscriber won ("a global default trace dispatcher has already been set"). Report the bootstrap error; do not retry from each boundary. |
| Do `log` records from dependencies vanish? | A second `log` logger was installed first, for example `android_logger`, so `LogTracer` got `SetLoggerError`. Keep one bridge. |
| Do `log` records never arrive, even after a sink registers? | `try_init()` set `log::max_level()` to `Off` at install, when no sink existed. A later sink or `reload` filter raises only the `tracing` ceiling. Install with `set_global_default` plus `LogTracer::init()`. |
| Did sink registration fail? | The dispatcher is unavailable or the sink ID is already registered. Inspect the distinct registration status. |
| Is the sink's level above the emission's level? | Higher-severity events still arrive; the quiet ones do not. |
| Does a dependency enable a `tracing` or `log` `max_level_*` feature? | The callsites are compiled out. `cargo tree -e features -i tracing --workspace` (or `-i log`) names the crate under that feature node. |
| On a host, is `RUST_LOG` valid? | `EnvFilter::from_default_env` prints `ignoring ...` on stderr, drops each invalid directive, and falls back to `error` when none is valid. `try_from_default_env` returns `Err` instead. |
| Is the instrumented function on the path you exercise? | Unit tests pass, the CLI prints nothing. See step 3 of *Add an emission*. |
| Is the emission in a `#[cfg(test)]` module? | The release build drops it. |
| Is the crate target in the filter? | `RUST_LOG=debug` is not the same as `RUST_LOG=my_crate=debug` when a dependency floods the output. |

## Privacy floor

Diagnostic emission and every telemetry snapshot must not carry:

- Device or network identifiers, raw or hashed. A salted hash still supports
  correlation and dictionary attacks. Emit only aggregate counts or a local
  non-identifying category.
- Hardware and subscriber identifiers under any encoding.
- Addresses that identify a user's device or its location.
- Secrets, key material, or handshake payload bytes.
- Message or packet payloads. Counters and sizes are allowed. An opaque flow
  identifier must be random, short-lived, and scoped to one process or session.
  Never derive it from a forbidden value. Bytes are not allowed.
- User data in a panic, `expect`, or `unreachable!` message. A panic message is
  a log line: on Android, `panic = "abort"` copies it into the tombstone
  "Abort message". The `rust-panic-safety` skill owns the redacted panic report.

Audit before a release.

```bash
rg -i 'bssid|ssid|imei|imsi|raw_ip|latitude|longitude' \
  . --type rust -n | grep -v '// allow:'
```

The grep is a floor, not a proof. Two leaks no regex finds are in the
*smuggling routes* of
[references/redaction-and-field-vocabulary.md](references/redaction-and-field-vocabulary.md).

## Add an emission

```rust
#[tracing::instrument(skip_all, fields(stage = stage.code()))]
fn decode(stage: DecodeStage, items: &[Item]) -> Result<Output, EngineError> {
    tracing::debug!(item_count = items.len(), "decoding");
    todo!()
}
```

1. Record a closed code, not the argument. `fields(stage = stage.code())`
   records a small enum code.
2. Take each field name from the vocabulary tables in your observability crate.
   Adding a name means adding it to the table. Judge the value that the name
   carries, not the name. A field called `count` that holds a fixed-point
   coordinate is a leak with a safe-looking name.
3. **Instrument the entry point that the boundary calls.** Many crates have two
   entry points for the same work: a budgeted or cancellable entry for the FFI
   boundary, and a plain entry for the CLI. Instrumenting the wrong one
   compiles, passes unit tests, and emits nothing at run time. Exercise the path
   with the host tool before you trust it.
4. Watch `clippy::large_stack_frames`. The lint is in `nursery`, so it is off by
   default. Enable it and set `stack-size-threshold` in `clippy.toml`. A span or
   an event macro can push a frame past a small threshold such as 4096 bytes.
   For a once-per-operation call, write
   `#[expect(clippy::large_stack_frames, reason = "...")]`. In a hot loop, move
   the emission into an `#[inline(never)]` helper, or delete it.

Read [references/redaction-and-field-vocabulary.md](references/redaction-and-field-vocabulary.md)
when you add a field name, write a sink visitor, or review an emission for
leakage. It has the vocabulary tables, the three smuggling routes, and the
visitor contract.

## Severity

| Level | Use for |
|-------|---------|
| `error` | The operation failed. |
| `warn` | Recoverable degradation. The operation continues. |
| `info` | A boundary event: start, stop, configuration applied. |
| `debug` | Detail for one operation. |
| `trace` | Per-item detail in a control-plane loop, for targeted diagnostics. Never on the data plane. |

Cancellation is `debug`. A cancelled operation is the caller getting what it
asked for. Reporting it as an error teaches readers to ignore the severity that
matters.

No tracing level is off in a release build by default. The installed host
subscriber and its filter decide which events are enabled. Configure and test
the release filter explicitly. Do not rely on `cfg(debug_assertions)` unless the
product contract deliberately removes those callsites.

Do not enable the `max_level_*` or `release_max_level_*` features of `tracing`
or `log` in a library. Cargo unifies features across the build, so one
library's choice compiles out callsites in every crate of the binary. Only the
final binary may set them. The `cargo tree -e features` gates prove it.

## Control plane and data plane

Pick the channel by the path, not by the information you want. `tracing` events
and spans, and `log` records bridged into the same subscriber, serve the control
plane: lifecycle, configuration, errors, single-shot diagnostics. The data plane
uses an `AtomicU64` counter or a bounded queue. A native trace backend, for
example Perfetto, stays behind a debug-only feature flag.

Any event, span, or `#[instrument]` on a per-item or per-byte path is rejected
in review, except an `error!` or `warn!` on an error path. Run the hot-path
search in *Gates and what they prove*.

Read [references/embedded-telemetry-surface.md](references/embedded-telemetry-surface.md)
when you choose a channel for a new path. It has the per-channel cost and
forbidden-use table.

## One dispatcher install, multiple sinks

Put the dispatcher and the sink registry in one shared observability crate.
`install_dispatcher` is the only function that calls `set_global_default`. Each
FFI boundary only calls `register_sink`, which adds its sink to the installed
subscriber's fan-out registry. Rows 2 to 5 of *"It emits nothing"* show the
silent defects. Also:

- Store the install result in a one-time state. Do not retry a failed install
  from a boundary.
- Report the `set_global_default` and `LogTracer::init()` results separately.
- Do not call `android_logger::init_once`. That logger writes dependency
  records to logcat past the redacting visitor.
- Only a host binary whose filter is fixed at install may use `try_init()`.

Logging stays optional for start-up. Return install and registration status to
the host. Do not panic, and do not turn a diagnostic failure into a domain
failure. Test the install in one process-level test, alone in its own
integration-test file, because the global install succeeds once per process.

Read [references/dispatcher-install.md](references/dispatcher-install.md) when
you write or change `install_dispatcher`, `register_sink`, the fan-out
subscriber, the `log` bridge, the install test, or an Android bootstrap sink.
It has the registry API, the interest-cache rebuild rule, the exact `init`
failure messages, and the six install-test steps.

## Host and embedded sink see different things

- **Host** (a CLI, a service, or a test binary): a `tracing-subscriber`
  formatting layer renders the full event, including an error's `Display`
  message. Write to stderr so stdout stays machine-readable. In a CLI, keep the
  layer off unless an environment filter is set. The layer renders untrusted
  text: use `tracing-subscriber` 0.3.20 or later, which escapes ANSI sequences
  in logged values (RUSTSEC-2025-0055), and gate advisories with
  `cargo deny --config deny.toml --locked check advisories`.

  ```bash
  RUST_LOG=my_pipeline=debug my-cli render input.toml
  ```

- **Bootstrap `cdylib`** (the application-owned outermost library that a mobile
  app or plugin host loads): it owns the install and may depend on
  `tracing-subscriber`. In a shipped build, its platform sink receives the
  redacted record, like any embedded sink. On Android, stderr and `RUST_LOG` do
  not apply, and `tracing-logcat` writes the full text, message included: add
  it only in a debug or opt-in build.

- **Embedded sink** (a callback registered across FFI): receives a redacted
  record — severity, target, callsite name, and the fields that survive the
  visitor. **Never the message.** An error arrives as its kind, a frozen
  enumeration case, and nothing else.

Only a host binary and the bootstrap `cdylib` depend on `tracing-subscriber`.
Engine crates, the shared observability crate, and inner FFI library crates do
not. Put the layer in the host instead.

## Counters, the bounded queue, and the snapshot

Count data-plane work with `AtomicU64::fetch_add(n, Ordering::Relaxed)`. A
counter needs atomicity, not a happens-before edge; see the `memory-model` skill.
Two relaxed counters read in one pass are not consistent with each other, so do
not derive an invariant from their ratio.

Put a data-plane event that a consumer must see individually into a bounded
queue, one per domain. On overflow it atomically drops the oldest record, for
example with `crossbeam_queue::ArrayQueue::force_push`, and counts the drop. The
newest records are the ones you need after a fault. Do not use
`tokio::sync::broadcast`, an unbounded queue, or a blocking mutex-backed buffer.

The host polls one serialized snapshot that carries the counters and the
drained queue. Do not call across the FFI boundary per item or per telemetry
event: the per-call cost is the whole budget on a hot path. A one-shot readiness
callback is the one exception.

Read [references/embedded-telemetry-surface.md](references/embedded-telemetry-surface.md)
when you implement or change the event queue, the snapshot entry point, or
readiness, golden-test a snapshot, or work on the telemetry side of panic
reporting or on stall detection. It has the ring code and queue contract, the
snapshot key-order and scrub-path rules, and the heartbeat.

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
when you add a production metric, propagate OpenTelemetry context, change an
exporter, or upgrade the `opentelemetry` crates. It has the Rust SDK traps: the
version pairing, the millisecond-scaled default histogram buckets, the
thread-based batch processors, and provider shutdown.

## Related skills

- `memory-model` — why `Relaxed` is correct for counters.
- `rust-async-internals` — `broadcast` `Lagged` handling, task shutdown.
- `rust-security` — `cargo deny` policy and advisory triage.
- `rust-panic-safety` — the redacted panic report, hook ownership, unwinding.
- `rust-debugging` — reading logcat, tombstones, and a live process.
- `rust-serde` — `serde_json` map order and feature unification.
- `rust-jni` — FFI call cost, thread naming for readable logs.
- `ffi-error-progress-cancel` — error kinds, progress, cancellation at a boundary.
- `rust-lints` — enforcing the clippy configuration above.
- `rust-performance` — measuring the cost an emission adds.
