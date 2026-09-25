# UniFFI compared with the raw jni crate

Read this file when you choose between the raw `jni` crate and UniFFI for a
JVM binding. It shows what the UniFFI side looks like, so you can price it
before you commit. The `uniffi-boundary` skill, when it is installed, owns the
generated boundary, and `uniffi-packaging-versioning` owns its versions and
packaging.

## Decision rule

- **Small, handle-based surface** (create, start, stop, poll, destroy) with a
  hot data path: use the raw `jni` crate. The generator buys little when the
  payload is one `jlong` handle and one JSON string.
- **Growing API with rich types**, or a second target platform: use UniFFI
  (`uniffi = "0.32.1"` or later). Hand-written signatures on both sides cost
  more than the generator. Its Kotlin bindings call the library through JNA, so
  no `Java_*` symbol or `external fun` exists.
- Do not mix both styles on one class. Pick one per binding surface.

## What changes

| Concern | Raw `jni` crate | UniFFI |
|---------|-----------------|--------|
| Export declaration | `native_method!` plus `RegisterNatives`, `#[jni_mangle]`, or a hand-written `Java_*` export | `#[uniffi::export]` |
| Panic guard | `native_method!` generates it; a hand-written export needs its own | Generated scaffolding contains it |
| Error mapping | An `ErrorPolicy` in `resolve`, or a manual `throw_new` | A typed error enum maps to a Kotlin exception |
| Kotlin declaration | Hand-written `external fun` | Generated class, enum, and exception types |
| Transport | JNI | JNA, so the app needs the JNA dependency; see `uniffi-packaging-versioning` |
| Thread attachment | Your problem for every callback | JNA attaches and detaches the thread on every callback; for frequent callbacks, attach each Rust worker once (see the `ffi-error-progress-cancel` skill) |
| Hot-path bytes | Your choice of fd transfer or direct buffer | `Vec<u8>` copies. A `&[u8]` argument borrows a direct `ByteBuffer` for the call only (0.32+) |
| `#![forbid(unsafe_code)]` | Rejects every hand-written `#[unsafe(no_mangle)]` export and `JNI_OnLoad` | Compiles: the lint does not see scaffolding that the proc macros generate |
| Dependency | `jni = "0.22.2"` or later | `uniffi = "0.32.1"` or later (Kotlin checksum fixes) |

The `forbid` row matters in review. The lint ignores macro-generated `unsafe` in
both columns, so a clean `forbid(unsafe_code)` build proves only that
hand-written code has no `unsafe`. Hand-rolled `extern "C"` inside a UniFFI
crate bypasses the generated guard and needs its own panic guard.

## Proc-macro form

```rust
uniffi::setup_scaffolding!();

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum SessionError {
    #[error("socket error")]
    Socket,
    #[error("bind error")]
    Bind,
    #[error("invalid address")]
    InvalidAddress,
}

#[uniffi::export]
pub fn create_session(address: String, port: i32) -> Result<i32, SessionError> {
    let _ = (address, port);
    todo!("bind the socket and return the session handle")
}
```

The `uniffi-boundary` skill owns the exported surface (proc-macros, no UDL).

## Generate the Kotlin bindings

Generate, check in, and gate the bindings as the `uniffi-packaging-versioning`
skill describes: the in-crate generator behind the `cli` feature,
`--no-format`, and a `--check` script. On Kotlin, call
`uniffiEnsureInitialized()` once at startup, or a stale binding runs without a
checksum error.
