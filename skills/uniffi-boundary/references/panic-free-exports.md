# Panic-free exports

Deep material for `uniffi-boundary`, "Errors: the shape rule". Read it when you set the lint
set of a boundary crate or make a non-throwing export total.

Apply the FFI-path panic lint set from the `rust-panic-safety` skill in `lib.rs`. For a
UniFFI adapter, also deny `clippy::unreachable` and `clippy::indexing_slicing`, because a
panic in a non-throwing export is a Swift fatal error. Add `clippy::arithmetic_side_effects`
when the crate does arithmetic.

Add `#![forbid(unsafe_code)]` when the crate has no hand-written `unsafe`; the `rust-unsafe`
skill owns that rule. The generated scaffolding does not trip it (Rust 1.99.1, UniFFI 0.32.2).

The lints do not see a panic inside an inner crate that the adapter calls, or inside a
panicking std API such as `split_at`, `Vec::remove`, or `copy_from_slice`. Keep the body of a
non-throwing export total: an atomic store, or a lock that recovers poison with
`PoisonError::into_inner`. Otherwise wrap the inner call in `std::panic::catch_unwind` and map
a panic to a no-op or a logged event.
