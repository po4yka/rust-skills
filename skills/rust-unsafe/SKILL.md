---
name: rust-unsafe
description: Use when adding, removing, or reviewing unsafe Rust, such as unsafe blocks, unsafe impl Send or Sync, raw pointers, transmute, mem::zeroed and MaybeUninit, unions, hand-written extern "C" and no_mangle exports, syscall or ioctl wrappers, zero-copy buffers, mmap, and forbid(unsafe_code). Also for soundness or undefined-behavior questions. Triggers on "SAFETY comment", "Strict Provenance", "repr(packed)", "E0793", "E0133", "improper_ctypes", "OwnedFd".
license: BSD-3-Clause
---

# Rust unsafe

## Find the unsafe surface

Run this inventory when you audit a crate, or when you add or remove unsafe code:

```bash
# Crates that promise no unsafe in their own source.
rg -l '#!\[forbid\(unsafe_code\)\]' --type rust

# Where unsafe code lives.
rg -n 'unsafe\s*\{|unsafe fn|unsafe impl|unsafe extern' --type rust

# Symbols that leave the crate unmangled, and custom link sections.
rg -n '#\[(unsafe\()?(no_mangle|export_name|link_section)' --type rust
```

In a periodic audit, also grep the macro expansion of each crate, because
`forbid(unsafe_code)` does not see dependency macro code. The nightly command is in
[references/forbid-unsafe-code.md](references/forbid-unsafe-code.md).

## Governance with `#![forbid(unsafe_code)]`

A written rule such as "no unsafe in this crate" is not enforcement. Enforce it with
`#![forbid(unsafe_code)]` at the crate root, a lint level, or a CI check. Add the attribute to
every crate that has no hand-written `unsafe`, including a crate that reaches C or the OS only
through a safe wrapper crate. A local `#[allow(unsafe_code)]` cannot weaken it (E0453). The lint
also rejects `#[unsafe(no_mangle)]`, `#[unsafe(export_name)]`, and `#[unsafe(link_section)]`, so a
crate with an unmangled export cannot carry it. Before 1.98 it ignores other unsafe attributes,
such as `#[unsafe(naked)]`.

The lint checks the crate's own source, not the code it compiles to. An unsafe block or an
`#[unsafe(no_mangle)]` export that a dependency's macro expands builds with no diagnostic, and
`cargo clippy -- -D unsafe_code` is silent too. So a `forbid` hit does not prove that the crate
compiles to no unsafe. Read the same reference for the diagnostic per source of unsafe.

Removing `#![forbid(unsafe_code)]` is a reviewable event. Remove it in the commit that adds the
unsafe code, not in advance, and state which unsafe operation forced it and where it lives. Keep
the set of unsafe crates small, for example only the FFI adapter.

## Lint floor for unsafe crates

Put these lints at the root of every crate that contains `unsafe`:

```rust
#![deny(unsafe_op_in_unsafe_fn)]
#![deny(
    clippy::undocumented_unsafe_blocks,
    clippy::multiple_unsafe_ops_per_block,
    clippy::missing_safety_doc,
)]
```

They require an `unsafe { ... }` block for each unsafe operation inside an `unsafe fn`, a
`// SAFETY:` comment above every block, one unsafe operation per block (each has its own
invariant), and a `# Safety` section with the caller obligations on every `pub unsafe fn`. By
default `unsafe_op_in_unsafe_fn` warns only from edition 2024, the two restriction lints are
off, and `missing_safety_doc` only warns. Set the lints in `[workspace.lints]`, and restate them
at the root of each crate that contains unsafe. The `rust-lints` skill, when it is installed,
owns the workspace floor, the suppression policy, and the CI lint gate.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `E0133: ... is unsafe and requires unsafe block` (an error, or under edition 2024 an `unsafe_op_in_unsafe_fn` warning inside an `unsafe fn`) | An unsafe or foreign `fn` call, a `static mut` or `extern` static access, or a call to a `#[target_feature]` fn from a caller without that feature | One `unsafe { }` per operation, with a SAFETY comment; declare a foreign fn `safe fn` when it has no precondition; or give the caller the same `#[target_feature]` |

When you add the first unsafe to a safe crate, add the floor and run
`cargo clippy --locked -p <crate> --all-targets -- -D warnings` before you write the unsafe body.
This proves that the floor is active, so clippy then rejects a bare `unsafe { ... }`.
Performance is a reason for unsafe only after a measurement. Read
[references/audit-checklist.md](references/audit-checklist.md) when you decide whether a new
unsafe site is legitimate.

## Verify an unsafe change

Run the checks that match the risk. Each check proves one thing.

1. Every change: `cargo clippy --locked -p <crate> --all-targets -- -D warnings`. It proves that
   the lint floor holds. It does not prove that a SAFETY comment is true.
2. Every change: `cargo test --locked -p <crate>` in the debug profile. On the executed path,
   debug assertions check many std unsafe preconditions (1.78), a misaligned `*p` (1.70), and a
   null `*p` (1.86). A violation aborts with `unsafe precondition(s) violated: ...`,
   `misaligned pointer dereference`, or `null pointer dereference occurred`: a non-unwinding
   panic that `catch_unwind` cannot catch. Treat it as undefined behavior. `--release` removes
   these checks. With the prebuilt std, no profile checks a misaligned `ptr::read` (rustc
   1.99.1); `cargo +nightly careful test`, when cargo-careful is installed, does.
3. Code that Miri can execute, when nightly with the `miri` component is installed:
   `cargo +nightly miri test --locked -p <crate>` with the default Stacked Borrows model first,
   then `MIRIFLAGS="-Zmiri-tree-borrows"` as a second opinion. Tree Borrows is more permissive
   and more experimental, so never use it to excuse a default-model failure. Add
   `-Zmiri-symbolic-alignment-check` for reads through a cast byte pointer,
   `-Zmiri-strict-provenance` for code that does not deliberately expose provenance, and
   `-Zmiri-many-seeds` for threads or a manual `Send` or `Sync` impl (one seed explores one
   schedule).
4. FFI code that Miri cannot execute: mark the test `#[cfg_attr(miri, ignore)]` and cover the
   path with ASan on the host, or HWASan or MTE on a device. cargo-careful is not a substitute.
   A `#[cfg(miri)]` stub for the foreign function must dereference every pointer that the
   foreign side stores; otherwise Miri sees no use of the pointer and reports nothing.

A clean Miri run is evidence about aliasing, provenance, initialization, and alignment (with
`-Zmiri-symbolic-alignment-check`) on the paths that the tests execute. It is not evidence about
unexecuted paths, foreign code, or a library contract that the abstract machine never evaluates,
such as UTF-8 validity or the allocator rule of `String::from_raw_parts`. The
`rust-sanitizers-miri` skill, when it is installed, owns the Miri flag policy and the sanitizers.

The change is complete when clippy passes, a debug test executes each unsafe path, every block
and `unsafe impl` has a SAFETY comment that names its invariant, and the report names each unsafe
path that neither Miri nor a sanitizer executed. Read
[references/audit-checklist.md](references/audit-checklist.md) when you review unsafe code that
someone else wrote, or before a merge that adds unsafe.

## Triage: faults that pass a safety review

In these faults the unsafe block is correct and the shape of the data is wrong. No
`// SAFETY:` comment catches them, and each one is still undefined behavior.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `E0793: reference to field of packed struct is unaligned` | `&` or `&mut`, a `&self` or `&mut self` method (`clone()`), a `match` guard, or a `ref` binding on a `#[repr(packed)]` field | Copy the field out, or `(&raw const f).read_unaligned()` |
| Correct on the host and the device; default Miri or a debug `*p` fails only on some buffer addresses | `bytes.as_ptr() as *const u32`, then a read | "Pointer reads from untrusted byte buffers" below |
| `error: casting &T to &mut T is undefined behavior` | Mutation through a shared reference | `UnsafeCell`; there is no other sound way |
| A `*const` silently became a `*mut` | `as` on a pointer changes mutability too | `ptr.cast::<T>()`, and `cast_mut` when you mean it |
| `warning: uses type dyn Trait, which is not FFI-safe` | A fat pointer in a C signature | Pointer plus length, or an opaque handle |
| Two unrelated handles accepted at the same call | Every handle is `*mut c_void` | One zero-sized `#[repr(C)]` opaque type per handle |
| Memory grows once per callback registration | The boxed closure context is never reclaimed | Provide the unregister path that calls `Box::from_raw` |
| Double close, or a read from a reused descriptor | `RawFd` states no owner | `OwnedFd` to own, `BorrowedFd<'_>` to lend |
| A field is corrupt on one target only | Hand-rolled bitfield masks | A bitfield crate, plus a round-trip test against real bytes |
| Sound in debug, unsound in release | `debug_assert!` guards an unsafe block | `assert!`, which survives the shipping profile |
| A handle outlives the data it points at | A raw pointer carries no lifetime and no drop check | `PhantomData<&'a T>` to borrow, `PhantomData<T>` to own |

Keep both FFI-safety lints on: `improper_ctypes` checks imports from C, and
`improper_ctypes_definitions` checks exports, so one alone leaves half the boundary unchecked.
Both warn by default, so the `-D warnings` gate fails on a hit. Never allow either lint
crate-wide; put `#[expect(..., reason = "...")]` on the one item that the lint cannot judge.
Since 1.98, `c_void_returns` warns on `-> c_void`; write no return type for a C `void` function.
Read [references/ffi-layout-rules.md](references/ffi-layout-rules.md) when you apply a fix from
this table.

## Drop hazards

Soundness must not depend on a `Drop` running: `mem::forget`, `Box::leak`, and an `Rc` cycle skip
it in safe code. Make a forgotten guard harmless, as `thread::scope` does. Read
`references/unsafe-patterns.md` when a guard, a registration, or a `Drop::drop` can fail.

## One unsafe block breaks local reasoning

One unsafe block anywhere in the call graph, a dependency included, can break an invariant
that safe code relies on. For example, a dependency calls `str::from_utf8_unchecked` on bytes whose validation was defeated, and the
undefined behavior surfaces in your first decode loop. Outside a byte-string literal, neither
the compiler nor Miri reports the construction. When you audit:

1. `rg 'from_utf8_unchecked|from_raw_parts' --type rust -n`. Every hit
   needs a SAFETY comment that traces back to where the invariant is established.
2. Run `cargo deny --config deny.toml --locked check advisories` to find a dependency with a
   known soundness advisory. The `rust-security` skill, when it is installed, owns the policy.
3. When a dependency's unsafe transits through your API, restate the assumed invariant in your
   own `# Safety` section.

Read [references/unsafe-patterns.md](references/unsafe-patterns.md) when you write the
reproducing test; only a decode loop fails on invalid UTF-8.

## Manual `unsafe impl Send` or `Sync`

The compiler accepts a manual impl unchecked, also after a field gains an `Rc`. Bound it on the
parameters (`unsafe impl<T: Sync> Sync`), and audit every field and `&self` method, derives
included. Read `references/miri-and-aliasing.md` before you write or review one.

## Reference fabrication

Never hand out a `&T` built from `RefCell::as_ptr` or a `&String` from `String::from_raw_parts`
over a `&str`; Miri can pass both. Read `references/miri-and-aliasing.md` when code does either.

## Pointer reads from untrusted byte buffers

`std::ptr::read(buf.as_ptr() as *const T)` requires `buf.as_ptr()` to be aligned for `T`. Bytes
from a socket, a file, a mapping, or an FFI caller carry arbitrary alignment, and a misaligned
`ptr::read` is undefined behavior on every target. Native x86-64 and AArch64 tests still pass,
so the defect ships unless you follow these steps.

1. Read a `&[u8]` from I/O, FFI, or a mapping with `ptr::read_unaligned`, even when the field is
   aligned today.
2. Prefer `zerocopy::FromBytes`, `u32::from_le_bytes`, or `bytes::Buf` over pointer arithmetic
   on byte buffers. They remove the unsafe block and make endianness explicit.
3. Test every new unsafe byte parser under Miri with `-Zmiri-symbolic-alignment-check`. Without
   the flag, default Miri fails only on the seeds where the buffer lands misaligned.
   cargo-careful also sees only the addresses that the test produces.
4. Run a parser that uses native endianness or pointer casts under
   `cargo +nightly miri test --target s390x-unknown-linux-gnu`. The target is big-endian, so a
   hidden little-endian assumption fails.

Grep audit:

```bash
rg -n 'as_ptr\(\)\s*(as\s*\*const|\.cast::<)' --type rust | rg -v 'read_unaligned|::<u8>'
rg 'transmute::<\s*&\[u8\]' --type rust -n
```

The grep is a floor: it misses a pointer cast in a later statement. `clippy::cast_ptr_alignment`
(pedantic) flags both `as` and `.cast::<T>()`. Read
[references/unsafe-patterns.md](references/unsafe-patterns.md) when you write a byte parser.

## Where the other patterns live

- `mem::zeroed`, `assume_init`, a reference from a raw pointer, or an integer-to-pointer
  conversion: `references/validity-and-provenance.md`.
- A slice over a foreign buffer or a mapping, or an `#[unsafe(no_mangle)]` export:
  `references/ffi-layout-rules.md`.
- Whether a block needs `unsafe`; an `unsafe impl`, `unsafe trait`, unsafe attribute, or
  `# Safety` section; pointer arithmetic; a syscall, `ioctl`, or descriptor wrapper:
  `references/unsafe-patterns.md`.

## Panics and unwinding at the FFI boundary

The `rust-panic-safety` skill, when it is installed, owns the panic policy at a C ABI or JNI
boundary. Two soundness facts stay here:

- Below `rust-version` 1.81, an unwind out of `extern "C"` is undefined behavior, not an abort.
- A foreign exception that unwinds into Rust through an import declared `extern "C"` is
  undefined behavior. Declare such an import `extern "C-unwind"`.

Read [references/unsafe-patterns.md](references/unsafe-patterns.md) when you write a hand-rolled
`extern "C"` entry point, or a `from_raw` call that takes ownership of a foreign handle. The
`rust-jni` skill, when it is installed, owns `JNI_OnLoad` and `JNI_OnUnload`: `JNI_OnLoad`
returns `JNI_ERR` on a caught panic.

## Transmute

Prefer the named conversion, such as `f32::from_bits`, `u32::from_ne_bytes`, `Box::into_raw`, or
`zerocopy::FromBytes`: it cannot be applied to the wrong pair of types. When none exists, write
both types in the turbofish and state the layout and lifetime argument in the SAFETY comment.
Read [references/unsafe-patterns.md](references/unsafe-patterns.md) when you choose a conversion
or extend the lifetime bound of a `dyn` raw pointer.

## Related skills

When installed: `rust-jni` and `uniffi-boundary` (the boundary), `rust-variance`
(`PhantomData`), `rust-pin-projection` (`map_unchecked_mut`), `memory-model` (atomics), and
`rust-debugging` (a crash).
