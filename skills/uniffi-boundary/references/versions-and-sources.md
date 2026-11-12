# UniFFI version floor and primary sources

## Version floor

The catalog examples target UniFFI 0.32.x. The proc-macro surface changes between minor
versions. When `Cargo.lock` pins a `uniffi` version below the floor of a row, use the older
form or upgrade. The `uniffi-packaging-versioning` skill owns the upgrade.

| Form | Needs |
|------|-------|
| `uniffi::custom_type!(T, Bridge, { lower, try_lift })`. `UniffiCustomTypeConverter` is removed. | 0.29 |
| `#[uniffi::export] impl` on a Record or an Enum (methods on data types) | 0.31 |
| `#[uniffi::export(foreign)]` and `#[uniffi::export(rust, foreign)]`. Before 0.32, write `with_foreign`. | 0.32 |
| `&[u8]` argument without a copy (Kotlin direct `java.nio.ByteBuffer`) | 0.32 |
| `HashSet<T>`, `Box<T>` (parameters, enum variants, recursive types), `async_runtime` on a trait export | 0.32 |

Kotlin consumers need 0.32.1 or later.

## Primary sources

Read the pages for the UniFFI version in `Cargo.lock`. `latest` tracks the newest release.

| Topic | URL |
|-------|-----|
| Proc-macros, derives, `setup_scaffolding!` | <https://mozilla.github.io/uniffi-rs/latest/proc_macro/index.html> |
| Interfaces (Objects), constructors, `Arc` | <https://mozilla.github.io/uniffi-rs/latest/types/interfaces.html> |
| Foreign traits, `UnexpectedUniFFICallbackError`, cycles | <https://mozilla.github.io/uniffi-rs/latest/foreign_traits.html> |
| `&[u8]` arguments | <https://mozilla.github.io/uniffi-rs/latest/types/bytes.html> |
| Custom types | <https://mozilla.github.io/uniffi-rs/latest/types/custom_types.html> |
| Async and futures | <https://mozilla.github.io/uniffi-rs/latest/futures.html> |
| Kotlin object lifetimes | <https://mozilla.github.io/uniffi-rs/latest/kotlin/lifetimes.html> |
| Swift panics and `Sendable` | <https://mozilla.github.io/uniffi-rs/latest/swift/overview.html> |
| CHANGELOG | <https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md> |
