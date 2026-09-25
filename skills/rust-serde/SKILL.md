---
name: rust-serde
description: Use when deriving or changing Serialize or Deserialize on a type whose encoded form is a contract (config file, stored record, cache, message that another process or build reads), or when serde_json drops a field, reorders keys, or loses number precision without an error. Triggers on deny_unknown_fields, rename_all, serde(alias), serde(tag), untagged, serde(flatten), skip_serializing_if, serde(default), serde(try_from), DeserializeOwned, JSON map key, large integer, preserve_order, float_roundtrip, arbitrary_precision, postcard, bincode, "unknown field", "did not match any variant".
license: BSD-3-Clause
---

# Rust serde

A `#[derive(Deserialize)]` is a parser and a published schema at the same time. Most serde
incidents are silent: a field stays at its default, a number loses digits, or an older build can
no longer read a payload.

Behavior below was measured with serde 1.0.229, serde_json 1.0.151, postcard 1.1.3, and
bincode 2.0.1 on Rust 1.98.1.

## Find the contracts

Run these when you audit a crate or change a type that already shipped:

```bash
# Types whose encoding is a contract with something outside this process.
rg -n '#\[derive\([^)]*Deserialize' --type rust

# Every serde attribute. Each one is a wire-format decision.
rg -n '#\[serde\(' --type rust

# Files that derive Deserialize and never use deny_unknown_fields. Per file, not per struct.
# Do not write `rg -L`: in rg it means --follow, not grep's files-without-match.
rg --files-without-match 'deny_unknown_fields' --type rust $(rg -l 'Deserialize' --type rust)

# serde_json features in the shipped build, and which crate turns each on.
cargo tree --locked -e normal,features -i serde_json -p <shipping-package>

# The same for a test build of the whole workspace, dev-dependencies included.
cargo tree --locked -e features -i serde_json --workspace
```

## Decide what the encoding is for

| The encoded form is | Rule |
| --- | --- |
| Internal to one process, one build, cache that may be discarded | Change it freely. Version the cache directory and drop it on mismatch |
| Written by a human: config, manifest, fixture | `deny_unknown_fields`. A typo must be an error, not a default |
| An older payload is read by a newer build of your own code | Self-describing format: additive only, and every new field gets `default`. postcard or bincode: version the whole payload |
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

With the attribute, `{"host":"h","timoutSecs":5}` fails at parse time, at the byte offset:

```text
unknown field `timoutSecs`, expected `host` or `timeoutSecs` at line 1 column 24
```

### `rename_all` is a wire change, not a style change

`rename_all = "camelCase"` renames every field on the wire. The struct above rejects
`{"host":"h","timeout_secs":5}` with ``unknown field `timeout_secs` ``. Adding `rename_all` to a
type that already shipped breaks every existing payload.

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
the new spelling is written and old payloads keep parsing. Keep the alias until every writer is
upgraded, then remove it in a release that says so.

## Enum representations

Four representations put four different documents on the wire. Choose once, when you create the
type, because a later change is a breaking wire change.

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

| Representation | On the wire | Payload constraint | postcard, bincode (not self-describing) |
| --- | --- | --- | --- |
| External (default) | `{"data":3}` | None | Works |
| Internal (`tag`) | `{"type":"data","size":3}` | Struct, unit, or newtype holding a struct or map | Fails at runtime |
| Adjacent (`tag` + `content`) | `{"t":"data","c":3}` | None | Fails at runtime |
| Untagged | `3` | First variant whose shape fits wins | Fails at runtime |

Internal tagging is the usual choice for a JSON message type, because the tag reads naturally
and the payload stays flat. Adjacent tagging is the fallback when a variant holds something that
is not a map. Use external tagging when the type must also go through a binary format, or build
without serde's `alloc` feature. serde documents it as the only representation for no-alloc
builds, and the postcard and bincode results in the table show the same for those formats.

Internal tagging rejects a tuple variant at compile time. A newtype variant that holds a scalar
compiles and fails only at runtime:

```text
cannot serialize tagged newtype variant <Enum>::<Variant> containing an integer
invalid type: map, expected u64
```

The first line comes from serialization, the second from deserialization of `{"type":"data"}`.

On postcard, deserialization of the internal, adjacent, and untagged forms fails with
`This is a feature that PostCard will never implement`; bincode 2 reports `AnyNotSupported` or
`IdentifierNotSupported`. The derive compiles for all four.

### `untagged` costs the error message and can pick the wrong variant

An untagged enum tries each variant in order. When none fits, the error names no field and no
expected type:

```text
data did not match any variant of untagged enum Untagged
```

Nested in a struct, it adds only the position where the value ends (`at line 1 column N`). An
externally tagged enum at the same place names the expected type:
`invalid type: string "notnum", expected u64`.

The first variant that fits wins, even when a later one fits better. With variants
`Short { x: u8 }` and `Long { x: u8, y: u8 }` in that order, `{"x":1,"y":2}` parses as
`Short { x: 1 }` and drops `y` without an error. Put the variant with the most fields first, or
add `deny_unknown_fields` to the enum.

Use `untagged` only for a small, shapeless input, such as a value that is either a scalar or a
list of scalars. Do not use it for a message enum or a config section.

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

Two constraints that the attribute does not show:

- **`flatten` and `deny_unknown_fields` cancel each other.** With both on one struct, the deny
  rule fires first and the flatten map never receives anything: `{"id":1,"typo":2}` returns
  ``unknown field `typo` ``. Serde documents the combination as unsupported. Pick one: the
  catch-all map or the strict schema.
- **`flatten` needs a self-describing format.** It works with JSON, YAML, and TOML, which carry
  field names. On postcard, serialization fails with `The length of a sequence must be known`. A
  type that flattens cannot move to a binary encoding later.

## Choose a maintained format crate

Before you add a format crate, look it up at `https://rustsec.org/packages/<crate>.html`. After
you add it, and before commit, run `cargo deny --config deny.toml --locked check advisories` or
`cargo audit --deny warnings`. Plain `cargo audit` exits 0 on unmaintained and unsound
advisories. As of 2026-09:

- `bincode` is unmaintained (RUSTSEC-2025-0141, which lists wincode, postcard, bitcode, and rkyv
  as alternatives). Its latest release, 3.0.0, is a `compile_error!` stub, so `cargo add bincode`
  gives a build that fails with only `error: https://xkcd.com/2347/`. Existing users pin
  `=2.0.1` or `1.3.3` until they migrate.
- `serde_yml` is unsound and unmaintained (RUSTSEC-2025-0068, which lists serde_norway and
  serde_yaml_ng as alternatives).
- `serde_yaml` is deprecated: its repository is archived, and its last release is
  `0.9.34+deprecated`.

## Validate at the boundary with `try_from`

A deserialized value is untrusted input that happens to have a type. `#[serde(try_from = "..")]`
runs a conversion during deserialization, so an invalid value never becomes an instance:

```rust
use serde::Deserialize;

#[derive(Deserialize, Debug)]
#[serde(try_from = "u16")]
pub struct NonZeroPort(u16);

impl TryFrom<u16> for NonZeroPort {
    type Error = String;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err("port must be non-zero for this contract".to_owned());
        }
        Ok(NonZeroPort(value))
    }
}
```

`serde_json::from_str::<NonZeroPort>("0")` now fails. The error type must implement `Display`.
Use a different type when zero means "request an ephemeral port". Use `#[serde(into = "..")]`
for the same treatment on the way out; it requires `Clone`.

## Stay readable across versions

Two attributes carry almost all backward compatibility. The rules in this section apply to
self-describing formats (JSON, YAML, TOML). postcard and bincode need the rules in the next
subsection.

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

Both `default`s are needed and they do different jobs. The field-level one handles an absent
section. The struct-level one handles a section that is present but incomplete:
`{"name":"a","limits":{"max_files":3}}` parses, and `max_bytes` comes from `Default`.

`skip_serializing_if` keeps a key out of the output when it has no value. A reader that predates
the field then sees no new key, which matters when that reader uses `deny_unknown_fields`.

Rules for an evolving type:

1. Add fields; do not remove or retype them. A removed field breaks an older reader that requires
   it; a retyped field breaks every reader.
2. Give every added field `#[serde(default)]` in the same commit that adds it.
3. Rename with `alias`, not with a bare `rename`.
4. Carry an explicit version field when the format may need a real migration, and write the
   migration before you need it.

### postcard and bincode decode by position

A positional format writes no field names, so these rules do not hold:

- An added field fails on every old payload, even with `default` (postcard:
  `DeserializeUnexpectedEnd`).
- `skip_serializing_if` removes bytes that the reader expects, so the type cannot read its own
  output (postcard: `DeserializeBadOption`; bincode:
  `UnexpectedVariant { type_name: "Option<T>", .. }`). Do not use it on these formats.

Version the whole payload instead, from the first release: a version prefix, or an externally
tagged enum with one variant per version. A new variant goes at the end, and an old payload then
still decodes as its old variant.

## serde_json changes data without an error

| Operation | Default result | Control |
| --- | --- | --- |
| Parse an integer outside `i64`/`u64` into `Value` | Succeeds as `f64`: `18446744073709551616` becomes `1.8446744073709552e+19` | Parse into the typed field (`u64` fails, `u128` succeeds), or enable `arbitrary_precision` |
| `to_value` on an `i128`/`u128` outside the `i64`/`u64` range | `Err("number out of range")`; `json!` panics on it; `to_string` succeeds | Serialize directly, or enable `arbitrary_precision` |
| `f64` to JSON and back | Best-effort parse. Some values return one ulp off: `906.7979265841685` reads as `906.7979265841684` | Enable `float_roundtrip` (about 2x slower float parsing) |
| Key order of `Value` and `Map` | Sorted, because the map is a `BTreeMap` | `preserve_order` keeps insertion order; `Value::sort_all_objects()` (1.0.129+) sorts on demand |
| Key order of a derived struct | `to_string` writes declaration order; `to_value` then write sorts it | Serialize the struct directly |

Normal-dependency features unify across every package that one command builds. A
dev-dependency turns a feature on only in builds that compile tests, examples, or benches. So one
crate that enables `preserve_order` or `arbitrary_precision` changes the result for every crate
in that build, and a test can see a feature that the shipped binary does not have. Measured: a
dev-dependency with `preserve_order` made `cargo test` print `{"b":1,"a":2}`, and the binary
printed `{"a":2,"b":1}`. Compare the two `cargo tree` commands from "Find the contracts" to see
who enables each feature in each build. Decide the numeric and key-order policy in the crate
that owns the wire format. Pin it with a test, and make sure that no dev-dependency enables
either feature, so the test runs with the feature set that production uses. The
`cargo-workflows` skill, when it is installed, has the resolver rules.

Read [references/data-model-and-lifetimes.md](references/data-model-and-lifetimes.md) when a
generic parser needs a `Deserialize` bound, a map has non-string Rust keys, or you must choose a
large-integer policy.

## Prove the wire contract

A successful derive proves only that serde can describe the Rust type. It does not prove that
the chosen format can represent every value, or that an old payload still parses. Add tests for
the risks the type carries:

- **Old payloads.** Commit one fixture per shipped version. Parse each with the current type and
  assert the field values, not only `is_ok()`. Include aliases, absent sections, and unknown keys.
- **Written output.** Compare the serialized form with a golden file, so a rename or a new
  `rename_all` shows up as a diff. The `rust-test-tools` skill, when it is installed, has the
  golden mechanics. When an older build must read the new output, parse the golden file with the
  released type. For a crate published to a registry, add a renamed dev-dependency on the same
  crate: `old = { package = "<crate>", version = "=<last>" }`.
- **Empty and absent values.** Round-trip empty strings, collections, maps, and `None` for every
  field that has `skip_serializing_if`. A skipped field without `default` writes a document that
  the same type cannot read, and serde_json reports `missing field` for it.
- **Every claimed format.** Round-trip each enum and each flattened type through every format the
  type claims, such as postcard. Tagged enums and `flatten` compile and fail only at runtime.
- **Numeric edges.** Test zero, signed minimum, unsigned maximum, the largest value inside the
  documented JSON range, and the first value above it. For `18446744073709551616`, assert
  `is_f64()` on the `Value` path, rejection on the typed `u64` path, or the exact digits under
  `arbitrary_precision`.
- **Map keys.** Serialize the exact public map type, not a `HashMap<String, T>` stand-in.

Run the targeted test while you iterate, then `cargo test --locked` once before commit. These
tests do not prove what another language's reader accepts. For that, run the consumer's parser
on the golden files.

## Triage

| Symptom | Cause | Fix |
| --- | --- | --- |
| A config value is silently the default | No `deny_unknown_fields`; the key was misspelled | Add the attribute; the parse now names the key |
| Every existing payload stopped parsing | `rename_all` or `rename` added to a shipped type | Add `alias` for the old spelling |
| `unknown field` on a key you meant to capture | `flatten` and `deny_unknown_fields` on one struct | Remove one of them |
| `did not match any variant of untagged enum` | An `untagged` enum with no shape that fits | Move to `tag` or `tag` + `content` |
| An untagged enum parses into the wrong variant and drops fields | An earlier variant with fewer fields fits first | Put the variant with the most fields first, or add `deny_unknown_fields` |
| `cannot serialize tagged newtype variant ... containing ...`, or `invalid type: map, expected ...` on an enum | Internal tagging on a newtype variant that does not hold a map or struct | Use adjacent tagging |
| A newer build cannot read an older payload | A field was added without `default`; on postcard or bincode, a field was added at all | Add `default` to the new reader. On postcard or bincode `default` does not help: version the whole payload |
| An older build cannot read a newer payload | The old reader rejects a field from the new writer | Keep the writer from emitting the field until tolerant or version-aware readers are deployed |
| postcard or bincode fails at runtime on a type that JSON accepts | `flatten`; an internal, adjacent, or untagged enum; or `skip_serializing_if` | Use external tagging, no `flatten`, and no `skip_serializing_if`, or keep the format self-describing |
| ``implementation of `Deserialize` is not general enough`` | A generic parser requires `DeserializeOwned`, and the type borrows (`&'a str`) | Use `T: Deserialize<'de>` while the input lives; keep `DeserializeOwned` for owned input |
| `key must be a string` | A tuple, struct, or newtype-variant map key in JSON | Encode keys as strings, or use a sequence of key-value records |
| A large integer reads back as a float, or `number out of range` | The default `serde_json::Number` in `Value` | Parse into the typed field, or enable and test `arbitrary_precision` |
| An `f64` differs in the last digit after a JSON round trip, or key order changed after a dependency update | A `serde_json` default or a feature that another crate enabled | See "serde_json changes data without an error" |
| A parsed value is structurally valid and semantically wrong | Validation lives after deserialization | `#[serde(try_from = "..")]` |

## Related skills

Use these skills when they are installed:

- `rust-discipline`: parse, do not validate, and the newtype that carries the invariant
- `rust-security`: hardening a parser that reads untrusted input, and the advisory gate
- `rust-test-tools`: property and golden tests for a round trip
- `rust-crate-architecture`: which crate owns a type that crosses a boundary
- `uniffi-boundary`: versioned payloads that cross an FFI boundary as JSON
- `ffi-error-progress-cancel`: the error taxonomy those payloads carry
