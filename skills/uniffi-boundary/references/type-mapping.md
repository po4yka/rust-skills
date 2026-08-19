# UniFFI type mapping

Use this file when you choose the Rust type for an exported signature or a Record field.

The mappings below are the standard UniFFI built-ins. Confirm them against the documentation
for the UniFFI version pinned in your lockfile before you rely on an edge case; the generated
foreign types have changed between minor versions.

## Scalars

| Rust | Kotlin | Swift |
|------|--------|-------|
| `bool` | `Boolean` | `Bool` |
| `i8` | `Byte` | `Int8` |
| `i16` | `Short` | `Int16` |
| `i32` | `Int` | `Int32` |
| `i64` | `Long` | `Int64` |
| `u8` | `UByte` | `UInt8` |
| `u16` | `UShort` | `UInt16` |
| `u32` | `UInt` | `UInt32` |
| `u64` | `ULong` | `UInt64` |
| `f32` | `Float` | `Float` |
| `f64` | `Double` | `Double` |
| `String` | `String` | `String` |
| `()` | `Unit` / void return | `Void` |

Notes:

- Kotlin unsigned types are a different type family from the signed ones. A `u32` field in a
  Record becomes `UInt` in Kotlin, and Kotlin callers must convert. If the value is a count
  that Kotlin code will do arithmetic with, ask whether `i64` is the kinder choice. Do not
  change a type only for foreign convenience if it makes an invalid state representable in
  Rust.
- `usize` and `isize` have no mapping. Convert to a fixed-width integer at the boundary and
  handle the conversion failure explicitly. Do not use `as`.
- Rust `char` has no mapping. Use `String`.

## Collections and containers

| Rust | Kotlin | Swift |
|------|--------|-------|
| `Option<T>` | `T?` | `T?` |
| `Vec<T>` | `List<T>` | `[T]` |
| `HashMap<K, V>` | `Map<K, V>` | `[K: V]` |
| `Vec<u8>` | `ByteArray` | `Data` |

Notes:

- Every container is copied on every crossing. A `Vec<T>` field with 10 000 elements is
  10 000 conversions per call, in each direction.
- `HashMap` iteration order is not stable. Do not let the foreign side depend on it. If order
  is meaningful, return `Vec<(K, V)>` as a `Vec` of a two-field Record.
- Nested containers work — `Option<Vec<HashMap<String, i64>>>` — but a deeply nested generic
  signature is a sign that the payload should be a Record, or a JSON string contract.
- Use owned types in an exported signature. `&[T]` has no mapping; take `Vec<T>`. Take
  `String`, not a borrowed string type.
- Fixed-size arrays `[T; N]` have no mapping. Use `Vec<T>` and validate the length in Rust.
- Tuples have no mapping. Use a Record with named fields; the generated API is also clearer.

## Time types

| Rust | Kotlin | Swift |
|------|--------|-------|
| `std::time::SystemTime` | `java.time.Instant` | `Date` |
| `std::time::Duration` | `java.time.Duration` | `TimeInterval` |

`chrono` and `time` crate types have no built-in mapping. Either convert to `SystemTime` and
`Duration` at the boundary, or declare a custom type with an explicit converter. For a
wire-stable timestamp, an `i64` of epoch milliseconds inside a JSON contract avoids the
platform date types entirely, and is often the better answer for a contract that must be
byte-identical on both platforms.

## Compound types you declare

| Derive | Foreign result | Constraint |
|--------|----------------|------------|
| `#[derive(uniffi::Record)]` | Kotlin `data class`, Swift `struct` | Every field must be a UniFFI type |
| `#[derive(uniffi::Enum)]` | Kotlin sealed class, Swift `enum` | Variant payload fields must be UniFFI types |
| `#[derive(uniffi::Object)]` | Opaque reference-counted class | Type must be `Send + Sync` |
| `#[derive(uniffi::Error)]` | Kotlin `Exception`, Swift `Error` | Used only in the `Err` position of an exported return |

Rules:

- Enums may carry payloads. Keep payload fields small; a large payload on a hot variant is
  copied on every crossing.
- Generic types you declare have no mapping. `Response<T>` cannot be exported. Declare a
  concrete Record per payload type, or use a JSON string contract.
- Support for an Object field inside a Record depends on the UniFFI version. Check the
  documentation for your pinned version before you nest a handle inside a Record. When in
  doubt, return the handle separately.
- Do not derive `Record` on an inner-crate domain type. Declare a boundary Record and write an
  explicit `From<DomainType> for BoundaryRecord`. That impl is where you keep the contract
  stable when the domain type changes.

## Default values

Proc-macro exports support a default value on an argument, so that the generated Kotlin and
Swift signatures carry the default and adding an argument stays source compatible for
callers. Check the proc-macro documentation for your pinned version for the exact attribute
form before you use it. A default only helps the *foreign source* compatibility; it is still a
regenerated binding, so it is not a substitute for the stability rules in the main skill.

## Custom types

A custom type transports as a built-in type but has a distinct name and distinct semantics on
the foreign side.

Transparent newtype over a built-in:

```rust
pub struct SpecJson(pub String);

uniffi::custom_newtype!(SpecJson, String);
```

For a type that needs real conversion logic in both directions, use the custom-type converter
form documented for your version. The converter defines the *builtin* it travels as, how to
build the Rust type from that builtin, and how to lower the Rust type back to it. The
constraints are the same in every version:

- The conversion must be **total in the lowering direction**. Rust to builtin cannot fail.
- The lifting direction — builtin to Rust — may fail, and that failure surfaces as an error to
  the caller. Make the error message say which value was rejected.
- The round trip must be **lossless**. If `lift(lower(x)) != x` for any valid `x`, the type is
  a bug waiting for a caller to find it. Add a property test for the round trip.
- Custom types cost a conversion on every crossing. A custom type on a field inside a large
  `Vec` multiplies that cost.

Common custom-type candidates: `PathBuf` transported as `String`, a UUID transported as
`String`, a validated identifier newtype, and a versioned JSON contract string.

## Types that never cross

| Type | Why | Do this instead |
|------|-----|-----------------|
| `&T`, `&mut T`, any lifetime (the `&self` receiver excepted) | UniFFI has no borrow model | Return an owned Record or an `Arc` handle |
| `Rc<T>`, `Cell<T>`, `RefCell<T>` | Not `Sync` | `Arc` plus `Mutex` or `RwLock` |
| Raw pointers | No safety story across the boundary | Wrap in an Object and expose methods |
| Generic `T` | No monomorphization across the boundary | Concrete types, one per payload |
| Closures | No mapping | A callback interface trait |
| `Box<dyn Trait>` for an undeclared trait | Only declared callback traits map | Declare the trait with `#[uniffi::export(callback_interface)]` |
| `std::io::Error`, `anyhow::Error` | Not a UniFFI error type | Map to a `#[derive(uniffi::Error)]` enum at the boundary |
| Large `Vec<u8>` buffers | Copied on every crossing, doubles peak memory | Write the file in Rust, return the path |

## Naming

The generator applies the idiomatic naming of each target language. Rust `snake_case` methods
and fields become `camelCase` in Kotlin and Swift; Rust types keep `PascalCase`. Name the Rust
side idiomatically for Rust and let the generator do the rest. Do not pre-mangle a Rust name
to make one platform look better, because it makes the other platform look worse and it makes
the Rust crate read badly on its own.

Avoid a Rust name that collides with a keyword or a standard type on either target. `Error`,
`Result`, `Data`, `Type`, and `Object` are all worth avoiding as bare exported type names.
Prefix them with the domain instead.
