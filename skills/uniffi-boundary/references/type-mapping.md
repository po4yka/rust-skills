# UniFFI type mapping

Use this file when you choose the Rust type for an exported signature or a Record field.

The mappings below are the UniFFI 0.32 built-ins. Confirm an edge case against the
documentation for the version in `Cargo.lock`; the generated foreign types change between
minor versions.

Contents: Scalars; Collections and containers; Time types; Compound types you declare;
Default values; Custom types; Types that never cross; Naming.

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
| `HashSet<T>` (0.32+) | `Set<T>` | `Set<T>` |
| `Box<T>` (0.32+) | as `T` | as `T` |
| `Vec<u8>` | `ByteArray` | `Data` |
| `&[u8]` argument (0.32+) | direct `java.nio.ByteBuffer` | `Data` |

Notes:

- Every container is copied on every crossing. A `Vec<T>` field with 10 000 elements is
  10 000 conversions per call, in each direction.
- `HashMap` iteration order is not stable. Do not let the foreign side depend on it. If order
  is meaningful, return `Vec<(K, V)>` as a `Vec` of a two-field Record.
- Nested containers work — `Option<Vec<HashMap<String, i64>>>` — but a deeply nested generic
  signature is a sign that the payload should be a Record, or a JSON string contract.
- Use owned types for Record fields, returns, and stored values. A top-level shared
  reference argument (`&str`, `&[T]`, `&Record`, `&Object`) is borrowed only for the call.
  `Option<&str>` fails with an unsatisfied `Lift<UniFfiTag>` bound.
- A `&[u8]` argument is not copied. It cannot be returned, nested, used in an async export,
  or used in a foreign-trait method. [SKILL.md](../SKILL.md) ("Ownership across the boundary")
  has the Kotlin direct-buffer and position rules.
- `Box<T>` crosses as `T` in parameters and enum variants, and lets an Enum or a Record refer
  to itself. Both need 0.32.
- Fixed-size arrays `[T; N]` have no mapping. Use `Vec<T>` and validate the length in Rust.
- Tuples have no mapping. Use a Record with named fields; the generated API is also clearer.

## Time types

| Rust | Kotlin | Swift |
|------|--------|-------|
| `std::time::SystemTime` | `java.time.Instant` | `Date` |
| `std::time::Duration` | `java.time.Duration` | `TimeInterval` |

Swift `Date` and `TimeInterval` are `Double` seconds, so Swift can lose nanosecond precision.
On Android below API 26, `java.time` needs core library desugaring; otherwise cross an `i64`
of epoch milliseconds.
`chrono` and `time` crate types have no built-in mapping. Either convert to `SystemTime` and
`Duration` at the boundary, or declare a custom type with an explicit converter. For a
wire-stable timestamp, an `i64` of epoch milliseconds inside a JSON contract avoids the
platform date types entirely, and is often the better answer for a contract that must be
byte-identical on both platforms.

## Compound types you declare

| Derive | Foreign result | Constraint |
|--------|----------------|------------|
| `#[derive(uniffi::Record)]` | Kotlin `data class`, Swift `struct` | Every field must be a UniFFI type |
| `#[derive(uniffi::Enum)]` | Kotlin `enum class` without payloads, `sealed class` with payloads; Swift `enum` | Variant payload fields must be UniFFI types |
| `#[derive(uniffi::Object)]` | Opaque reference-counted class | Type must be `Send + Sync` |
| `#[derive(uniffi::Error)]` | Kotlin `Exception`, Swift `Error` | The `Err` type of an exported `Result` |

Rules:

- Enums may carry payloads. Keep payload fields small; a large payload on a hot variant is
  copied on every crossing.
- Generic types you declare have no mapping. `Response<T>` cannot be exported. Declare a
  concrete Record per payload type, or use a JSON string contract.
- A Record or an Enum can hold an `Arc<Object>` field. In Kotlin, a Record that holds an
  Object implements `Disposable`. Its `destroy()` also releases Objects inside its `List` and
  `Map` fields. For a `List` or `Map` of Objects returned directly, call
  `Disposable.destroy(list)` or close each Object.
- Do not derive `Record` on an inner-crate domain type. Declare a boundary Record and write an
  explicit `From<DomainType> for BoundaryRecord`. That impl is where you keep the contract
  stable when the domain type changes.

## Default values

A default makes the generated Kotlin and Swift signatures carry the value. Adding a defaulted
argument or field then stays source compatible for foreign callers. These forms compile on
0.32:

| Target | Form |
|--------|------|
| Record field, type default | `#[uniffi(default)]` on the field (literal optional since 0.30) |
| Record field, literal | `#[uniffi(default = 3)]` |
| Method argument | `#[uniffi::method(default(limit = 10))]` on the method |
| Constructor argument | `#[uniffi::constructor(default(size = 4))]` |
| Free function argument | `#[uniffi::export(default(n = 5))]` |
| Argument, type default | Name it without a value: `default(name = "x", size)` |

A default helps only foreign source compatibility. The binding is still regenerated, so the
stability rules in [SKILL.md](../SKILL.md) still apply.

## Custom types

A custom type travels as another UniFFI type but has its own name and semantics on the foreign
side. Use `custom_newtype!` for a transparent wrapper and `custom_type!` for real conversion
logic. `UniffiCustomTypeConverter` was removed in 0.29; do not write it.

```rust
uniffi::setup_scaffolding!();

mod ids {
    pub struct SpecJson(pub String);
    uniffi::custom_newtype!(SpecJson, String);

    #[derive(Debug, thiserror::Error, uniffi::Error)]
    pub enum IdError {
        #[error("a job id has 1 to 64 bytes")]
        InvalidJobId,
    }

    pub struct JobId(String);

    impl JobId {
        pub fn parse(raw: String) -> Result<Self, IdError> {
            if raw.is_empty() || raw.len() > 64 {
                return Err(IdError::InvalidJobId);
            }
            Ok(Self(raw))
        }

        pub fn into_string(self) -> String {
            self.0
        }
    }

    uniffi::custom_type!(JobId, String, {
        lower: |id| id.into_string(),
        try_lift: |raw| Ok(JobId::parse(raw)?),
    });

    #[uniffi::export]
    pub fn cancel_job_by_id(id: JobId) -> Result<(), IdError> {
        let _ = id;
        Ok(())
    }
}
```

Keep the conversions in named functions, so a round-trip test can call them. The rules:

- The lowering direction, Rust to builtin, cannot fail.
- The lifting direction, builtin to Rust, can fail. UniFFI downcasts the `anyhow::Error` from
  `try_lift` to the error type that the function declares, and returns it as that error.
  Any other lift failure is an internal error: Kotlin gets `InternalException`, and a
  non-throwing Swift function ends the app. Return the boundary error from `try_lift`, and
  take the type only in functions that declare that error, as `cancel_job_by_id` does.
- The round trip must be lossless. If `parse(into_string(x))` does not give back `x` for a
  valid `x`, a caller finds the bug later. Add a property test for the round trip.
- Custom types cost a conversion on every crossing. A custom type on a field inside a large
  `Vec` multiplies that cost.

Common custom-type candidates: `PathBuf` transported as `String`, a UUID transported as
`String`, a validated identifier newtype, and a versioned JSON contract string.

## Types that never cross

| Type | Why | Do this instead |
|------|-----|-----------------|
| Borrowed return, stored borrow, `&mut T`, `Option<&T>`, or a nested reference | No foreign lifetime can carry the borrow | Return an owned Record or an `Arc` handle; borrow a top-level shared argument only for one call |
| `Rc<T>`, `Cell<T>`, `RefCell<T>` | Not `Sync` | `Arc` plus `Mutex` or `RwLock` |
| Raw pointers | No safety story across the boundary | Wrap in an Object and expose methods |
| Generic `T` | No monomorphization across the boundary | Concrete types, one per payload |
| Closures | No mapping | A foreign trait, `#[uniffi::export(foreign)]` |
| `Arc<dyn Trait>` for an undeclared trait | Only exported traits map | Declare the trait with `#[uniffi::export(foreign)]` or `#[uniffi::export(rust, foreign)]` |
| `std::io::Error`, `anyhow::Error` | Not a UniFFI error type | Map to a `#[derive(uniffi::Error)]` enum at the boundary |
| Large `Vec<u8>` buffers | Copied on every crossing, doubles peak memory | Write the file in Rust and return the path; take a large input as `&[u8]` |

## Naming

The generator applies the idiomatic naming of each target language. Rust `snake_case` methods
and fields become `camelCase` in Kotlin and Swift; Rust types keep `PascalCase`. Name the Rust
side idiomatically for Rust and let the generator do the rest. Do not pre-mangle a Rust name
to make one platform look better, because it makes the other platform look worse and it makes
the Rust crate read badly on its own.

Avoid a Rust name that collides with a keyword or a standard type on either target. `Error`,
`Result`, `Data`, `Type`, and `Object` are all worth avoiding as bare exported type names.
Prefix them with the domain instead.
