---
name: rust-serde
description: Use when you derive Serialize or Deserialize on a type whose encoded form is a contract - a config file, an on-disk record, a cached payload, a message another process or an older build reads. Covers deny_unknown_fields and the rename_all migration trap, the four enum representations and what each puts on the wire, why untagged destroys error messages, flatten and its interaction with deny_unknown_fields and non-self-describing formats, validation at the boundary with try_from, and the default plus alias pair that keeps old and new payloads both readable. Triggers on serde, Serialize, Deserialize, DeserializeOwned, serde_json, JSON map key, large integer, deny_unknown_fields, rename_all, serde(tag), untagged, serde(flatten), skip_serializing_if, serde(default), serde(alias), serde(try_from), "unknown field", "did not match any variant", or any wire-compatibility question.
license: BSD-3-Clause
---

# Rust serde

## Purpose

Rules for types whose encoded form other code depends on. A `#[derive(Deserialize)]`
is a parser and a published schema at the same time, and the derive hides that. Most serde
incidents are not crashes; they are a field that silently stayed at its default, or a payload
an older build can no longer read.

Find what is at stake before you change a type:

```bash
# Every type whose encoding is a contract with something outside this process.
rg -n '#\[derive\([^)]*Deserialize' --type rust

# Attributes that change the wire format. Each one is a compatibility decision.
rg -n '#\[serde\((rename|rename_all|tag|untagged|flatten|skip)' --type rust

# Structs that accept anything they are given.
rg -L 'deny_unknown_fields' -l --type rust $(rg -l 'Deserialize' --type rust)
```

## Decide what the encoding is for

| The encoded form is | Rule |
| --- | --- |
| Internal to one process, one build, cache that may be discarded | Change it freely. Version the cache directory and drop it on mismatch |
| Written by a human: config, manifest, fixture | `deny_unknown_fields`. A typo must be an error, not a default |
| Read by an older build of your own code | Additive only. Every new field gets `default` |
| Read by another team or another language | Additive only, plus an explicit version field and a written schema |

The second and third rows conflict: `deny_unknown_fields` rejects a field a *newer* writer
added. Apply it to files a human authors, not to messages a newer peer may send.

## `deny_unknown_fields`

By default serde discards any key that matches no field. A typo in a config file passes
validation, and the field it was meant to set keeps its default value. Nothing reports it.

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Config {
    host: String,
    timeout_secs: u64,
}
```

With the attribute, `{"host":"h","timoutSecs":5}` fails:

```text
unknown field `timoutSecs`, expected `host` or `timeoutSecs` at line 1 column 24
```

The message names the field and the position. That is the whole value of the attribute: the
error arrives at parse time, at the byte offset, instead of appearing later as a wrong timeout.

### `rename_all` is a wire change, not a style change

`rename_all = "camelCase"` renames every field on the wire. The struct above no longer accepts
`{"host":"h","timeout_secs":5}` at all — the snake_case spelling is now an unknown field. Adding
`rename_all` to a type that already shipped breaks every existing payload.

Add `alias` for the old spelling when the type is already in the field:

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
struct Config {
    // Writes `timeout_ms`; reads both `timeout_ms` and the old `timeout`.
    #[serde(rename = "timeout_ms", alias = "timeout")]
    timeout_ms: u64,
}
```

`rename` sets the name for both directions. `alias` adds an accepted name for reading only, so
the new spelling is what gets written and the old payloads keep parsing. Keep the alias until
every writer has been upgraded, then remove it in a release that says so.

## Enum representations

Four representations, four different documents on the wire. Choose once, at the point the type
is created, because changing it later is a breaking wire change.

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum External { Ping, Data(u64) }

#[derive(Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum Internal { Ping, Data { size: u64 } }

#[derive(Serialize, Deserialize)]
#[serde(tag = "t", content = "c", rename_all = "snake_case")]
enum Adjacent { Ping, Data(u64) }

#[derive(Serialize, Deserialize)]
#[serde(untagged)]
enum Untagged { Number(u64), Text(String) }
```

For the `Data` variant carrying `3`:

| Representation | On the wire | Constraint |
| --- | --- | --- |
| External (default) | `{"data":3}` | Nests every payload one level |
| Internal (`tag`) | `{"type":"data","size":3}` | Struct and unit variants only; a newtype variant must hold a map |
| Adjacent (`tag` + `content`) | `{"t":"data","c":3}` | No constraint on the payload |
| Untagged | `3` | Matched by shape, first variant that fits |

Internal tagging is the usual choice for a message type, because the tag reads naturally and the
payload stays flat. Adjacent tagging is the fallback when a variant holds something that is not
a map.

### `untagged` costs you the error message

An untagged enum is matched by trying each variant in order. When none fits, serde cannot say
which one you meant, so the error names nothing:

```text
data did not match any variant of untagged enum Untagged
```

No field, no position, no expected type. On a large config this is close to useless. Use
`untagged` only for a small, genuinely shapeless input, such as a value that is either a scalar
or a list of scalars. Never use it for a message enum, and never for a config section.

## `flatten`

`flatten` inlines a nested struct or a map into the parent. It is the way to capture keys you do
not know in advance:

```rust
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Serialize, Deserialize, Debug)]
struct Record {
    id: u64,
    #[serde(flatten)]
    extra: BTreeMap<String, serde_json::Value>,
}
```

Two constraints that are not obvious from the attribute:

- **`flatten` and `deny_unknown_fields` cancel each other.** With both on one struct, the deny
  rule fires first and the flatten map never receives anything: `{"id":1,"typo":2}` returns
  `unknown field 'typo'`. Serde documents the combination as unsupported. Pick one — the
  catch-all map or the strict schema.
- **`flatten` needs a self-describing format.** It works with JSON, YAML, and TOML, which carry
  field names. It does not work with a compact binary format such as bincode, where the decoder
  has only the field order. A type that flattens cannot be moved to a binary encoding later.

## Validate at the boundary with `try_from`

A deserialized value is untrusted input that happens to have a type. `#[serde(try_from = "..")]`
runs a conversion during deserialization, so the invalid value never becomes an instance:

```rust
use serde::Deserialize;

#[derive(Deserialize, Debug)]
#[serde(try_from = "u16")]
pub struct Port(u16);

impl TryFrom<u16> for Port {
    type Error = String;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err("port 0 is not bindable".to_owned());
        }
        Ok(Port(value))
    }
}
```

`serde_json::from_str::<Port>("0")` now fails with `port 0 is not bindable`. Every later use of
a `Port` can assume it is valid, and no code needs a second check. This is the serde form of
parse, do not validate; see the `rust-discipline` skill.

Use `#[serde(into = "..")]` for the same treatment on the way out, and note that it requires
`Clone`.

## Stay readable across versions

Two attributes carry almost all backward compatibility.

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Default)]
#[serde(default)]     // a partially written section fills the rest from Default
pub struct Limits {
    pub max_bytes: u64,
    pub max_files: u32,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Config {
    pub name: String,
    #[serde(default)] // the whole section may be absent in an older payload
    pub limits: Limits,
    // Omitted entirely when None, so an older reader never sees the key.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}
```

Both `default`s are needed and they do different jobs. The field-level one handles the section
being absent. The struct-level one handles the section being present but incomplete:
`{"name":"a","limits":{"max_files":3}}` parses, and `max_bytes` comes from `Default`.

`skip_serializing_if` keeps the written document small and, more importantly, keeps a key out of
the output entirely when it has no value. A reader that predates the field then sees no new key
at all, which matters when the reader uses `deny_unknown_fields`.

Rules for an evolving type:

1. Add fields, never remove or retype them. A removed field breaks an older reader that requires
   it; a retyped field breaks every reader.
2. Give every added field `#[serde(default)]` in the same commit that adds it.
3. Rename with `alias`, never with a bare `rename`.
4. Carry an explicit version field when the format may need a real migration, and write the
   migration before you need it.

## Prove the data model and ownership bound

Read [references/data-model-and-lifetimes.md](references/data-model-and-lifetimes.md) when a
generic parser needs a `Deserialize` bound, a JSON map has non-string Rust keys, or an integer
can exceed `u64` or `i64`. Derive success proves only that Serde can describe the Rust type. It
does not prove that the selected format can represent every value.

Run boundary round trips for the exact format. Include empty values, maximum integers, legacy
aliases, unknown fields, and every map-key shape that the contract permits.

## Triage

| Symptom | Cause | Fix |
| --- | --- | --- |
| A config value is silently the default | No `deny_unknown_fields`; the key was misspelled | Add the attribute; the parse now names the key |
| Every existing payload stopped parsing | `rename_all` or `rename` added to a shipped type | Add `alias` for the old spelling |
| `unknown field` on a key you meant to capture | `flatten` and `deny_unknown_fields` on one struct | Remove one of them |
| `did not match any variant of untagged enum` | An `untagged` enum with no shape that fits | Move to `tag` or `tag` + `content` |
| `invalid type: map, expected ...` on an enum | Internal tagging on a newtype variant that is not a map | Use adjacent tagging |
| An older build cannot read a new payload | A field was added without `default` | Add `default`; ship the reader before the writer |
| A binary format rejects a type that JSON accepts | `flatten` needs field names | Remove `flatten`, or keep the format self-describing |
| A generic parser rejects borrowed output | It requires `DeserializeOwned` or `Deserialize<'static>` | Use `T: Deserialize<'de>` while the input lives; keep `DeserializeOwned` only for owned input |
| JSON rejects a derived map at runtime | The key type is outside JSON's supported scalar key model | Encode keys as strings or use a sequence of key-value records |
| A large integer fails only through `serde_json::Value` | The default `Number` representation cannot hold it | Define the numeric range or enable and test an explicit arbitrary-precision policy |
| A parsed value is structurally valid and semantically wrong | Validation lives after deserialization | `#[serde(try_from = "..")]` |

## Related skills

- `rust-discipline` — parse do not validate, and the newtype that carries the invariant
- `rust-security` — hardening a parser that reads untrusted input
- `rust-test-tools` — property and golden tests for a round trip
- `rust-crate-architecture` — which crate owns a type that crosses a boundary
- `uniffi-boundary` — versioned payloads that cross an FFI boundary as JSON
- `ffi-error-progress-cancel` — the error taxonomy those payloads carry
