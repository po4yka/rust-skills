---
name: rust-database
description: Use when you build or review production Rust database code; prevent database pool exhaustion; define transaction rollback and transaction cancellation safety; order database migration deployment; retry a serialization failure safely; or run a schema integration test. Triggers on "database pool exhaustion", "transaction rollback", "database migration ordering", "transaction cancellation safety", "serialization failure", or "schema integration test".
license: BSD-3-Clause
---

# Rust Database

Use this skill for production database policy around an existing Rust driver or
ORM. Keep the database, driver, and migration tool that the workspace already
uses. Use their native pool and transaction types before you add wrappers.

This skill applies to SQL databases and transactional key-value databases.
Adapt database-specific error codes and DDL behavior to the selected engine.

## Boundaries

This skill owns these decisions:

- pool size, admission, acquisition deadlines, and shutdown;
- transaction ownership, commit, rollback, and external side effects;
- query and transaction behavior during cancellation;
- migration compatibility, serialization, and deployment order;
- isolation level, conflict classification, and bounded retries;
- tests against the real database engine and schema.

Use `rust-async-internals` for general future cancellation and task ownership.
Use `rust-networking` for HTTP deadlines and upstream retries. Use
`rust-observability` for telemetry implementation. Use `rust-security` for
credential storage and untrusted query input.

## Inspect the existing contract

Find the database boundary before you change it:

```bash
rg 'sqlx|diesel|tokio-postgres|rusqlite|deadpool|bb8|r2d2|sea_orm' \
  Cargo.toml Cargo.lock --glob '*.toml'
rg 'begin\(|transaction\(|commit\(|rollback\(|acquire\(' \
  --glob '*.rs' .
rg 'CREATE TABLE|ALTER TABLE|CREATE INDEX|migrate' \
  --glob '*.sql' --glob '*.rs' .
```

Record these facts before the edit:

| Fact | Required answer |
|---|---|
| Database | Engine and production major version |
| Driver | Crate, version, runtime, and TLS backend |
| Pool owner | Process object that creates and closes the pool |
| Connection budget | Server limit, reserved capacity, instance count, and pool maximum |
| Acquisition policy | Queue bound, acquisition timeout, and overload result |
| Query policy | Operation deadline and server-side statement limit |
| Transaction policy | Isolation, retryable errors, and maximum attempts |
| Migration owner | One job or process that serializes migrations |
| Deployment policy | Expand, migrate data, switch code, and contract order |
| Test engine | Exact engine major version used in production |

Do not infer a safe pool size from a library default. Do not infer transaction
semantics from an ORM method name. Confirm both in the driver and database
documentation that matches the locked versions.

## Budget database connections

Calculate a deployment-wide budget before you set one process pool:

```text
usable connections = server maximum - admin reserve - migration reserve - other clients
per-instance maximum = floor(usable connections / maximum live instances)
```

Include rolling deployment overlap, autoscaling maximum, workers, scheduled
jobs, and local sidecars in `maximum live instances`. Keep an admin reserve so
an operator can connect during saturation. Keep a migration reserve when the
migration runner uses a separate connection.

Set a finite pool maximum. Set a finite acquisition timeout shorter than the
request deadline. Use a bounded admission limit before pool acquisition when
the pool has no bounded waiter queue. Reject overload before work holds memory
or other scarce resources.

Create one pool per database identity and process. Do not create a pool per
request, task, repository object, or transaction. Key a pool by every property
that changes routing or identity:

```text
endpoint + database + role + TLS identity + session policy
```

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

Add jitter to connection maximum lifetime. Identical lifetimes can reconnect
all instances at the same time. Do not run a validation query before every
checkout unless the driver cannot detect broken sessions and measurements show
the query cost is acceptable.

Make startup policy explicit. A service that cannot work without its primary
database can fail startup after a bounded connection attempt. A service that
can serve degraded work can start without a connection, but it must report not
ready for database-dependent traffic. Never retry startup forever without a
deadline or a supervisor policy.

Release a connection as soon as its database work ends. Do not hold a pooled
connection while you wait for HTTP, a message broker, user input, a long CPU
task, or a retry delay. Close the pool during graceful shutdown after admitted
database work finishes.

Measure at least:

- checked-out, idle, and maximum connections;
- acquisition wait duration and acquisition timeouts;
- waiter or admission count and overload rejections;
- connection creation, retirement, and failure counts;
- query and transaction duration by bounded operation name;
- transaction commit, rollback, conflict, and retry counts.

Do not put SQL text, credentials, bind values, or high-cardinality identifiers
in metric labels.

## Keep one transaction in one async scope

The function that starts a transaction owns it until commit or rollback. Pass
`&mut Transaction` or the driver equivalent to helpers. Do not put a live
transaction in shared state. Do not move it into a detached task. Do not return
it across an API boundary unless that boundary exists only to compose database
operations in the same task.

Use this shape:

```text
begin
  read and lock the rows required by the invariant
  validate the invariant
  write all related rows
  write an outbox record when an external effect must follow commit
commit
publish or perform the external effect from the committed outbox
```

Use an explicit commit on the success path. Return the commit error. Do not
report success before commit succeeds. Roll back explicitly when the driver
provides useful rollback errors and the error path still has time. Otherwise
confirm that dropping the transaction schedules or completes rollback before
the connection returns to the pool.

Do not assume that `Drop` performs a synchronous rollback. Many async drivers
queue rollback work for the connection. The connection must not serve another
transaction until that work finishes. Test this behavior for the selected
driver.

Keep every domain invariant in one transaction or in a database constraint.
Prefer a unique, foreign-key, exclusion, or check constraint over a read-then-
write check that two transactions can pass at the same time.

Do not perform an irreversible external effect inside a database transaction.
The database can roll back after the effect succeeds. Use a transactional
outbox for messages and callbacks. Make the outbox consumer idempotent.

Treat a lost connection during `COMMIT` as an unknown outcome. The server might
have committed. Do not retry the transaction blindly. Reconcile by a stable
operation ID, an idempotency row, or a domain read that can prove the outcome.

## Make cancellation safe

A dropped Rust query future does not prove that the database stopped the
statement. The driver can cancel the server statement, close the session, wait
for the result, or leave cleanup to a connection worker. Confirm the actual
behavior for the locked driver and database versions.

Apply all of these controls:

1. Carry one caller deadline into pool acquisition and database work.
2. Set a server-side statement timeout below the caller deadline when the
   database supports it.
3. Set a lock-wait timeout below the statement timeout when lock waits must
   fail separately.
4. Keep the transaction lifetime inside the deadline.
5. Roll back or quarantine the connection after cancellation until protocol
   state is clean.
6. Do not return a connection to the idle pool while a cancelled statement can
   still produce protocol messages.

Set transaction-local timeouts where possible. A session-wide timeout can leak
into the next pool user when reset fails. If the driver requires a session
setting, set it on checkout and reset or discard the session before check-in.

Cancellation before commit must leave no partial database state. Cancellation
during commit has the same unknown-outcome rule as a lost connection. Keep the
stable operation ID available after the future is dropped so a caller or
reconciler can query the outcome.

Test cancellation at these points:

- while waiting for a pool connection;
- while waiting for a row or advisory lock;
- during a long statement;
- after writes but before commit;
- while commit is in flight.

After each test, prove that the pool regains capacity and that a new transaction
can execute. Also prove the expected rows and outbox records.

## Choose isolation from the invariant

Write the invariant and the conflicting schedule before you choose an
isolation level. Use the lowest level that the database documents as sufficient
for that schedule. Add a constraint or an explicit lock when it makes the
invariant simpler and cheaper.

| Invariant or operation | Typical control |
|---|---|
| One value must stay unique | Unique constraint, then classify its violation |
| Update only the version read | Version column in the `WHERE` clause |
| Update a known row set | Row locks in a stable order |
| Protect a missing row or range | Serializable isolation or engine-specific range lock |
| Maintain a cross-row predicate | Serializable isolation or a matching constraint |
| Claim queued jobs once | Atomic update or locking read with explicit skip policy |

Do not use `SELECT` followed by `UPDATE` as concurrency control at read
committed isolation unless a constraint, row lock, or compare-and-swap predicate
closes the race.

Acquire multiple locks in a stable order. Keep lock scopes short. A deadlock can
still occur through another code path, so classify and handle the database's
deadlock-victim error.

## Retry the complete transaction

Retry only an error that proves the current transaction did not commit and that
the database defines as transient. The common classes are serialization
failure and deadlock victim. Match structured database error codes. Do not
match error message text.

Examples that require an engine-specific check include PostgreSQL SQLSTATE
`40001` and `40P01`, MySQL error `1213` or SQLSTATE `40001`, and SQLite busy or
locked results. These codes do not make every operation retryable. Confirm the
selected engine's semantics.

Retry the complete transaction closure with a new transaction. Do not retry
only the failed statement. Preserve the same logical operation ID and stable
input across attempts. Re-read database state on every attempt.

Never retry these cases automatically:

- a constraint violation that reports a domain conflict;
- invalid SQL, invalid data, permission failure, or missing schema;
- cancellation or an exhausted caller deadline;
- a lost connection during commit or any other unknown commit outcome;
- a transaction that performed a non-idempotent external side effect.

Count the first execution as attempt one. Use a small finite attempt maximum,
an absolute operation deadline, exponential backoff, and jitter. Release the
failed transaction and its connection before the delay. Bound retries across
the process so an outage does not create a retry storm.

Keep retry classification pure and test it separately from the driver:

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DbFailure {
    Serialization,
    DeadlockVictim,
    Constraint,
    CommitOutcomeUnknown,
    Cancelled,
}

fn can_retry(failure: DbFailure, attempt: u8, maximum_attempts: u8) -> bool {
    attempt < maximum_attempts
        && matches!(failure, DbFailure::Serialization | DbFailure::DeadlockVictim)
}

fn main() {
    assert!(can_retry(DbFailure::Serialization, 1, 3));
    assert!(can_retry(DbFailure::DeadlockVictim, 2, 3));
    assert!(!can_retry(DbFailure::Serialization, 3, 3));
    assert!(!can_retry(DbFailure::Constraint, 1, 3));
    assert!(!can_retry(DbFailure::CommitOutcomeUnknown, 1, 3));
    assert!(!can_retry(DbFailure::Cancelled, 1, 3));
}
```

## Deploy migrations in compatible phases

Use one migration history. Store checksums. Never edit a migration that ran in
any shared environment. Add a forward migration that corrects it.

Serialize migration execution with one deployment job or a database advisory
lock. Do not let every application instance race to migrate on startup. Give
the runner a finite lock wait and statement timeout. Record the applied
version, checksum, start time, finish time, and failure.

Use this order for a rolling deployment:

1. **Expand:** add nullable columns, tables, indexes, or compatible constraints.
2. **Backfill:** update old rows in bounded batches that can resume.
3. **Switch:** deploy code that reads the new form and stops depending on the
   old form. Dual-write only when the transition needs it.
4. **Verify:** prove backfill completion and new-code adoption with queries and
   metrics.
5. **Contract:** remove old columns, constraints, indexes, and compatibility
   code in a later deployment.

Do not add a required column with no safe value while old binaries still write
the table. Do not rename or drop an object while old binaries still use it.
Keep the expand state compatible with both the old and new application.

Build large indexes with the engine's online or concurrent mode when required.
Some engines prohibit that operation inside a transaction. Put
non-transactional DDL in its own migration and make its restart behavior
explicit. Inspect invalid or partial artifacts after a failed run.

For a destructive migration, verify a restore path and measure the lock and
rewrite cost on production-shaped data. A rollback file is not a backup. Data
removed by a down migration can be unrecoverable.

Use the repository's migration tool. For SQLx workspaces, useful checks include:

```bash
sqlx migrate info --database-url "$DATABASE_URL"
sqlx migrate run --database-url "$DATABASE_URL"
cargo sqlx prepare --workspace --check
```

Run mutation commands only against an authorized disposable test database or
an explicitly authorized environment. Do not print `DATABASE_URL`.

## Test the real schema

Run database integration tests against the same engine and major version as
production. An in-memory substitute does not prove SQL syntax, isolation,
locking, collation, extensions, or migration behavior.

Use an isolated database or schema per test worker. Give each one a generated,
bounded identifier. Apply migrations from an empty database. Run application
queries through the production repository or data-access code. Drop the test
database or schema after the pool closes.

Do not rely only on transaction rollback for test isolation. It cannot model
code that opens another connection, commits internally, or tests migrations.
Bound parallel workers by the database connection budget.

The minimum CI matrix is:

- migrate an empty database to the current version;
- start from the previous released schema and migrate to the current version;
- run repository integration tests on the migrated schema;
- run one concurrent test for each protected business invariant;
- inject one serialization conflict or deadlock and prove bounded retry;
- cancel a transaction and prove rollback and pool recovery;
- run a schema or query metadata freshness check when the driver supports it.

Use the workspace's normal test command. Select the database tests explicitly
when the full suite is too slow:

```bash
cargo test --locked --test database -- --test-threads=4
```

Treat the worker count as a connection-budget input, not as a constant to copy.
Do not mark a database test as flaky because it exposed an unbounded retry,
missing lock, shared schema, or unsafe cleanup.

## Triage failures

| Symptom | Likely cause | First proof | Fix |
|---|---|---|---|
| Pool acquisition timeout rises | Connections are held too long or total budget is too small | Compare checked-out count, wait duration, and query duration | Shorten hold scope, bound admission, then recalculate pool budget |
| Database rejects new sessions during deploy | Rolling instances exceed the deployment budget | Count pools across old and new instances | Lower per-instance maximum or server instance overlap |
| Pool stays smaller after cancellation | Cancelled query or rollback still owns a connection | Cancel at each phase and observe pool capacity | Await cleanup or discard the dirty connection |
| Rows changed although caller saw an error | Commit outcome is unknown | Query by stable operation ID | Reconcile; do not repeat the transaction blindly |
| Deadlocks repeat on every attempt | Lock order differs or retry repeats immediately | Capture bounded operation names and lock order | Use stable lock order and jittered bounded retry |
| Serialization failures surge | Contention or transaction scope grew | Compare conflict rate, duration, and touched rows | Shorten scope, reduce hot rows, keep bounded retry |
| Migration blocks application traffic | DDL takes a strong lock or rewrites data | Measure on production-shaped data | Split the change and use online or batched operations |
| New binary fails before migration completes | Deploy order is incompatible | Reproduce old and new binaries on expand schema | Restore expand-switch-contract compatibility |
| Migration passes locally but fails in CI | Test engine or extension differs | Compare engine version and enabled extensions | Match production engine and provision extensions |
| Tests fail only in parallel | Workers share schema or exceed connection budget | Run with one worker, then inspect names and pools | Isolate schemas and bound parallelism |

## Completion checklist

- [ ] The deployment-wide connection calculation includes rolling overlap.
- [ ] Pool size, admission, acquisition, query, lock, and shutdown waits are finite.
- [ ] One async scope owns each transaction through explicit commit or rollback.
- [ ] External effects use an idempotent outbox or occur after commit.
- [ ] Cancellation leaves the protocol clean and restores pool capacity.
- [ ] Unknown commit outcomes reconcile by a stable operation ID.
- [ ] Isolation and locks follow a written invariant and conflicting schedule.
- [ ] Retry uses structured codes, the complete transaction, a deadline, and a finite attempt count.
- [ ] Migrations are serialized and compatible with rolling old and new binaries.
- [ ] Destructive and non-transactional DDL has a measured recovery plan.
- [ ] CI migrates empty and previous-release schemas on the production engine version.
- [ ] Integration tests cover conflicts, cancellation, rollback, and pool recovery.

Report the database and driver versions, pool calculation, transaction and
retry policy, migration phases, integration test topology, commands run, and
any production-only behavior that remains unverified.
