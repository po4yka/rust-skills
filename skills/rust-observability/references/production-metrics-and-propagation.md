# Production Metrics and Context Propagation

Read this reference before you add a production metric, propagate an
OpenTelemetry context, or change an exporter. Keep the redaction and data-plane
rules in `SKILL.md` in force.

## Define the metric contract first

Write one row before you write code.

| Field | Required decision |
|-------|-------------------|
| Name | Stable semantic name and owner |
| Instrument | Counter, UpDownCounter, gauge, or histogram |
| Unit | UCUM unit in instrument metadata |
| Meaning | One sentence that states what one measurement means |
| Attributes | Closed list with the source and maximum values for each key |
| Series budget | Numeric maximum for the product of all attribute values |
| Aggregation | Backend-compatible aggregation and temporality |
| Boundaries | Increasing values in the instrument unit, for a histogram |
| Consumers | Dashboard, alert, SLO, or capacity query that needs the metric |

Do not add a metric with no named consumer. Do not use a metric to preserve a
value that belongs in a log or trace.

Check the OpenTelemetry semantic conventions before you define a name. Use an
existing semantic name and its instrument, unit, and attributes when it fits.
For an application-specific metric:

- Use lowercase dot-separated namespaces. Use underscores only inside one
  namespace component.
- Do not put the unit in the name when instrument metadata carries it.
- Do not append `total`. An exporter can translate a counter name for its
  target format.
- Use `s` for durations, `By` for bytes, `1` for ratios, and singular UCUM
  annotations such as `{request}` for integer item counts.
- Keep one name tied to one meaning, unit, and instrument kind. Rename the
  metric when any of those properties changes.

## Choose the instrument from its semantics

| Value | Instrument | Example |
|-------|------------|---------|
| Monotonic total of non-negative additions | Counter | completed operations, bytes sent |
| Current total that rises and falls | UpDownCounter | active operations, queued work |
| Latest non-additive observation | Gauge | temperature, configured limit |
| Distribution of independent observations | Histogram | request duration, payload size |

Use the same attribute set for the increment and decrement of an
UpDownCounter. Otherwise they update different time series.

Do not publish a gauge of a local average when consumers need a population
distribution. Record each observation into a histogram. Let the backend derive
rates and quantiles from sums, counts, and buckets.

## Set histogram boundaries from decisions

Do not accept library defaults without checking them against the measured
range. Start with the thresholds that change an operational decision:

1. Put every SLO and alert threshold on an exact bucket boundary.
2. Add enough lower boundaries to separate the normal operating range.
3. Add enough upper boundaries to expose saturation and timeouts.
4. Keep all boundaries strictly increasing and in the declared unit.
5. Keep the same boundaries for every process that emits the metric.

Do not add buckets only to make a chart smooth. Each bucket increases storage
and export cost. Test zero, every decision boundary, one value between adjacent
boundaries, and one value above the last boundary. Assert that the observation
count and the selected buckets are correct.

## Budget attribute cardinality

An attribute set creates a time series. Review its worst-case product, not each
attribute in isolation.

```text
max_series = values(method) * values(route) * values(status_class) * values(region)
```

Record `max_series` in the metric contract. Reject the change if the calculated
product exceeds that number. Configure an SDK or backend hard limit when the
selected stack supports one. Monitor the overflow or dropped-series signal.
Do not treat a hard limit as permission to emit unbounded attributes.

Budget at the backend identity boundary, not only at one instrument call.
Include bounded resource attributes, collector-added dimensions, and the
maximum number of emitting instances. Record separate per-process and fleet
limits. A local attribute product can fit while the fleet series count exceeds
the storage budget.

Allow only bounded semantic values. Prefer normalized route templates and
closed error kinds. Never use these values as metric attributes:

- user, tenant, device, request, session, span, or trace identifiers;
- raw URL paths, query strings, hostnames, file paths, or peer addresses;
- free-text errors or arbitrary external names;
- timestamps or monotonically increasing sequence numbers.

Put high-cardinality detail in a redacted trace or log. Do not hash a forbidden
value to turn it into a label.

## Use exemplars only as links

Enable exemplars only when the SDK and exporter preserve them and the backend
can query them. Prefer trace-based exemplar sampling from sampled spans. An
exemplar links an aggregate point to a trace; it does not replace the metric
and must not be required for an alert.

Do not add a trace or span ID as a metric attribute. Verify exemplar privacy
separately. Exemplars can retain measurement attributes that a metric view
drops. Apply the same allow list to the exemplar reservoir input. Disable
exemplars when the stack cannot enforce that floor.

## Propagate one context

Use one configured propagator contract for all services. Prefer W3C Trace
Context for traces. Add W3C Baggage only when a reviewed use case needs it.
Baggage crosses process boundaries and can reach metrics, logs, and traces, so
apply an allow list and size limits during both extraction and injection.
Discard unknown or oversized baggage before you attach the extracted parent.
Keep trace-context validity separate from baggage trust.

For an inbound transport:

1. Extract and validate the carrier before you create the server span.
2. Set the extracted context as the parent once.
3. Treat malformed or missing propagation fields as absent context. Do not fail
   the domain request.
4. Do not trust a remote sampling flag as authorization to record sensitive
   data.

For an outbound transport, inject the current operation context into the
carrier immediately before the send. Do not copy headers by hand. Use the
configured propagator so validation and format stay consistent.

### Async tasks and callbacks

Capture the parent context when you create a future or task. Instrument the
future, or wrap it with the context-aware future helper supplied by the chosen
integration. Do not attach a thread-local context guard around an `.await`.
The future can move between threads, and a guard can stay active while another
future runs on that thread.

Choose the relationship before a detached task starts:

- Use a child span when the parent operation waits for the task.
- Use a span link when queued work has an independent lifetime or more than one
  cause.
- Start a new root only when no valid causal context exists.

Capture context at callback registration only when the callback belongs to that
registration operation. Otherwise pass context with each callback invocation.
Never read an arbitrary executor thread's current context as the parent.

### HTTP, messages, and FFI

For HTTP and text-capable message carriers, inject and extract through the
propagator's carrier interface. Preserve `traceparent` and `tracestate` as one
validated trace context. Apply message-system rules for retries and redelivery;
do not reuse one consumer span across multiple deliveries.

Do not pass an SDK `Context`, span object, or thread-local guard across FFI.
Define an owned carrier in the boundary contract. Carry the configured
propagator's text fields in a size-bounded record. Copy borrowed bytes before
the foreign call returns.

Extract on entry and inject on exit. Make missing or invalid context a normal
case. Apply the boundary's size limits before parsing. Do not let telemetry
parsing panic or unwind across FFI.

Test one trace across every real handoff. Assert parent or link relationships
for an async spawn, an HTTP round trip, and each FFI direction that exists.
Also send malformed and oversized carriers and assert that domain behavior is
unchanged.

## Bound the exporter

Use a batch processor or periodic reader for production export. Keep simple or
synchronous export for tests and local diagnosis only.

Set these limits explicitly from the service budget:

| Limit | Failure it contains |
|-------|---------------------|
| Queue capacity | Collector outage cannot exhaust process memory |
| Maximum batch size | One export has bounded memory and wire size |
| Schedule interval | Quiet traffic still leaves within a known delay |
| Export timeout | A stuck collector cannot hold a worker forever |
| Retry attempts and elapsed time | A long outage cannot create an infinite retry loop |
| Shutdown timeout | Process exit cannot wait forever |

Keep the maximum batch size at or below the queue capacity. Keep exporter I/O
off application executor workers when the selected SDK requires a blocking
client or a dedicated worker. Do not hold an application, sink-registry, or FFI
lock during export.

The request and data plane never wait for exporter capacity. When the queue is
full, follow the processor's documented drop policy and increment an observable
drop counter. Export queue depth, accepted items, dropped items, batch size,
export latency, and failures through a path that cannot recursively feed the
same exporter.

Let the protocol exporter own protocol retries. Do not add a second retry loop
around it. Retry only transient failures. Bound exponential backoff with jitter
by both attempt count and elapsed time. Drop a batch after a permanent failure
or exhausted budget, count it once, and continue domain work.

## Shut down once

The process bootstrap owns providers and exporters. A library must not replace
or shut down a host's global provider. Retain the provider handle that the
current SDK version requires for explicit shutdown.

On controlled process exit:

1. Stop accepting new application work.
2. Drain or cancel admitted work and join owned workers under one deadline
   while telemetry providers remain active.
3. Stop the remaining application-owned telemetry producers. Do not shut down
   processors, readers, or exporters independently from their provider.
4. Force a bounded flush when loss at this exit matters.
5. Shut each owned provider down once with a deadline.
6. Report timeout or failure through a fallback channel that does not use the
   stopped exporter.

Do not retry shutdown. Do not change a successful domain result because flush
or shutdown failed. The deadline bounds waiting, not delivery. Timeout or
abrupt termination can lose buffered telemetry; a batch exporter does not
provide durable delivery.

## Review checklist

- [ ] Each metric has one consumer and one written contract.
- [ ] Name, kind, unit, attributes, and temporality keep one meaning.
- [ ] Histogram boundaries include every SLO and alert threshold.
- [ ] Each attribute has bounded values and the product fits `max_series`.
- [ ] Exemplars preserve the privacy floor and are not labels.
- [ ] Context is explicit across async, HTTP, message, callback, and FFI paths.
- [ ] Malformed propagation does not fail domain work.
- [ ] Export queue, batch, timeout, retry, and shutdown are bounded.
- [ ] Exporter loss and failure are observable without recursive export.
- [ ] The owning bootstrap flushes and shuts down providers exactly once.
