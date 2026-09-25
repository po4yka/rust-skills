# Isolation and retry classification

Controls for common invariants and a runnable retry classifier, behind "Choose
isolation from the invariant" and "Retry the complete transaction" in
`SKILL.md`.

## Controls for common invariants

| Invariant or operation | Typical control |
|---|---|
| One value must stay unique | Unique constraint, then classify its violation |
| Update only the version read | Version column in the `WHERE` clause |
| Update a known row set | Row locks in a stable order |
| Protect a missing row or range | Serializable isolation or engine-specific range lock |
| Maintain a cross-row predicate | Serializable isolation or a matching constraint |
| Claim queued jobs once | Atomic update or locking read with explicit skip policy |

## PostgreSQL retry classifier

The classifier and the retry decision are pure functions, so a unit test covers
them without a database. The classifier matches exact SQLSTATE codes. Only a
bucket that is never retried may match a class prefix.

```rust,run
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DbFailure {
    Serialization,
    DeadlockVictim,
    Constraint,
    Timeout,
    CommitOutcomeUnknown,
    Cancelled,
    Other,
}

fn classify_postgres(sqlstate: &str) -> DbFailure {
    match sqlstate {
        "40001" => DbFailure::Serialization,
        "40P01" => DbFailure::DeadlockVictim,
        "57014" | "55P03" | "25P03" | "25P04" => DbFailure::Timeout,
        // A prefix is safe only for a bucket that is never retried.
        code if code.starts_with("23") => DbFailure::Constraint,
        _ => DbFailure::Other,
    }
}

fn can_retry(failure: DbFailure, attempt: u8, maximum_attempts: u8) -> bool {
    attempt < maximum_attempts
        && matches!(failure, DbFailure::Serialization | DbFailure::DeadlockVictim)
}

fn main() {
    assert_eq!(classify_postgres("40001"), DbFailure::Serialization);
    assert_eq!(classify_postgres("40003"), DbFailure::Other);
    assert_eq!(classify_postgres("23505"), DbFailure::Constraint);
    assert_eq!(classify_postgres("57014"), DbFailure::Timeout);
    assert!(can_retry(DbFailure::Serialization, 1, 3));
    assert!(can_retry(DbFailure::DeadlockVictim, 2, 3));
    assert!(!can_retry(DbFailure::Serialization, 3, 3));
    assert!(!can_retry(DbFailure::Constraint, 1, 3));
    assert!(!can_retry(DbFailure::Timeout, 1, 3));
    assert!(!can_retry(DbFailure::CommitOutcomeUnknown, 1, 3));
    assert!(!can_retry(DbFailure::Cancelled, 1, 3));
}
```

`CommitOutcomeUnknown` and `Cancelled` have no SQLSTATE. The call site sets
them, because only it knows whether `COMMIT` was in flight or the caller gave
up.
