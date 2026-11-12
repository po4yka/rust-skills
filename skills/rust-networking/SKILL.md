---
name: rust-networking
description: Use when building or reviewing a production Rust network client or server with reqwest, hyper, axum, tower-http, tonic, or rustls; setting an HTTP timeout or deadline budget; retrying with Retry-After and jitter; keeping TLS verification on; configuring a connection pool, proxy, or DNS; enforcing a response body limit or overload bound; or adding graceful shutdown. Not for select! or task cancel safety; use `rust-async-internals`.
license: BSD-3-Clause
---

# Rust Networking

Apply this policy to HTTP, gRPC, WebSocket, and custom TCP clients and servers.
Use the controls of the stack that the workspace already uses; do not replace
the framework to get one middleware type.

Use these skills, when they are installed, for adjacent work:
`rust-async-internals` for `select!`, task ownership, cancel safety, and runtime
configuration; `rust-observability` for tracing, metrics, and exporters;
`rust-security` for dependency advisories and untrusted-input parser hardening.

## Start from one operation contract

Record these decisions next to the configuration before you tune settings:

| Field | Required decision |
|---|---|
| Operation deadline | Maximum wall-clock time for all attempts and delays |
| Phase caps | DNS, connect, write idle, first-byte, and read idle caps (see "Use one absolute deadline") |
| Retry attempts | Total attempts, including the first attempt |
| Retry eligibility | Operation semantics, replayable body, and retryable result |
| Response limit | Maximum decoded bytes accepted by the caller |
| Concurrency limit | Maximum admitted work per process, route, or upstream |
| Server header limit | Maximum header bytes, field count, and read time |
| Server idle limits | Keep-alive, request-body, and response-write idle caps |
| Shutdown grace | Maximum time allowed for accepted work to drain |

Derive timeout values from the caller's deadline and the service latency
objective, not from another service. Keep each one configurable, with a finite
production default.

## Set the limits the stack leaves open

An unset limit compiles and passes tests, then fails under a slow or hostile
peer. Set each one explicitly:

| Stack | Default | Consequence |
|---|---|---|
| reqwest 0.13 async `Client` | No `timeout`, `connect_timeout`, or `read_timeout`; `pool_max_idle_per_host` is `usize::MAX` | A stalled peer holds a request forever; the idle pool has no bound |
| reqwest `Response::bytes`, `text`, `json` | Collect the whole body with no size limit | A large response exhausts memory |
| hyper 1.x HTTP/1 server | `header_read_timeout` (30 s) acts only after `Builder::timer`; a configured value with no timer panics | Slow-header clients hold connections |
| `axum::serve` 0.8 | Builds its hyper builder with no timer | No header-read timeout at all |
| axum `with_graceful_shutdown` | Waits for open connections with no deadline | One open request stalls shutdown |
| tower-http `TimeoutLayer::new` | Deprecated since 0.6.7; answers `408` | A client can repeat even a `POST` that the handler already ran |
| tonic 0.14 `Endpoint` | No connect timeout; `timeout` does not send `grpc-timeout` | The server never sees the deadline, so it cannot stop at it or pass it downstream |
| rustls 0.23 | Zero or two provider features (or `custom-provider`) and no installed provider | `ClientConfig::builder()` panics at run time |

Read [references/stack-defaults.md](references/stack-defaults.md) when the
workspace uses one of these crates: it has the reqwest 0.13 upgrade changes,
working client and server setups, and the rustls and Android TLS setup.

## Verify the configuration

Run these checks when you add or review network configuration. Review each hit;
a hit is not always a defect.

```bash
rg -n --type rust 'danger_accept_invalid|tls_danger_|\.dangerous\(\)|tls_sslkeylogfile\(true\)|KeyLogFile|DefaultBodyLimit::disable|\bTimeoutLayer::new|axum::serve\(|with_graceful_shutdown\(|\breqwest::get\(|\bClient(Builder)?::(new|builder)\(\)|\.(bytes|text|json)\(\)\.await|\.json::<'
if cargo tree --locked -i rustls --depth 0 > /dev/null 2> rustls.err; then
  cargo tree --locked -e features -i rustls --prefix none | grep -oE '^rustls feature "(ring|aws_lc_rs|custom-provider)"' | sort -u
elif ! grep -q 'did not match any packages' rustls.err; then cat rustls.err; exit 1; fi
cargo deny --config deny.toml --locked check advisories
```

| Check | Proves | Does not prove |
|---|---|---|
| `rg` | Each bypass, key log, unbounded body, `408` timeout, and unbounded serve or client construction is visible | That the configured values fit the contract |
| `cargo tree` | Which rustls provider features are on; it skips a graph with no rustls. Output other than one `ring` or `aws_lc_rs` line means `main` must install a provider | That the provider is installed before first TLS use |
| `cargo deny` | No known vulnerability in rustls, h2, hyper, quinn, or the rest of the graph. An unsound advisory in a transitive crate fails only with `unsound = "all"` (the `rust-security` skill owns this `deny.toml` policy). Without cargo-deny, run `cargo audit --deny warnings` | Protocol correctness |

A green grep does not prove the timing contract; the tests in
`references/test-seams.md` do. The work is complete when each contract field and each
stack-defaults row has a finite, configurable, tested value, and the TLS root
source, the pool key, the outcome-unknown error state, and the diagnostics
field list match their sections. In a review, each gap is a finding.

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
| Shutdown never finishes | New work is still admitted, each step resets grace, or axum `with_graceful_shutdown` has no outer deadline | Trace admission close and one deadline |
| Slow clients exhaust server connections | `axum::serve`, or hyper with no timer, has no header-read timeout | Send zero bytes and a partial header; time each close |
| Panic "Could not automatically determine the process-level CryptoProvider" | Zero or two provider features (or `custom-provider`) and no installed provider | Run the `cargo tree` check; install one provider in `main` |
| Metrics leak user data | Raw URI, header, or error text is a label | Apply the closed field vocabulary |

## Keep TLS verification on

Use the TLS backend that the workspace already selected. Apply these rules:

- Verify the certificate chain and the server name on every production
  connection.
- Load trust roots from one explicit source. Choose the platform store when the
  product must honor managed enterprise roots. Choose a bundled store when the
  product requires the same roots on every target. A reqwest 0.12 `rustls-tls`
  build (bundled webpki roots) silently moves to the platform verifier on 0.13;
  call `tls_certs_only(roots)` to keep a bundled or private set.
- Fail startup or client construction when the required root store is empty.
- Keep certificate and hostname bypass APIs (the `rg` check above lists them)
  out of production code paths. A test verifier must not be reachable from
  runtime configuration.
- Send SNI for a DNS name. Verify the original service name, not the resolved IP
  address.
- Keep private keys out of logs and error chains. Never enable key logging in
  production: reqwest `tls_sslkeylogfile(true)` and rustls `KeyLogFile` write
  session secrets to the file that `SSLKEYLOGFILE` names.
- Rebuild the client and drain old pooled connections after a trust-root,
  client-certificate, or private-key rotation.
- Use certificate pinning only when the product has a rotation and recovery
  plan. Ship at least one backup identity before the active identity changes.

Do not force a protocol-version policy that conflicts with the platform or the
service contract. Use the secure defaults of the maintained TLS backend. Raise
the minimum only when the deployment matrix proves that every peer supports it.

## Use one absolute deadline

Create one monotonic deadline at the operation boundary. Carry it through DNS,
connect, proxy negotiation, TLS, every request attempt, response streaming, and
retry delay. Do not restart the full timeout after a retry.

Before each phase, calculate this duration:

```text
phase allowance = min(configured phase cap, operation deadline - monotonic now)
```

Fail before the phase starts when no time remains. Report which phase consumed
the budget. Do not report every deadline failure as `connect timeout`. Read
[references/deadlines-and-retries.md](references/deadlines-and-retries.md) when
you set the phase caps: it gives the start, the end, and the failure mode of
each cap.

On a server, start the header-read deadline at accept, before protocol
detection: a client that sends nothing must not hold a connection slot.

An idle timeout is not a total transfer timeout. Reset it only after useful
progress. A peer that sends one byte before every idle timeout can still consume
the operation deadline, so enforce both. With tower-http, pair
`RequestBodyTimeoutLayer` (idle) with `RequestBodyDeadlineLayer` (total,
tower-http 0.7+). With reqwest, pass the remaining time to
`RequestBuilder::timeout` on every attempt.

Use `tokio::time::timeout_at` or the runtime equivalent when the stack does not
accept a deadline directly. Dropping the timed future cancels it, so check its
cancel safety.

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

Also bound retries per upstream across the process with a retry budget
(`tower::retry::budget::TpsBudget` in a tower stack); read
[references/deadlines-and-retries.md](references/deadlines-and-retries.md) when
you add one.

Use exponential backoff with full jitter. Parse both `Retry-After` forms: delay
seconds and HTTP date. Reject invalid or negative values. Use the larger of the
server delay and the local jitter delay. Do not sleep past the operation
deadline. Clamp arithmetic to prevent overflow. Keep the delay calculation pure:
pass the random sample and current time into it, so a retry test needs no mock
HTTP framework. Read
[references/deadlines-and-retries.md](references/deadlines-and-retries.md) when
you write the delay function: it has the jitter formula and a tested
implementation.

## Stream with hard limits and backpressure

Reject a declared body length that exceeds the route limit before allocation.
Do not trust the declaration as the only limit. Count actual decoded bytes as
chunks arrive, and stop when the count exceeds the limit.

Apply limits to the representation that the application consumes. A small
compressed body can expand into a large decoded body. If the stack exposes both
wire and decoded sizes, limit and record both.

Process large bodies as streams. Do not call a collect-to-bytes helper unless
the route limit is small enough to allocate safely. On a server, use
`http_body_util::Limited`, `axum::body::to_bytes(body, limit)`, or a per-route
`DefaultBodyLimit::max(n)`. Put a bounded channel between network reads and a
slower consumer. Await capacity or cancel the request when the channel is full.
Never add an unbounded queue to hide backpressure.

For uploads, make replayability explicit. A byte buffer is replayable. A file is
replayable only when each attempt opens a new handle and starts at the same
offset. A live channel, socket, decoder, or one-shot generator is not
replayable.

Stop reading after cancellation, a body-limit error, or an expired deadline.
Release or reset the protocol stream as the library requires. Do not return a
connection to the pool when its protocol state is uncertain.

## Emit safe network diagnostics

Record bounded, low-cardinality fields: route template or operation name (not
the full URL), method, attempt number, retry reason class, timeout phase,
elapsed bucket, status class, bytes sent and received, TLS version, certificate
error class, pool reuse, DNS result count, and a proxy-used boolean. Do not
record URL queries, raw paths with identifiers, headers, cookies, tokens,
certificate contents, body fragments, proxy credentials, or peer error text that
can echo those values. Do not put the remote address into a metric label. Use
`rust-observability`, when it is installed, for redaction and cardinality gates.

## Conditional references

Test policy without a real public network.

| Read | When |
|---|---|
| `references/cancellation.md` | A caller can cancel a state-changing request, or the application must recover from an `Outcome unknown` result |
| `references/proxy-and-dns.md` | You key or reuse a connection pool, or configure a proxy, `NO_PROXY`, a resolver, or a DNS cache |
| `references/overload-and-shutdown.md` | You set server admission, concurrency, queue, or handler-timeout limits, or add or review graceful shutdown |
| `references/test-seams.md` | You write a network policy test: it maps each control to the smallest seam, and gives the paused-clock and test-run rules |
