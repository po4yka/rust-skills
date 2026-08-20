# Redaction and the Field Vocabulary

This reference expands the redaction rules in `SKILL.md`. Read it before you add
a field name, write a sink, or review a diagnostic for leakage.

## The vocabulary lives in exactly one place

Keep the normative allow list and deny list in one document — a privacy
document that covers every platform in the product, not a Rust document. Cite
it from code and from reviews. Never restate the list in a crate doc, a skill, a
gate script, or a commit message. Three copies drift, and the copy a reader
opens is then the wrong one.

Your observability crate holds the machine-readable tables that implement the
document. The gate script reads those tables. It does not repeat them. That way
the gate and the runtime visitor cannot disagree.

A workable table split:

| Table | Holds | Value shape |
|-------|-------|-------------|
| `ENUM_FIELDS` | Names whose value is a closed enumeration case | `&'static str` from a fixed set, or a small integer code |
| `COUNT_FIELDS` | Names whose value is a magnitude | Unsigned integer |
| `FLAG_FIELDS` | Names whose value is a boolean | `bool` |

Nothing else is a legal field. A field with a free-text value has no table,
because there is no such field.

## The three smuggling routes

A field name that looks safe is not evidence that the value is safe. Watch for
these.

1. **A permitted name carrying a forbidden value.** A field called `count` that
   holds a fixed-point coordinate. A field called `code` that holds a hostname
   hash. The name passes the gate. The value is the leak.
2. **A correlation identifier derived from a forbidden value.** A stable hash of
   a location, a device identifier, or a user identifier is well-formed at every
   layer, and it confirms the value to anyone holding a candidate. A regex
   cannot see this. It stays reviewer-owned.
3. **An emission assembled in a helper rather than written at the call site.**
   The helper takes a `&str` and passes it into `tracing::info!`. The gate reads
   the macro call, sees a variable, and passes. The caller decides what the
   variable holds.

A green gate is not a privacy proof. Say so in the review, every time.

## The redacting visitor

The visitor implements `tracing::field::Visit`. It keeps the declared fields and
drops everything else, including the message.

```rust
use tracing::field::{Field, Visit};

#[derive(Default)]
pub struct RedactingVisitor {
    fields: Vec<(&'static str, FieldValue)>,
}

pub enum FieldValue {
    Enum(&'static str),
    Count(u64),
    Flag(bool),
}

impl Visit for RedactingVisitor {
    fn record_u64(&mut self, field: &Field, value: u64) {
        if COUNT_FIELDS.contains(&field.name()) {
            self.fields.push((field.name(), FieldValue::Count(value)));
        }
    }

    fn record_bool(&mut self, field: &Field, value: bool) {
        if FLAG_FIELDS.contains(&field.name()) {
            self.fields.push((field.name(), FieldValue::Flag(value)));
        }
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        if let Some(case) = enum_case(field.name(), value) {
            self.fields.push((field.name(), FieldValue::Enum(case)));
        }
    }

    fn record_debug(&mut self, _field: &Field, _value: &dyn core::fmt::Debug) {
        // Deliberately empty. `Debug` is an unbounded channel.
        // The `message` field arrives here and is dropped with everything else.
    }
}
```

The important part is the shape, not the types.

- Every `record_*` method is an allow list. The default is to drop.
- `record_debug` is empty. `tracing` routes the event message through the
  `message` field, so an empty `record_debug` drops the message for free.
- `record_str` maps a value to a known case. It does not copy the string. A
  string that is not a known case is dropped, not truncated.

## What a sink receives

```rust
pub struct RedactedEvent {
    pub level: Level,
    pub target: &'static str,
    pub callsite: &'static str,
    pub fields: Vec<(&'static str, FieldValue)>,
}
```

All four members are `'static` or plain data. Nothing borrows from the event.
There is no message, no error string, and no formatted line.

An error reaches the sink as its kind. Define the kind as a frozen enumeration
in the error type, and record it through an `ENUM_FIELDS` name.

```rust
tracing::error!(error_kind = err.kind().code(), "export failed");
```

The host formatter renders the whole line, message included. The embedded sink
receives `error_kind` and nothing else. Both are correct for their reader.

## Sink registration

```text
install_dispatcher() -> Result<(), InstallError>
register_sink(id, sink, level) -> Result<(), SinkError>
```

Semantics:

- `install_dispatcher` calls `set_global_default` once during process bootstrap.
  It creates a dispatcher with a dynamic fan-out registry, but no sinks.
- `register_sink` never installs a subscriber. It adds one sink to the installed
  dispatcher's registry and updates the effective level ceiling.
- A duplicate sink ID returns `SinkError::DuplicateId` and leaves the original
  sink unchanged.
- A missing or failed dispatcher returns `SinkError::DispatcherUnavailable`.
  Keep this distinct from duplicate registration.

Return the installation or registration status across the FFI boundary. Do not
panic and do not turn it into a domain-operation failure. A diagnostic surface
must not be able to fail application start-up.

The fan-out registry can add sinks after the dispatcher is installed. Its
effective ceiling is the highest enabled level among registered sinks. With no
sink the ceiling is off, and every callsite is rejected by design. See the main
skill for the callsite-interest cache rule that makes a later registration
visible.

## The gate

A shell gate that reads the vocabulary tables can reject five things by pattern.

| Rejected | Why |
|----------|-----|
| `?ident` or `%ident` in an emission | `Debug` and `Display` are unbounded |
| `format!` inside an emission | Free text |
| `#[instrument]` without `skip_all` | Records every argument through `Debug` |
| A field name that is not in a table | Undeclared vocabulary |
| A crate whose coverage state disagrees with the coverage record | Silent regression in what is instrumented |

Give the gate a `--self-test` mode that runs it against fixtures containing one
known-bad case per rule. A gate with no self-test rots into a no-op after the
first refactor of its regexes.

The gate cannot see route 2 and route 3 above. Both stay reviewer-owned.

## Stdio is not a diagnostic channel

```rust
#![deny(clippy::print_stdout, clippy::print_stderr, clippy::dbg_macro)]
```

```toml
# clippy.toml
allow-print-in-tests = true
```

`println!` bypasses the visitor entirely. On a mobile or embedded target it also
reaches no reader. Exempt only host-side tools whose job is to write to a
terminal, and write the exemption as an inner attribute with a reason.

Use `allow-print-in-tests` rather than a path rule, because test modules often
live inside `src/` where a path-based exemption cannot distinguish them.
