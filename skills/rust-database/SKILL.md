---
name: rust-database
description: Use when building or reviewing production Rust database code (sqlx, diesel, tokio-postgres, rusqlite, deadpool, bb8) for database pool exhaustion, transaction rollback, transaction cancellation safety, a serialization failure or deadlock retry, database migration ordering in a rolling deploy, a schema integration test, or a sqlx 0.9 upgrade that hits SqlSafeStr or AssertSqlSafe.
license: BSD-3-Clause
---

# Rust Database

Keep the database, driver, and migration tool that the workspace already uses.
Use their native pool and transaction types before you add wrappers. Adapt
error codes and DDL behavior to the selected engine.

Other skills own neighboring work, when installed: `rust-async-internals`
(future cancellation and task ownership), `rust-networking` (HTTP deadlines and
retries), `rust-observability` (telemetry), and `rust-security` (the
dependency advisory gate).

Read the section of
[references/engine-and-driver-notes.md](references/engine-and-driver-notes.md)
for the engine and crates that `Cargo.lock` names when you set a pool option,
a timeout, a retry code, or a migration command.

## Inspect the existing contract

Find the database boundary before you change it:

```bash
rg -g 'Cargo.toml' -g 'Cargo.lock' \
  'sqlx|diesel|tokio-postgres|rusqlite|deadpool|bb8|r2d2|sea-orm' .
rg 'begin\(|begin_with\(|transaction\(|commit\(|rollback\(|acquire\(' --glob '*.rs' .
rg 'CREATE TABLE|ALTER TABLE|CREATE INDEX|migrate' --glob '*.sql' --glob '*.rs' .
rg -U -i 'AssertSqlSafe|sql_query\(|format!\(\s*r?#*"\s*(select|insert|update|delete|with)\b' --glob '*.rs' .
```

Record these facts before you change pool, transaction, retry, or migration
policy:

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

Do not infer a safe pool size or wait from a library default. A deadpool
default pool grows with the host CPU count, and it has no wait timeout, so
`Pool::get()` can wait forever: set `timeouts.wait` below the caller deadline.
Do not infer transaction semantics from an ORM method name. Confirm pool and
transaction behavior in the driver and database documentation for the locked
versions.

## Triage failures

| Symptom | Likely cause | First proof | Fix |
|---|---|---|---|
| Pool acquisition timeout rises | Connections are held too long or total budget is too small | Compare checked-out count, wait duration, and query duration | Shorten hold scope, bound admission, then recalculate pool budget |
| Database rejects new sessions during deploy | Rolling instances exceed the deployment budget | Count pools across old and new instances | Lower per-instance maximum or server instance overlap |
| Pool stays smaller after cancellation | Cancelled query or rollback still owns a connection | Cancel at each phase and observe pool capacity | Await cleanup or discard the dirty connection |
| Writes succeed but later vanish, with no error | An open transaction returned to the pool (sqlx before 0.9.0, drop during `BEGIN`) | `cargo tree --locked -i sqlx-core --depth 0` shows a version below 0.9.0; `pg_stat_activity` shows `idle in transaction` sessions | Upgrade to sqlx 0.9.0 or later, or stop cancelling `begin()` |
| Rows changed although caller saw an error | Commit outcome is unknown | Query by stable operation ID | Reconcile; do not repeat the transaction blindly |
| Deadlocks repeat on every attempt | Lock order differs or retry repeats immediately | Capture bounded operation names and lock order | Use stable lock order and jittered bounded retry |
| Serialization failures surge | Contention or transaction scope grew | Compare conflict rate, duration, and touched rows | Shorten scope, reduce hot rows, keep bounded retry |
| SQLite returns `SQLITE_BUSY` at once despite `busy_timeout` | A deferred transaction tried to upgrade from read to write | Check how the transaction begins | Begin write transactions with `BEGIN IMMEDIATE` |
| Migration blocks application traffic | DDL takes a strong lock or rewrites data | Measure on production-shaped data | Split the change and use online or batched operations |
| `CREATE INDEX CONCURRENTLY cannot run inside a transaction block` | The migration tool wraps the file in a transaction | Read the migration tool's transaction rule | Move the statement to its own non-transactional migration |
| New binary fails before migration completes | Deploy order is incompatible | Reproduce old and new binaries on expand schema | Restore expand-switch-contract compatibility |
| Migration passes locally but fails in CI | Test engine or extension differs | Compare engine version and enabled extensions | Match production engine and provision extensions |
| Tests fail only in parallel | Workers share schema or exceed connection budget | Run with one worker, then inspect names and pools | Isolate schemas and bound parallelism |

## Verify and finish

Run the database test target while you iterate. Select it explicitly when the
full suite is too slow. Run the other commands once before merge or at review.
Skip the two sqlx commands when `Cargo.lock` has no sqlx.

```bash
cargo test --locked --test database -- --test-threads=4
cargo sqlx prepare --workspace --check   # sqlx only
cargo tree --locked -i sqlx-core --depth 0   # sqlx only
cargo deny --config deny.toml --locked check advisories
```

- Treat the test worker count as a connection-budget input, not a constant to
  copy. A green run does not prove lock duration or rewrite cost on production
  data volumes.
- `prepare --check` exits 1 when the `.sqlx` query metadata is
  stale.
- `cargo tree` prints the locked sqlx version for the 0.9.0 floor in "Make
  cancellation safe".
- `cargo deny` with `unsound = "all"` (or `cargo audit --deny warnings`) gates
  the driver crates against known advisories. The `rust-security` skill owns
  that policy.

Run a mutating migration command (`sqlx migrate run`, a down migration, or a
DDL script) only against a disposable test database or an environment the user
has authorized, because a migration can destroy data. Do not print
`DATABASE_URL` or pass it as a command-line argument, where process listings
expose it.

Before merge, confirm each item:

- [ ] The budget includes rolling overlap. Admission, acquisition, query, lock, and shutdown waits are finite.
- [ ] One async scope owns each transaction. External effects use an idempotent outbox or follow commit.
- [ ] Cancellation restores a clean protocol and pool capacity. Unknown commit outcomes reconcile by operation ID.
- [ ] Isolation follows a written invariant. Retry matches exact codes, reruns the whole transaction, and is bounded.
- [ ] Every value is bound. Every `AssertSqlSafe` or raw SQL string names its trusted source.
- [ ] Migrations are serialized and rolling-compatible. Destructive or non-transactional DDL has a recovery plan.
- [ ] CI on the production engine covers empty and previous-release schemas, conflicts, cancellation, and pool recovery.
- [ ] The advisory gate passes.

Report the database and driver versions, pool calculation, transaction and
retry policy, migration phases, integration test topology, commands run, and
any production-only behavior that remains unverified.

## Keep SQL text static

Bind every value. Do not build SQL text from untrusted input with `format!`.

sqlx 0.9 `query*()` functions take `impl SqlSafeStr`. A `&'static str`
implements it; a runtime `String` does not, so `query(&sql)` stops compiling
after the upgrade. Do not wrap the string in `AssertSqlSafe` only to make it
compile, because the wrapper asserts that the text is safe without proof. Build
dynamic SQL with `QueryBuilder`. `QueryBuilder::new` and `push` accept any
string and do not escape. Start from a static string, use `push_bind` for every
value, and use `push` only for a fragment from a fixed allowlist, such as a
column name.
Give every remaining `AssertSqlSafe(` and diesel `sql_query(` a comment that
names where its text comes from.

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
provides useful rollback errors and the error path still has time. Do not
assume that `Drop` performs a synchronous rollback: many async drivers queue
it. sqlx runs the queued rollback on the next use of the connection, including
its return to the pool. Test the drop behavior of the selected driver.

Keep every domain invariant in one transaction or in a database constraint.

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

Require sqlx 0.9.0 or later when a timeout, `select!`, or an aborted request
can cancel `begin()`. Before 0.9.0, a transaction dropped during `BEGIN` could
return to the pool still open, and later writes on that connection could stay
uncommitted and be lost without an error.

Apply all of these controls:

1. Carry one caller deadline into pool acquisition and database work.
2. Set a server-side statement timeout below the caller deadline when the
   database supports it.
3. Set a lock-wait timeout below the statement timeout when lock waits must
   fail separately.
4. Keep the transaction lifetime inside the deadline. PostgreSQL 17 adds
   `transaction_timeout`; it terminates the session, so expect a dead pooled
   connection after it fires.
5. Do not let a connection serve another caller while a cancelled statement or
   a queued rollback can still produce protocol messages. Confirm that the
   driver drains, rolls back, or closes it. Discard the connection yourself when
   the driver does not.

Send a server-side cancel explicitly (tokio-postgres `Client::cancel_token()`)
when a long statement must stop, unless the driver documents that a drop sends
one. Keep the statement timeout as the real bound: the server does not report
whether a cancel worked.

Set transaction-local timeouts where possible. A session-wide timeout can leak
into the next pool user when reset fails. If the driver requires a session
setting, set it on checkout and reset or discard the session before check-in.

Cancellation before commit must leave no partial database state. Cancellation
during commit has the same unknown-outcome rule as a lost connection. Keep the
stable operation ID available after the future is dropped so a caller or
reconciler can query the outcome.

Test cancellation at every phase, from the pool wait to a commit in flight.
Read [references/schema-tests.md](references/schema-tests.md) when you write
these tests; it lists the cancel points and what to prove after each one.

## Retry the complete transaction

Retry only an error that proves the current transaction did not commit and that
the database defines as transient. The common classes are serialization
failure and deadlock victim. Match structured database error codes. Do not
match error message text.

Retryable examples: PostgreSQL SQLSTATE `40001` and `40P01`, MySQL error `1213`
(SQLSTATE `40001`), and SQLite `SQLITE_BUSY`. Match exact codes, not a class
prefix: PostgreSQL `40003` means statement completion unknown.

Report a lock-wait timeout (PostgreSQL `55P03`, MySQL `1205`) by default. Retry
it only after a full rollback, inside the remaining caller deadline and attempt
limit. MySQL `1205` rolls back only the statement by default
(`innodb_rollback_on_timeout=OFF`), so roll back the transaction before you act
on it. PostgreSQL documents that `23505` or `23P01` can be a serialization
failure when the transaction derived the key from its own reads. Let only that
call site opt into a retry.

Retry the complete transaction closure with a new transaction. Do not retry
only the failed statement. Preserve the same logical operation ID and stable
input across attempts. Re-read database state on every attempt.

Never retry these cases automatically, because the outcome is known to be
permanent, the caller has given up, or a repeat can apply the effect twice:

- a constraint violation that reports a domain conflict;
- invalid SQL, invalid data, permission failure, or missing schema;
- cancellation, a statement timeout (PostgreSQL `57014`), or an exhausted
  caller deadline;
- a lost connection during commit or any other unknown commit outcome;
- a transaction that performed a non-idempotent external side effect.

Count the first execution as attempt one. Use a small finite attempt maximum,
an absolute operation deadline, exponential backoff, and jitter. Release the
failed transaction and its connection before the delay. Bound retries across
the process so an outage does not create a retry storm.

Keep classification and retry policy pure and test them separately from the
driver. Get the code with `err.as_database_error().and_then(|e| e.code())` in
sqlx, or `err.code()` in tokio-postgres. A lost connection has no SQLSTATE;
classify it at the call site, where you know whether `COMMIT` was in flight.
Read [references/isolation-and-retry.md](references/isolation-and-retry.md)
when you write the classifier; it has a runnable PostgreSQL example.

## Deploy migrations in compatible phases

Use one migration history. Store checksums. Never edit a migration that ran in
any shared environment, because its checksum and applied state no longer match.
Add a forward migration that corrects it.

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
Put non-transactional DDL, such as PostgreSQL `CREATE INDEX CONCURRENTLY`, in
its own migration (sqlx: first line `-- no-transaction`) and make its restart
behavior explicit. Inspect invalid or partial artifacts after a failed run.
MySQL DDL commits implicitly, so a multi-statement MySQL migration is not
atomic.

For a destructive migration, verify a restore path and measure the lock and
rewrite cost on production-shaped data. A rollback file is not a backup. Data
removed by a down migration can be unrecoverable.

Use the repository's migration tool. The target rules in "Verify and finish"
apply to every mutating command. Read the
[sqlx section](references/engine-and-driver-notes.md#sqlx) of the reference
for the `sqlx migrate` commands when the repository uses sqlx.

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

Use a bounded admission limit before pool acquisition when the pool has no
bounded waiter queue. Reject overload before work holds memory or other scarce
resources.

Create one pool per database identity and process. Do not create a pool per
request, task, repository object, or transaction. Key a pool by every property
that changes routing or identity: endpoint, database, role, TLS identity, and
session policy.

Release a connection as soon as its database work ends. Do not hold a pooled
connection while you wait for HTTP, a message broker, user input, a long CPU
task, or a retry delay. Close the pool during graceful shutdown after admitted
database work finishes.

Read [references/pool-operations.md](references/pool-operations.md) when you
set pool timeouts, lifetime, health checks, or startup behavior, or add pool
metrics.

## Choose isolation from the invariant

Write the invariant and the conflicting schedule before you choose an
isolation level. Use the lowest level that the database documents as sufficient
for that schedule. Prefer a unique, foreign-key, exclusion, or check
constraint, or an explicit lock, when it makes the invariant simpler and
cheaper. Read
[references/isolation-and-retry.md](references/isolation-and-retry.md) when
you pick the control for an invariant.

Do not use `SELECT` followed by `UPDATE` as concurrency control at read
committed isolation unless a constraint, row lock, or compare-and-swap predicate
closes the race, because two transactions can pass the same check at the same
time.

Acquire multiple locks in a stable order. Keep lock scopes short. A deadlock can
still occur through another code path, so classify and handle the database's
deadlock-victim error.

## Test the real schema

Run database integration tests against the same engine and major version as
production. An in-memory substitute does not prove SQL syntax, isolation,
locking, collation, extensions, or migration behavior.

Use an isolated database or schema per test worker. Do not rely only on
transaction rollback for test isolation. It cannot model code that opens
another connection, commits internally, or tests migrations. Read
[references/schema-tests.md](references/schema-tests.md) when you set up test
databases or the CI matrix.

Do not mark a database test as flaky because it exposed an unbounded retry,
missing lock, shared schema, or unsafe cleanup.
