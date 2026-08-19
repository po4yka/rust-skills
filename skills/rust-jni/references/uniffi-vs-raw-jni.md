# UniFFI compared with the raw jni crate

Read the decision rule in [../SKILL.md](../SKILL.md) first. This file shows what
the UniFFI side of that decision looks like, so you can price it before you
commit. For the full generated-boundary contract, use the `uniffi-boundary` and
`uniffi-packaging-versioning` skills.

## What changes

| Concern | Raw `jni` crate | UniFFI |
|---------|-----------------|--------|
| Export declaration | `#[unsafe(no_mangle)] pub extern "system" fn Java_<pkg>_<Class>_<method>` | `#[uniffi::export]` or a UDL entry |
| Panic guard | You write it at every export | Generated scaffolding contains it |
| Error mapping | Manual `env.throw_new` | A typed error enum maps to a Kotlin exception |
| Kotlin declaration | Hand-written `external fun` | Generated class, enum, and exception types |
| Thread attachment | Your problem for every callback | Handled for generated callback interfaces |
| Hot-path bytes | Your choice of fd transfer or direct buffer | The generated mapping copies; keep hot paths out |
| `#![forbid(unsafe_code)]` | Not possible in the shim crate | Not possible: the generated scaffolding is `unsafe` |

The last row matters in review. A UniFFI crate with no hand-written `unsafe` is
not a soundness finding; confirm with `rg -n 'unsafe' <crate>/src` that every
hit is macro-generated. Hand-rolled `extern "C"` inside a UniFFI crate bypasses
the generated guard and needs the full `catch_unwind` treatment.

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

## UDL form

```udl
namespace example {
    [Throws=SessionError]
    i32 create_session(string address, i32 port);

    [Throws=SessionError]
    i32 start_session(i32 handle);

    [Throws=SessionError]
    i32 stop_session(i32 handle);
};

[Error]
enum SessionError {
    "Socket",
    "Bind",
    "InvalidAddress",
};
```

Pick one form per crate. The proc-macro form keeps the signature next to the
implementation, so the two cannot drift. The UDL form gives one file to review
as the API surface.

## Generate the Kotlin bindings

```bash
cargo run --locked --bin uniffi-bindgen generate \
    --library target/debug/libexample_native.so \
    --language kotlin \
    --out-dir <module>/src/main/kotlin/<package path>
```

Notes:

- Generate from the built library (`--library`), not from the UDL file, so the
  bindings match the compiled scaffolding.
- Generation is a build step, not a manual one. Wire it into the build so the
  generated sources cannot go stale against the crate.
- Treat the generated directory as build output. Do not edit it by hand.
- There are no `external fun` declarations to keep in sync, and no symbol names
  to match. The failure mode moves from `UnsatisfiedLinkError` at run time to a
  version mismatch between the bindings and the `.so`. Ship both from the same
  build.
