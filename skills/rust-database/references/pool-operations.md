# Pool operations

Pool controls, startup behavior, and pool metrics behind "Budget database
connections" in `SKILL.md`. Engine and crate defaults are in
`engine-and-driver-notes.md`.

## Pool controls

Use these pool controls deliberately:

| Control | Rule |
|---|---|
| Maximum size | Fit the deployment-wide connection budget |
| Minimum idle | Keep small or zero unless cold-connect latency is measured |
| Acquire timeout | Fail before the caller deadline expires |
| Idle timeout | Reclaim unused sessions without connection churn |
| Maximum lifetime | Rotate sessions and credentials with bounded jitter |
| Connect timeout | Bound DNS, TCP, TLS, and database authentication |
| Health check | Reject a dead session before application work uses it |

Vary the maximum lifetime per instance when the pool has no jitter option.
Identical lifetimes can reconnect all instances at the same time. Keep the
driver's checkout health check: sqlx pings an idle connection before it returns
it (`test_before_acquire`, default `true`). Turn it off only when a measurement
shows that its cost matters. Do not add a second validation query on top of it.

## Startup

Bound the startup connection attempt. Fail startup when the service cannot work
without the database. Otherwise start and report not ready for
database-dependent traffic. Do not retry startup forever without a deadline or
a supervisor policy.

## Metrics

Measure checked-out, idle, and maximum connections; acquisition wait and
timeouts; overload rejections; connection creation, retirement, and failure
counts; query and transaction duration by bounded operation name; and commit,
rollback, conflict, and retry counts. Do not put SQL text, credentials, bind
values, or high-cardinality identifiers in metric labels.
