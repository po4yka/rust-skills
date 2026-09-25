# Schema integration tests

Test database setup, the minimum CI matrix, and cancellation test points behind
"Test the real schema" and "Make cancellation safe" in `SKILL.md`.

## Isolated test databases

Use an isolated database or schema per test worker. Give each one a generated,
bounded identifier. Apply migrations from an empty database. Run application
queries through the production repository or data-access code. Drop the test
database or schema after the pool closes.

## Minimum CI matrix

- migrate an empty database to the current version;
- start from the previous released schema and migrate to the current version;
- run repository integration tests on the migrated schema;
- run one concurrent test for each protected business invariant;
- inject one serialization conflict or deadlock and prove bounded retry;
- cancel a transaction and prove rollback and pool recovery;
- run a schema or query metadata freshness check when the driver supports it
  (sqlx: `cargo sqlx prepare --workspace --check`, which exits 1 when `.sqlx`
  is stale).

## Cancellation test points

Test cancellation at these points:

- while waiting for a pool connection;
- while `BEGIN` runs;
- while waiting for a row or advisory lock;
- during a long statement;
- after writes but before commit;
- while commit is in flight.

After each test, prove that the pool regains capacity and that a new transaction
can execute. Also prove the expected rows and outbox records.
