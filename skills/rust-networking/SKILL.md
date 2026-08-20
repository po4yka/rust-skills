---
name: rust-networking
description: Use when you build or review production Rust network clients and servers; define end-to-end HTTP timeout budgets; retry idempotent and replayable requests with Retry-After and jitter; configure TLS verification, DNS, proxies, or connection pools; bound streaming bodies and overload; or implement graceful shutdown. Triggers on "HTTP timeout", "Retry-After", "TLS verification", "connection pool", "response body limit", or "graceful shutdown".
license: BSD-3-Clause
---

# Rust Networking

Use this skill for the policy around a Rust network client or server. Apply it
to HTTP, gRPC, WebSocket, and custom TCP protocols. Adapt the controls to the
framework that the workspace already uses.

Do not replace the framework to get a specific middleware type. Most mature
Rust network stacks provide timeout, retry, pool, body-limit, and shutdown
controls. Use those controls before you write new middleware.

## Boundaries

This skill owns these decisions:

- the operation deadline and the phase timeout caps;
- the retry eligibility, delay, and attempt budget;
- TLS identity verification and trust-root selection;
- proxy, DNS, and connection-pool lifecycle;
- streaming, body-size, queue, and concurrency limits;
- network cancellation semantics and graceful shutdown;
- network-safe diagnostic fields and deterministic test seams.

Use `rust-async-internals` for `select!`, task ownership, cancel safety, and
runtime configuration. Use `rust-observability` to implement tracing, metrics,
and exporters. Use `rust-security` for dependency policy and generic
untrusted-input parser hardening.

## Start from one operation contract

Write the contract before you change code. Record these fields next to the
client or server configuration:

| Field | Required decision |
|---|---|
| Operation deadline | Maximum wall-clock time for all attempts and delays |
| Connect cap | Maximum time for DNS, address selection, TCP, proxy, and TLS |
| Write cap | Maximum time without upload progress |
| First-byte cap | Maximum time after request upload until response headers |
| Read idle cap | Maximum time without response-body progress |
| Retry attempts | Total attempts, including the first attempt |
| Retry eligibility | Operation semantics, replayable body, and retryable result |
| Response limit | Maximum decoded bytes accepted by the caller |
| Concurrency limit | Maximum admitted work per process, route, or upstream |
| Server header limit | Maximum header bytes, field count, and read time |
| Server idle limits | Keep-alive, request-body, and response-write idle caps |
| Shutdown grace | Maximum time allowed for accepted work to drain |

Do not copy timeout values from another service. Derive them from the caller's
deadline and the service latency objective. Keep all values configurable. Give
each value a finite production default when the caller does not supply one.

## Use one absolute deadline

Create one monotonic deadline at the operation boundary. Carry it through DNS,
connect, proxy negotiation, TLS, every request attempt, response streaming, and
retry delay. Do not restart the full timeout after a retry.

Before each phase, calculate this duration:

```text
phase allowance = min(configured phase cap, operation deadline - monotonic now)
```

Fail before the phase starts when no time remains. Report which phase consumed
the budget. Do not report every deadline failure as `connect timeout`.

Use separate controls for separate failure modes:

| Control | Starts | Ends | Protects against |
|---|---|---|---|
| DNS cap | Before lookup | Address set returned | Resolver stall |
| Connect cap | Before socket or proxy connect | Secure connection ready | Route, proxy, TCP, or TLS stall |
| Write idle cap | After write starts | Request body complete | Peer that stops reading |
| First-byte cap | After request complete | Response headers arrive | Slow handler or upstream |
| Read idle cap | After body starts | Each body chunk | Peer that stops sending |
| Operation deadline | At API entry | Body consumed or discarded | All cumulative work |

On a server, also bound request-header read time and size, keep-alive idle
time, request-body read idle time, and response-write idle time. Start the
header deadline when the connection is accepted, before application admission.
A slow client must not hold an accepted-connection slot without completing a
bounded header.

An idle timeout is not a total transfer timeout. Reset it only after useful
progress. A peer that sends one byte before every idle timeout can still consume
the operation deadline, so enforce both.

Use `tokio::time::timeout_at` or the runtime equivalent when the stack does not
accept a deadline directly. Remember that dropping the timed future cancels it.
Check cancel safety with `rust-async-internals`.

## Retry only a safe operation

Retry only when all three conditions hold:

1. The operation is idempotent by protocol semantics or by an application
   idempotency key that the server stores atomically.
2. The complete request can be replayed byte for byte. A consumed stream is not
   replayable unless the caller can open a fresh stream.
3. The failure is transient and the operation deadline can hold another
   attempt plus its delay.

HTTP `GET`, `HEAD`, `PUT`, `DELETE`, `OPTIONS`, and `TRACE` have idempotent
method semantics. Application behavior can still make an operation unsafe to
repeat. Do not infer replay safety from the method name alone. Do not retry
`POST` unless the application contract provides idempotency or proves that the
server did not apply the request.

Use this default classification, then narrow it for the target service:

| Result | Automatic retry |
|---|---|
| DNS temporary failure | Yes, if another attempt fits |
| Connect refused, reset, or timeout | Yes, for an eligible operation |
| Connection closes before response headers | Yes, for an eligible operation |
| HTTP `408`, `429`, `502`, `503`, or `504` | Yes, when service policy permits it |
| HTTP `Retry-After` | Wait at least the valid server delay, within the deadline |
| Other `4xx` | No |
| TLS certificate or hostname failure | No |
| Request encode or validation failure | No |
| Body stream failed after response headers | No by default |
| Cancellation or exhausted deadline | No |

Do not retry every `5xx`. A retry can multiply overload and repeat an
application failure. Keep the retry status set explicit.

Count the first request as attempt one. Use a small finite attempt limit. Cap
retries again with the operation deadline. Never retry forever in a background
task.

Also bound retries per upstream across the process. Require a retry permit or
token before a second attempt. Limit retry concurrency, and suppress retries
when the local service is overloaded or the upstream failure rate crosses the
configured threshold. If no retry budget remains, return the original failure
instead of adding outage load.

Use exponential backoff with full jitter. Let `base` be the first cap and
`maximum` be the largest cap. For retry number `n`, starting at zero, select a
uniform delay in this range:

```text
0 .. min(maximum, base * 2^n)
```

Parse both `Retry-After` forms: delay seconds and HTTP date. Reject invalid or
negative values. Use the larger of the server delay and the local jitter delay.
Do not sleep past the operation deadline. Clamp arithmetic to prevent overflow.

Keep delay calculation pure. Pass the random sample and current time into it.
This small seam makes retry tests deterministic without a mock HTTP framework.

```rust
use std::time::Duration;

fn full_jitter_delay(
    base: Duration,
    maximum: Duration,
    retry_number: u32,
    sample: u64,
) -> Duration {
    let factor = 1_u128.checked_shl(retry_number).unwrap_or(u128::MAX);
    let cap = base.as_millis().saturating_mul(factor);
    let cap = cap.min(maximum.as_millis()).min(u128::from(u64::MAX)) as u64;
    Duration::from_millis(if cap == u64::MAX {
        sample
    } else {
        sample % (cap + 1)
    })
}

fn main() {
    assert!(full_jitter_delay(
        Duration::from_millis(100),
        Duration::from_secs(2),
        3,
        900,
    ) <= Duration::from_millis(800));
}
```

## Keep TLS verification on

Use the TLS backend that the workspace already selected. Apply these rules:

- Verify the certificate chain and the server name on every production
  connection.
- Load trust roots from one explicit source. Choose the platform store when the
  product must honor managed enterprise roots. Choose a bundled store when the
  product requires the same roots on every target.
- Fail startup or client construction when the required root store is empty.
- Keep certificate and hostname bypass APIs out of production features. Do not
  add `accept_invalid_certs`, an all-accepting verifier, or a test verifier to a
  runtime configuration path.
- Send SNI for a DNS name. Verify the original service name, not the resolved IP
  address.
- Keep private keys out of logs and error chains. Disable TLS key logging in
  production.
- Rebuild the client and drain old pooled connections after a trust-root,
  client-certificate, or private-key rotation.
- Use certificate pinning only when the product has a rotation and recovery
  plan. Ship at least one backup identity before the active identity changes.

Do not force a protocol-version policy that conflicts with the platform or the
service contract. Use the secure defaults of the maintained TLS backend. Raise
the minimum only when the deployment matrix proves that every peer supports it.

## Treat proxy and DNS as connection identity

Resolve proxy policy once per request destination. Support explicit proxy
configuration and the platform convention that the product requires. Parse
`NO_PROXY` with a maintained implementation. Do not copy a home-grown suffix
matcher into the client.

Never log proxy credentials. Keep origin credentials and proxy credentials in
separate configuration. Send `Proxy-Authorization` only to the proxy. Do not
reuse origin `Authorization` or cookies as proxy authentication. For HTTPS
through `CONNECT`, send origin headers and client certificates only inside the
verified end-to-end TLS tunnel. A plaintext forward proxy can inspect origin
requests, so do not send secrets through it unless the product policy accepts
that trust boundary.

Apply DNS changes to new connections. Do not assume that an existing pooled
connection follows a changed DNS record. Bound the DNS cache by the resolver
TTL or by a shorter product cap. Do not cache a failure forever. Preserve all
returned addresses and use the stack's IPv6 and IPv4 fallback strategy instead
of selecting the first address permanently.

Key a connection pool by every property that changes connection security or
routing:

```text
scheme + authority + proxy route + TLS identity + protocol settings
```

Do not create a client per request. Reuse one configured client for its policy
lifetime. Also do not keep an unbounded pool. Set per-host idle limits and an
idle lifetime. Let the protocol implementation detect stale connections.

HTTP/2 and HTTP/3 multiplex requests over a connection. A connection count is
not a request concurrency limit. Bound in-flight requests separately. Drain the
old pool when proxy, trust, identity, or protocol policy changes.

## Stream with hard limits and backpressure

Reject a declared body length that exceeds the route limit before allocation.
Do not trust the declaration as the only limit. Count actual decoded bytes as
chunks arrive, and stop when the count exceeds the limit.

Apply limits to the representation that the application consumes. A small
compressed body can expand into a large decoded body. If the stack exposes both
wire and decoded sizes, limit and record both.

Process large bodies as streams. Do not call a collect-to-bytes helper unless
the route limit is small enough to allocate safely. Put a bounded channel
between network reads and a slower consumer. Await capacity or cancel the
request when the channel is full. Never add an unbounded queue to hide
backpressure.

For uploads, make replayability explicit:

- A byte buffer is replayable.
- A file is replayable only when each attempt opens a new handle and starts at
  the same offset.
- A live channel, socket, decoder, or one-shot generator is not replayable.

Stop reading after cancellation, a body-limit error, or an expired deadline.
Release or reset the protocol stream as the library requires. Do not return a
connection to the pool when its protocol state is uncertain.

## Define cancellation at the network boundary

Cancellation answers what the local caller does. It cannot prove what a remote
server did. After any request bytes reach the network, a state-changing result
can be ambiguous.

Return an error variant that distinguishes these states when the application
needs recovery:

| State | Meaning |
|---|---|
| Not sent | No request bytes reached the transport |
| Outcome unknown | Some bytes were sent, but no final response arrived |
| Responded | A final response arrived |

Do not turn `Outcome unknown` into a safe retry. Require idempotency or an
application reconciliation step.

On client cancellation, stop producing the request body and release the
response body. Let the protocol stack send the correct stream reset or close.
On server cancellation, stop application work promptly, but do not claim that
a partial response can be withdrawn from the peer.

Use `rust-async-internals` to implement the cancellation tree and to verify that
dropped futures leave no locks, permits, or transactions behind.

## Bound server overload

Put a finite limit on accepted connections, incomplete request headers,
in-flight requests, request-body bytes, response-body bytes when applicable,
and queued work. Apply header read and keep-alive limits before application
admission. Apply a tighter concurrency limit to expensive routes.

Acquire the concurrency permit before expensive parsing, decompression,
database work, or downstream calls. Keep the wait queue bounded. When capacity
is exhausted, reject promptly with the protocol's overload response. For HTTP,
use `503 Service Unavailable` and a valid `Retry-After` when the server can give
a useful delay.

Do not combine a large buffer with a concurrency limit and call the result
bounded. The buffer is admitted work too. Include queued requests in the memory
and deadline budget.

## Shut down in a fixed order

Use this server shutdown sequence:

1. Mark the instance unready in service discovery or the load balancer.
2. Stop accepting new connections.
3. Stop admitting new requests on persistent connections.
4. Signal accepted handlers to finish.
5. Drain handlers and response bodies until the shutdown deadline.
6. Cancel the remaining work after the deadline.
7. Await task termination and release listeners, pools, and permits.

Keep one finite shutdown deadline. Do not apply a new full grace period at each
step. A signal storm must not restart the deadline.

For clients, stop accepting new operations, let eligible in-flight operations
finish within the deadline, then close pools. Do not drop a runtime while
network tasks still own sockets.

## Emit safe network diagnostics

Record bounded, low-cardinality fields:

- operation name or route template, not the full URL;
- method or protocol operation;
- attempt number and retry reason class;
- timeout phase and elapsed bucket;
- response status class;
- bytes sent and received;
- TLS protocol version and certificate error class;
- pool reuse, DNS result count, and proxy-used boolean.

Do not record URL queries, raw paths with identifiers, headers, cookies,
tokens, certificate contents, body fragments, proxy credentials, or peer error
text that can echo those values. Do not put the remote address into a metric
label. Use `rust-observability` to implement redaction and cardinality gates.

## Test deterministic seams

Test policy without a real public network. Use the smallest seam that exposes
the behavior under test:

- pause or inject monotonic time for deadlines and backoff;
- pass a fixed jitter sample into the delay calculation;
- run a local listener for partial writes, delayed headers, and stalled bodies;
- inject a resolver result for multiple addresses and DNS failures;
- generate a test CA and server certificate for TLS name and trust failures;
- use a counting body that fails if a retry reads it twice;
- expose pool-connect counts to prove reuse and policy-change drain;
- hold a concurrency permit to prove overload rejection;
- keep one handler open to prove bounded graceful shutdown.

Do not assert only the final error string. Assert the attempt count, elapsed
virtual time, bytes consumed, connection count, and error class.

Run the smallest affected tests first. Then run the workspace network tests
with retries disabled at the test runner level. A runner retry can hide a
flaky network contract.

## Failure triage

| Symptom | Likely cause | First check |
|---|---|---|
| Request exceeds its advertised timeout | Each retry received a fresh timeout | Trace one absolute deadline across attempts |
| POST executes twice | Method-only retry policy | Check idempotency and body replayability |
| Retry storm during outage | No jitter, no attempt cap, or ignored `Retry-After` | Inspect delay and total attempt metrics |
| TLS works only in development | Production root source differs or verifier bypass leaks into tests | Print root source and certificate error class |
| Requests use the old endpoint | Live pooled connection survives DNS change | Compare pool reuse and connect events |
| Memory grows under slow clients | Body collection or unbounded queue | Inspect decoded-byte and queue limits |
| HTTP/2 overloads the service | Connection limit is used as request limit | Inspect in-flight streams and route permits |
| Shutdown never finishes | New work is still admitted or each step resets grace | Trace admission close and one deadline |
| Metrics leak user data | Raw URI, header, or error text is a label | Apply the closed field vocabulary |

## Review checklist

- [ ] One absolute deadline covers all attempts, body work, and delay.
- [ ] Connect, write, first-byte, and read-idle failures stay distinct.
- [ ] Retry requires idempotency, replayability, and a transient result.
- [ ] Backoff uses bounded jitter and honors valid `Retry-After`.
- [ ] TLS verifies the chain and service name with an explicit root source.
- [ ] Proxy, DNS, TLS identity, and protocol settings participate in pool policy.
- [ ] Pool, body, queue, connection, and request concurrency are bounded.
- [ ] Cancellation preserves an outcome-unknown state after partial send.
- [ ] Shutdown stops admission, drains to one deadline, then cancels and joins.
- [ ] Diagnostics contain no raw URL, secret header, credential, or body data.
- [ ] Tests control time, jitter, DNS, TLS trust, and partial I/O as needed.

## Primary references

- [RFC 9110 HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html) defines
  idempotent methods and `Retry-After`.
- [RFC 6585 Additional HTTP Status Codes](https://www.rfc-editor.org/rfc/rfc6585.html)
  defines `429 Too Many Requests`.
- [RFC 8305 Happy Eyeballs Version 2](https://www.rfc-editor.org/rfc/rfc8305.html)
  defines IPv6 and IPv4 connection racing.
- [Tokio time](https://docs.rs/tokio/latest/tokio/time/) documents timeout
  cancellation and deterministic clock control.
- [rustls configuration](https://docs.rs/rustls/latest/rustls/struct.ConfigBuilder.html)
  documents certificate verification and trust-root configuration.
- [Tower ServiceBuilder](https://docs.rs/tower/latest/tower/struct.ServiceBuilder.html)
  documents framework controls for timeout, retry, limits, and load shedding.
