# Lint catalog

What each lint in the canonical set actually buys, plus the optional blocks you
add only when the workspace needs them.

## Clippy lint groups

Know the group before you set its level. A group level with `priority = -1`
sits below the individual lints, so a single lint can override its own group.

| Group | Contents | Recommended level |
|-------|----------|-------------------|
| `correctness` | Code that is almost certainly a bug | `deny` |
| `suspicious` | Code that is very likely wrong | `deny` |
| `style` | Idiomatic-Rust deviations | `warn` |
| `complexity` | Code that does something simple in a convoluted way | `warn` |
| `perf` | Code that is measurably slower than an equivalent | `warn` |
| `all` | The four groups above, combined | `deny` at `priority = -1` |
| `pedantic` | Opinionated, mostly correct, some noise | `warn` at `priority = -1` |
| `nursery` | New lints, still stabilizing | `warn` at `priority = -1` |
| `cargo` | Manifest and dependency-graph hygiene | `warn` at `priority = -1` |
| `restriction` | Deliberately restrictive; **never enable the group** | pick individual lints only |

`restriction` as a group contradicts itself - it contains mutually exclusive
lints. Cherry-pick from it. The picks in the canonical set are
`indexing_slicing`, `integer_division`, `arithmetic_side_effects`,
`modulo_arithmetic`, `unwrap_used`, `expect_used`, `panic`, `todo`,
`unimplemented`, `exit`, `str_to_string`, `allow_attributes`,
`allow_attributes_without_reason`, `undocumented_unsafe_blocks`,
`multiple_unsafe_ops_per_block`, `exhaustive_enums`, `exhaustive_structs`,
`unwrap_in_result`, `mem_forget`, `print_stdout`, `dbg_macro`.

## Defect class per lint

Read this table when you must justify a lint's level, or when you audit why a
defect reached production.

| Lint | Defect class it catches |
|------|-------------------------|
| `mem_forget` = deny, plus `std::mem::forget` in `disallowed-methods` | Leaking `Drop` on a resource-bearing type: an open file, a native handle, a GPU surface, a lock guard. The resource is never released and nothing reports it. |
| `let_underscore_drop` = deny | `let _ = guard;` drops an RAII guard immediately instead of holding it. The critical section then has no lock. This is one of the most common machine-generated concurrency bugs, and it compiles cleanly. |
| `undocumented_unsafe_blocks` | An `unsafe` block with no `// SAFETY:` comment. The invariant was never stated, so no reviewer can check it and no later author can preserve it. |
| `multiple_unsafe_ops_per_block` | One `// SAFETY:` comment covering several unsafe operations. The comment then justifies at most one of them. |
| `missing_safety_doc` | A `pub unsafe fn` with no `# Safety` rustdoc section. The caller has no stated contract to satisfy. |
| `unsafe_op_in_unsafe_fn` (rustc) | The whole body of an `unsafe fn` treated as one implicit unsafe block. This hides which line actually needs the audit. |
| `large_stack_arrays`, `large_stack_frames` | A big array or a fat state struct placed on the stack. It overflows on a small thread stack - worker threads and mobile main threads are far smaller than the default. |
| `large_futures` | An oversized future moved between tasks; each `spawn` copies it. |
| `large_enum_variant` | One huge variant inflating every value of the enum, including the small ones. |
| `exhaustive_enums`, `exhaustive_structs` | A public enum or struct without `#[non_exhaustive]`. Adding a field or a variant later is then a breaking change for every downstream match or literal. |
| `disallowed_methods` on `std::ptr::read` | A misaligned read from a byte buffer that came from I/O or FFI. `ptr::read` requires an aligned pointer, so a misaligned read is undefined behavior on every target, and it faults in practice on aarch64. Use `read_unaligned`. |
| `disallowed_methods` on `std::env::set_var` | A mutation of the process environment after threads have started. It is not thread-safe. |
| `arithmetic_side_effects`, `integer_division`, `modulo_arithmetic` | Unchecked integer arithmetic: overflow, truncation, divide-by-zero. A release build wraps silently; a debug build panics. Both outcomes are wrong. `arithmetic_side_effects` fires on integer operators only, so it does not cover float math. |
| `indexing_slicing` | `buf[i]` on data whose length came from outside the program. Use `.get()` and handle the `None`. |
| `unwrap_used`, `expect_used`, `unwrap_in_result` | A panic path in production code, usually written where an error should have propagated. |
| `panic`, `todo`, `unimplemented` | A stub that compiles and ships. `todo!()` in a merged branch is a runtime crash waiting for the right input. |
| `allow_attributes`, `allow_attributes_without_reason` | A bare `#[allow(...)]` smuggling a violation past review with no justification. Also pushes authors to `expect`, which self-reports when it goes stale. |
| `missing_docs`, `missing_panics_doc`, `missing_errors_doc` | A public API whose failure and panic conditions are undocumented, so every caller guesses. |
| `dbg_macro`, `print_stdout` | Debug output left in a shipped build. On a library or a CLI with structured output, `println!` corrupts the protocol. See `rust-observability`. |
| `exit` | `process::exit` inside library code. It skips every destructor and every buffer flush. |
| `redundant_closure_for_method_calls` | A closure that only forwards to a method, where the method path itself works. A common machine-written stylism. |
| `uninlined_format_args` | `format!("{}", x)` instead of `format!("{x}")`. Cheap to fix and it removes review noise. |
| `implicit_clone`, `str_to_string`, `inefficient_to_string`, `cloned_instead_of_copied` | Allocation nobody asked for, on a hot path nobody measured. |
| `needless_pass_by_value`, `trivially_copy_pass_by_ref` | An ownership signature that fights the caller in both directions. |
| `disallowed_types` | A type that is correct in one context and wrong in another - for example a blocking `Mutex` inside async code. |
| `unused_must_use` (rustc) | A dropped `Result` or a dropped guard-like value. |
| `unreachable_pub` (rustc) | An item marked `pub` that no external path can reach. It inflates the apparent API surface. |
| `non_ascii_idents` (rustc) | Homoglyph identifiers. Two distinct items look identical in review. |
| `rustdoc::broken_intra_doc_links` = deny | Documentation that silently rots after a rename. |

## Optional block: pointer and FFI lints

Add these only in a workspace that contains hand-written pointer work. In a
workspace where every crate is `#![forbid(unsafe_code)]` they can never fire.

```toml
[workspace.lints.clippy]
mut_from_ref              = "deny"   # returning &mut from &, an aliasing violation
transmute_ptr_to_ptr      = "deny"
useless_transmute         = "deny"
crosspointer_transmute    = "deny"
cast_ptr_alignment        = "deny"   # a cast that raises the alignment requirement
transmute_undefined_repr  = "warn"
as_ptr_cast_mut           = "warn"
ptr_as_ptr                = "warn"   # prefer .cast() over `as *const T`
rc_mutex                  = "deny"   # Rc<Mutex<T>> is single-threaded; you wanted Arc or RefCell

[workspace.lints.rust]
improper_ctypes            = "warn"  # a non-FFI-safe type in an extern block
improper_ctypes_definitions = "warn" # a non-FFI-safe type in an extern "C" fn you define
```

`cast_ptr_alignment` and the transmute family are the static half of the
alignment story. Miri is the runtime half. See `rust-unsafe` and
`rust-sanitizers-miri`.

## Optional block: async lints

Add these only when the workspace runs an async runtime. A synchronous,
compute-bound workspace - even one with data parallelism - gains nothing from
them, and carrying dead lint config trains readers to ignore the config.

```toml
[workspace.lints.clippy]
await_holding_lock         = "deny"  # a blocking guard held across .await deadlocks the executor
await_holding_refcell_ref  = "deny"  # a RefCell borrow held across .await panics on re-entry
await_holding_invalid_type = "warn"
large_futures              = "warn"
```

Pair them with the matching entries in `clippy.toml`, which is where
`disallowed-types` lives:

```toml
disallowed-types = [
  { path = "std::sync::Mutex",  reason = "in async modules use the runtime's Mutex" },
  { path = "std::sync::RwLock", reason = "in async modules use the runtime's RwLock" },
]
```

When you introduce an async runtime into a previously synchronous workspace,
add these lints in the same commit. Adding them later means auditing every
`.await` that already shipped. See `rust-async-internals`.

## Optional block: binding-layer relaxations

A JNI layer cannot satisfy two lints, because the foreign ABI fixes the shape of
the generated function signatures:

| Lint | Why the JNI layer cannot satisfy it |
|------|-------------------------------------|
| `missing_safety_doc` | A JNI crate holds many `pub unsafe extern "system"` functions that the JVM alone calls. Each one would carry the same boilerplate `# Safety` section. |
| `not_unsafe_ptr_arg_deref` | The JNI signatures pass raw `JNIEnv` and object pointers into safe-looking functions. The lint fires on every entry point. |

Scope the relaxation to the binding crate with a crate-level attribute, not with
a workspace `allow`:

```rust
#![expect(
    clippy::missing_safety_doc,
    clippy::not_unsafe_ptr_arg_deref,
    reason = "the JNI entry-point signatures are fixed by the foreign ABI; the JVM is the only caller"
)]
```

Rules for these two:

- Write the justification in the commit message as well as in the attribute.
- They are the only lint relaxations a binding layer should need. Any third one
  needs a real argument. See `rust-jni` and `uniffi-boundary`.

## Lints deliberately not in the canonical set

| Lint | Why not |
|------|---------|
| `clippy::string_to_string` | Removed in clippy 1.86. `implicit_clone` covers it. |
| `clippy::restriction` (the whole group) | Contains mutually exclusive lints. Cherry-pick instead. |
| `await_holding_*` in a synchronous workspace | Cannot fire; it is noise in the config. |
| `unsafe_code = "forbid"` in `[workspace.lints.rust]` | A workspace-wide `forbid` cannot be overridden by the one crate that owns unsafe. Set it per crate. |
