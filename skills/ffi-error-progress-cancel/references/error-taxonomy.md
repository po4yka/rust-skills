# Error taxonomy and redaction

Companion to `SKILL.md`, section 1. Read it when you add, split, rename, or
remove an error kind, or when you wire a log sink across the boundary.

Contents: the core kind enum, when to split a kind, the redacting log sink.

## The core kind enum

The core crate owns the kinds. Every kind has a stable `code()` string. The
boundary enum variant name and the `code()` string are the same identity; the
message is not part of it.

```rust
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreErrorKind {
    // caller-controlled input
    InvalidRequest,
    InvalidData,
    NotFound,
    // resource policy
    OutOfMemoryRisk,
    ResourceLimitExceeded,
    IoFailed,
    // encrypted or signed container import
    InvalidArchive,
    ArchiveAuthenticationFailed,
    // engine-side failures
    ProcessingFailed,
    OutputFailed,
    // control flow
    Cancelled,
    // invariant violation and forward-compatible fallback
    Unexpected,
}

impl CoreErrorKind {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidRequest => "invalid_request",
            Self::InvalidData => "invalid_data",
            Self::NotFound => "not_found",
            Self::OutOfMemoryRisk => "out_of_memory_risk",
            Self::ResourceLimitExceeded => "resource_limit_exceeded",
            Self::IoFailed => "io_failed",
            Self::InvalidArchive => "invalid_archive",
            Self::ArchiveAuthenticationFailed => "archive_authentication_failed",
            Self::ProcessingFailed => "processing_failed",
            Self::OutputFailed => "output_failed",
            Self::Cancelled => "cancelled",
            Self::Unexpected => "unexpected",
        }
    }
}
```

`#[non_exhaustive]` makes downstream `match` arms keep a wildcard, so a new kind
does not break every consumer crate at once. Inside the defining crate the
`match` stays exhaustive, so adding a kind fails the build until `code()` and
the boundary mapping cover it.

## When to split a kind

Keep the set small enough to enumerate in a review. Split a kind only when a
platform must react differently.

| Kind | Use it when |
| --- | --- |
| `InvalidRequest` | Caller-controlled operation parameters, identifiers, settings, paging, or lifecycle state are wrong. |
| `InvalidData` | Imported, captured, or persisted data is malformed or internally inconsistent. |
| `NotFound` | A named resource the caller asked for does not exist. |
| `OutOfMemoryRisk` | A memory policy or allocation guard refused the workload. Recoverable by shrinking it. |
| `ResourceLimitExceeded` | A non-memory work, count, depth, or time limit was hit. Recoverable by narrowing scope. |
| `InvalidArchive` | A container failed structural validation. |
| `ArchiveAuthenticationFailed` | A container failed authentication: wrong passphrase or bad tag. Keep it distinct from `InvalidArchive`; the UX is a passphrase prompt, not a re-pick. |
| `Unexpected` | Generated engine output violates an internal invariant. Also the FFI crate's wildcard target for a core kind that is newer than the FFI crate. |

A change to the kind set is a contract change:

- Adding a kind is additive. Assign its UX bucket and its boundary variant in
  the same change, and extend the stable-code contract test.
- Removing or renaming a kind, a variant, or a `code()` string is breaking.
  Platform mappers and telemetry key off these names.
- Changing a message is not a contract change. Messages vary per release and
  per locale.

## Redacting log sink

If the host installs a log sink across the boundary (the host passes a listener
that receives every `tracing` event), that sink is not a second channel for the
detail that the boundary error refuses to carry. Enforce it by construction:

- The error constructor emits the error's *kind* as a frozen enumeration case
  and nothing else. It does not emit the message or the source chain.
- A shared redacting visitor admits only declared field names that carry enum
  cases, counts, and booleans. It drops everything else (free-form strings,
  paths, source chains) before the boundary.
- A host-side subscriber inside the same process may render the full message.
  The FFI sink never sees it.

Review the visitor as an allowlist. A denylist of "sensitive" field names fails
the first time somebody adds a field. The `rust-observability` skill owns the
subscriber setup.
