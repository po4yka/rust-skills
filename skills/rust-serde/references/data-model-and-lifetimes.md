# Serde Data Model and Lifetime Bounds

Use this reference when a type derives successfully but a generic parser, one format, or a
boundary value fails.

## Choose the deserialization bound from input ownership

Use `Deserialize<'de>` when the result can borrow from the input:

```rust
use serde::Deserialize;

fn parse<'de, T>(input: &'de str) -> serde_json::Result<T>
where
    T: Deserialize<'de>,
{
    serde_json::from_str(input)
}
```

Use `DeserializeOwned` when the input buffer disappears before the result, or when the decoder
owns its input:

```rust
use serde::de::DeserializeOwned;

fn parse_owned<T>(input: String) -> serde_json::Result<T>
where
    T: DeserializeOwned,
{
    serde_json::from_str(&input)
}
```

Do not use `Deserialize<'static>` as an owned-data shortcut. It asks the decoder to borrow for
the program lifetime. It rejects normal input buffers and can force needless allocation. The
relationship is `DeserializeOwned` equals `for<'de> Deserialize<'de>`, not
`Deserialize<'static>`.

## A derive does not prove format compatibility

Serde defines a data model. Each format implements only the parts it can represent. A map key
is the common failure point.

JSON object keys are strings. `serde_json` accepts string-like keys and supported scalar keys,
including integers that it can render as strings. It rejects compound keys such as tuples,
structs, maps, and sequences.

Choose one contract:

- Convert keys to a canonical string and reject non-canonical spellings on input.
- Encode the map as a sequence of `{ "key": ..., "value": ... }` records.
- Select a format whose map keys support the required data model.

Do not test only `HashMap<String, T>` when the public type uses a newtype, integer, tuple, or
enum key. Serialize the exact public type with the selected format.

## Define the large-integer policy

The default `serde_json::Number` and `serde_json::Value` model does not hold every `i128` or
`u128`. `Number::from_i128` and `Number::from_u128` return `None` outside their supported range.
Parsing a larger JSON number into `Value` can also fail.

This does not mean that every direct streaming serialization of `i128` or `u128` fails. A
serializer can write the decimal digits without constructing a `Value`. Therefore test the
actual path. A direct `to_writer` path and a `to_value` then `to_writer` path have different
representational limits.

Do not convert an integer through `f64` unless the schema permits precision loss. Values above
the exact integer range of the chosen floating-point representation can round silently.

Choose and document one policy:

| Contract | Required proof |
| --- | --- |
| Integer fits the default JSON number range | Reject outside the range before serialization |
| Integer is a decimal string | Validate the canonical string and its sign or width |
| Arbitrary-precision JSON number | Enable the format feature deliberately and test every consumer |
| Binary integer | Select a format and schema with an explicit 128-bit representation |

## Run boundary round trips

For each supported format and version, test:

1. Serialize the current type.
2. Parse the bytes with the oldest supported reader.
3. Serialize with the oldest supported writer fixture.
4. Parse with the current reader.
5. Assert the semantic value, not only successful parsing.

Include these values when they are in the schema:

- empty strings, collections, and maps;
- zero, signed minimum, and unsigned maximum;
- the largest value below and the first value above the documented JSON range;
- every map-key family;
- aliases, defaults, and unknown fields;
- every enum representation.

A compile check proves the trait implementations. Only these format-specific round trips prove
the wire contract.

## Authoritative references

- [Serde deserializer lifetimes](https://serde.rs/lifetimes.html)
- [Serde data model](https://serde.rs/data-model.html)
- [`serde_json::Number`](https://docs.rs/serde_json/latest/serde_json/struct.Number.html)
