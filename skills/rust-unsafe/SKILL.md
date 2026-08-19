---
name: rust-unsafe
description: Use when you add or review any unsafe Rust block, FFI boundary (JNI, UniFFI, or hand-rolled extern "C"), raw-pointer arithmetic, transmute, ManuallyDrop, mem::zeroed, ioctl or syscall wrapper, union access, manual unsafe impl Send/Sync, Box::leak, zero-copy buffer or mmap handoff, or any change that removes #![forbid(unsafe_code)] from a previously safe crate. Covers the lint floor for unsafe crates, SAFETY comment discipline, panic safety at FFI boundaries, unaligned reads from untrusted bytes, Drop and double-panic hazards, symbol collision in cdylib crates, Miri and Tree Borrows verification, and a review checklist. Triggers on "unsafe", "FFI", "extern", "raw pointer", "transmute", "*mut/*const", "SAFETY comment", "undefined behavior", "no_mangle", "zero-copy", "mmap", "repr(packed)", "alignment", "E0793", "improper_ctypes", "opaque handle", "OwnedFd", or any soundness question.
license: BSD-3-Clause
---

# Rust unsafe

## Purpose

Use this skill to write, review, and audit `unsafe` Rust. The rules below apply to any
workspace. Derive the current unsafe inventory from the source tree before you change it.
Do not trust a memory of where unsafe lives.

Start every unsafe task with these four commands:

```bash
# Which crates promise to contain no unsafe in their own source.
rg -l '#!\[forbid\(unsafe_code\)\]' --type rust

# Which unsafe a dependency macro injects, which the attribute never sees.
cargo +nightly rustc -p <crate> --profile=check -- -Zunpretty=expanded | rg 'unsafe'

# Where unsafe actually lives.
rg -n 'unsafe\s*\{|unsafe fn|unsafe impl|unsafe extern' --type rust

# Which symbols leave the crate unmangled.
rg -n '#\[unsafe\(no_mangle\)\]|#\[no_mangle\]|#\[unsafe\(export_name|#\[export_name' --type rust
```

## Governance: `#![forbid(unsafe_code)]`

Every crate that holds pure logic carries `#![forbid(unsafe_code)]` at the crate root. Add the
attribute when you create a crate that has no FFI and no OS-level calls. It is cheap, it is
checked by the compiler, and an `#[allow]` further down cannot suppress it. A local
`#[allow(unsafe_code)]` under the attribute is
`error[E0453]: allow(unsafe_code) incompatible with previous forbid`.

### What the attribute covers, and what it does not

The lint is checked per lexical span. It governs the crate's own source text. It does not govern
the code the crate compiles to.

| Where the `unsafe` comes from | Result under `#![forbid(unsafe_code)]` |
| --- | --- |
| A hand-written `unsafe { ... }` block in the crate | `error: usage of an unsafe block`. The build fails. |
| A `macro_rules!` defined in the same crate | The same hard error, reported at the macro body and at the call site |
| A `macro_rules!` exported by any dependency crate | No diagnostic. The crate builds and the unsafe operation runs. |
| A proc macro from a dependency crate | No diagnostic. The crate builds and the unsafe operation runs. |

The boundary is the crate the macro was written in, not whether the macro is procedural. rustc
suppresses lints on tokens that an external macro expanded. The rule is general; `unsafe_code`
is the instance that matters, because it gates soundness and the other lints gate tidiness.

Measured on rustc 1.97.0, edition 2024. A binary whose first line is `#![forbid(unsafe_code)]`
calls `dep::deref_first!(v)` from an ordinary dependency, and that `macro_rules!` expands to
`unsafe { *v.as_ptr() }`. `cargo run` prints `9` and exits 0. The same dependency exports a
second macro that expands a function named `Not_Snake_Case` holding an unused `mut` and an
unused variable: under `#![warn(unused_variables, unused_mut, non_snake_case)]` rustc prints
zero warnings, and the identical text written by hand in that file prints three.
`cargo clippy -p <crate> -- -D unsafe_code -D clippy::undocumented_unsafe_blocks` also reports
nothing.

So a hit from `rg -l '#!\[forbid\(unsafe_code\)\]'` is not proof that the crate compiles to no
unsafe, and no dependency filter closes the gap: `cargo tree --prefix none -p <crate> | rg
'\(proc-macro\)'` lists nothing for a crate that exports a plain `macro_rules!`. Read the
expansion instead. It is the only check that sees every case, and it prints the injected
`let x: u8 = unsafe { *v.as_ptr() };` in plain text:

```bash
cargo +nightly rustc -p <crate> --profile=check -- -Zunpretty=expanded | rg 'unsafe'
```

`-Zunpretty=expanded` needs nightly, so run this as a periodic audit for every crate that
applies a macro from a dependency. Do not make it a CI gate.

Removing `#![forbid(unsafe_code)]` from a crate is a reviewable event, not a detail. When you
remove it, state in the same commit which unsafe operation forced the change and where that
operation lives.

Keep the set of unsafe-carrying crates small. A workspace where only the FFI adapter contains
unsafe is far easier to audit than one where every crate may.

## Lint floor for unsafe crates

Severity: CRITICAL. These lints are not negotiable for a crate that contains `unsafe`.

```rust
// Required at the root of every crate that contains `unsafe`.
#![deny(unsafe_op_in_unsafe_fn)]
#![deny(
    clippy::undocumented_unsafe_blocks,
    clippy::multiple_unsafe_ops_per_block,
    clippy::missing_safety_doc,
)]
```

What each lint forces:

| Lint | Forces | What it catches in generated code |
| --- | --- | --- |
| `unsafe_op_in_unsafe_fn` | Every unsafe operation inside an `unsafe fn` must still sit inside an `unsafe { ... }` block | A model sees `unsafe fn` and stops writing a `// SAFETY:` line per operation. This lint forces the discipline back. |
| `clippy::undocumented_unsafe_blocks` | Every `unsafe { ... }` block needs a `// SAFETY:` comment above it | Bare unsafe blocks with no justification |
| `clippy::multiple_unsafe_ops_per_block` | Each unsafe operation needs its own SAFETY entry. One comment for a block that holds a deref, a cast, and a transmute is rejected. | One paragraph written for three operations, each of which has a different invariant |
| `clippy::missing_safety_doc` | Every `pub unsafe fn` needs a `# Safety` rustdoc section that lists the caller obligations | A `pub unsafe fn` shipped with no stated contract |

Put these lints in `[workspace.lints]` so every crate inherits them, and restate them at the
root of a crate that contains unsafe. The workspace entry enforces the rule; the crate-root
entry makes the rule visible to the person reading that crate. See the `rust-lints` skill for
the full lint policy.

### Checklist: adding the first unsafe to a previously safe crate

1. Add the lint floor above to `lib.rs` or `main.rs`.
2. If the crate carried `#![forbid(unsafe_code)]`, remove it in the same commit as the unsafe
   code, and state the reason. Do not remove it in advance.
3. Run `cargo clippy --locked -p <crate> --all-targets -- -D warnings` **before** you write the
   unsafe body. This confirms the lint floor is active and would reject a bare `unsafe { ... }`.
4. Write the unsafe body. Run clippy again and confirm the SAFETY comments satisfy it.
5. Add a Miri test for non-FFI code, or a `cargo-careful` test for FFI code. Gate the test with
   `#[cfg_attr(miri, ignore)]` when Miri cannot execute it.
6. Check that the new site fits a documented category in "When unsafe is legitimate" below. If
   it does not, add the category and say why it is acceptable.

## The five unsafe superpowers

An `unsafe` block unlocks exactly five operations. Nothing else about the code changes, and the
borrow checker keeps running.

1. Dereference a raw pointer (`*const T`, `*mut T`).
2. Call an unsafe function, including `extern "C"` and `extern "system"`.
3. Read or write a mutable static.
4. Implement an unsafe trait (`Send`, `Sync`).
5. Read a field of a union.

If your `unsafe` block does none of these, delete the block.

### `unsafe trait` and `unsafe fn` are separate axes

Item 4 covers the impl only. `unsafe trait T` binds the implementor: a plain `impl T for X` is
`error[E0200]: the trait T requires an unsafe impl declaration`. `unsafe fn` binds the caller.
Neither implies the other, so a safe method of an `unsafe trait` is called with no block. The
mirror trap costs as much: `unsafe impl` on a safe trait is
`error[E0199]: implementing the trait T is not unsafe`, so you cannot use the keyword to mark an
impl as delicate. Put each `# Safety` section where its obligation sits.
[references/unsafe-patterns.md](references/unsafe-patterns.md) has the axes table and a worked
`unsafe trait` with one safe method and one unsafe method.

## Panic safety at the FFI boundary

Severity: CRITICAL.

An unwind across an FFI boundary is undefined behavior. Every entry point that a foreign caller
can reach must contain the panic.

- Hand-rolled `extern "C"`: wrap the whole body in `std::panic::catch_unwind` and map the
  outcome to an integer status. Never write a bare `extern "C"` body. A bare body propagates the
  panic.
- JNI on `jni` 0.22: use `EnvUnowned::with_env` plus `into_outcome`. The tri-state result keeps a
  caught panic separate from a normal error. On `jni` 0.21 and earlier, and inside `JNI_OnLoad`
  and `JNI_OnUnload`, use `catch_unwind(AssertUnwindSafe(|| { ... }))` and throw a Java
  exception in the `Err` arm.
- UniFFI: `uniffi::setup_scaffolding!` plus `#[uniffi::export]` generates the guard. Do not
  hand-write one. Add a hand-rolled `extern "C"` beside UniFFI only for a measured reason, such
  as a zero-copy buffer handoff, and apply the `catch_unwind` rule to it.

[references/unsafe-patterns.md](references/unsafe-patterns.md) has the worked `extern "C"` and
JNI entry points.

### `catch_unwind` catches nothing under `panic = "abort"`

A release profile that sets `panic = "abort"` turns every panic into an immediate abort.
`catch_unwind` never runs. Check the profile that builds your `cdylib` before you rely on a
guard, and decide deliberately: an abort at the boundary is a defensible policy, but it must be
a choice, not a surprise.

## Taking ownership of a raw FFI handle

A `from_raw` constructor takes ownership of a handle the foreign runtime created. Three
invariants apply to every such call:

- The raw pointer is valid, and it belongs to the frame you are in.
- You call `from_raw` exactly once for that pointer. A second call is a double free.
- The resulting value does not outlive the frame that owns the handle.

State all three in the `// SAFETY:` comment above the call.

Centralize the duplication of a process-wide handle, such as a `JavaVM`, in one module. Wrap it
in a type that the rest of the workspace clones, and write the liveness rationale once in that
module. A second `from_raw` call for the same handle elsewhere in the tree is a regression, and
a grep for the constructor name is enough to catch it in review.

## Zero-copy buffer handoff

When a foreign caller hands you a buffer and you build a slice over it without a copy, the
caller must guarantee three things for the whole call. State all three in the SAFETY comment,
and state them again at the foreign call site:

1. The pointer is non-null and aligned for the element type.
2. Access is exclusive: no concurrent read or write from the caller.
3. The buffer stays valid for the entire duration of the call.

The same rule covers a slice built over a memory-mapped region. The mapping must outlive the
slice, and the region must not be mutated while the slice is live. A fabricated lifetime on such
a function is a promise the compiler cannot check. Keep the function private, and make the
owning type hold the mapping so the borrow checker enforces the relationship for every caller.
[references/ffi-layout-rules.md](references/ffi-layout-rules.md) has both worked slices.

## Pointer reads from untrusted byte buffers

Severity: CRITICAL. This is silent on x86-64 and fatal on ARM64.

`std::ptr::read(buf.as_ptr() as *const T)` requires `buf.as_ptr()` to be aligned for `T`. Bytes
that arrive from a network socket, a file, a memory mapping, or an FFI caller carry arbitrary
alignment.

On x86-64 a misaligned read is slower, and nothing else. On ARM64 the same read is either a
`SIGBUS` trap or garbage data, depending on kernel configuration. A test suite on an x86-64
development host passes; the device run corrupts data or crashes on the same input.

Rules:

1. Any `ptr::read` whose source is a `&[u8]` from I/O, FFI, or a mapping must be
   `ptr::read_unaligned`. No exceptions, even when the field happens to be aligned today.
2. Prefer `zerocopy::FromBytes` or `bytes::Buf` over raw pointer arithmetic on byte buffers.
   They remove the unsafe block and make endianness explicit.
3. Add a Miri test under `MIRIFLAGS="-Zmiri-tree-borrows"` for every new unsafe byte-buffer
   parser. Unaligned and provenance UB in this code is silent: it passes normal tests, clippy,
   and human review, because the wrong pointer operation usually still returns the right bytes
   on x86-64. Miri is the only check in the toolchain that sees it.

Grep audit:

```bash
rg 'ptr::read\(\s*[a-z_][a-z_0-9]*\.as_ptr\(\)\s*as\s*\*const' --type rust -n
rg 'transmute::<\s*&\[u8\]' --type rust -n
```

[references/unsafe-patterns.md](references/unsafe-patterns.md) has the bad, the correct, and the
two safe forms side by side.

## Transmute

Reach for the named conversion, not `transmute`. Every sound conversion has a std function that
does the same work and cannot be misapplied to the wrong pair of types: `f32::from_bits`,
`u32::from_ne_bytes`, `Box::into_raw`, `zerocopy::FromBytes`. The full sound-and-unsound table is
in [references/unsafe-patterns.md](references/unsafe-patterns.md).

## `mem::zeroed` for plain C structs

`mem::zeroed()` is sound only when all-zero bytes is a valid value of the type. A plain
`repr(C)` struct that the kernel or a C library fills in qualifies, such as `libc::ifreq`. The
SAFETY comment must say that the type has no Rust-level invariant and that the zero value is
overwritten before it is read.

Never use `mem::zeroed()` for a type with a Rust-level invariant: `bool`, an `enum`, `NonNull`,
a reference, `Box`, or any type with a non-trivial `Drop`. Use `MaybeUninit<T>` instead, and do
not read it until it is fully initialized.

## Syscall and ioctl wrappers

Every syscall wrapper must:

1. Carry a `# Safety` rustdoc block on the `unsafe fn` that lists the descriptor-validity and
   layout-match invariants.
2. Use `zeroed()` only for plain C structs, per the rule above.
3. Cast with `.cast()` rather than `as *mut _`. The method preserves pointer provenance, which
   matters to Miri's Tree Borrows model.
4. Check the return value and convert `io::Error::last_os_error()`. Never discard `errno`.

An `ioctl` call needs a SAFETY comment that states three facts: the descriptor is valid, the
struct fields the kernel reads are populated, and which request number is being issued and what
it does.

A C union field read is unsafe because the compiler cannot know which variant was written last.
Zero the struct first, then write the field before you read it. A descriptor that a foreign
caller passes in is borrowed, not owned: duplicate it through `BorrowedFd::borrow_raw` before
you take ownership, or the foreign runtime closes it under you.

[references/unsafe-patterns.md](references/unsafe-patterns.md) has the worked `getsockopt`,
`ioctl`, union, and descriptor-duplication calls.

## Pointer arithmetic

`wrapping_add` is always sound to compute; do not dereference an out-of-bounds result. `add` is
UB on the computation, not on the dereference, once the result leaves the allocation.
`offset_from` needs both pointers in one allocation. The worked calls are in
[references/unsafe-patterns.md](references/unsafe-patterns.md).

`NonNull` documents the non-null invariant in the type instead of in a comment. Build it with
`NonNull::new(Box::into_raw(b))`, and consume it back through `Box::from_raw` exactly once. The
worked round trip is in the same reference.

## Layout and pointer shape

These faults pass every safety review and still produce undefined behavior, because the unsafe
block is correct and the *shape* of the data is wrong. Each row is a rule that the compiler
cannot infer from a `// SAFETY:` comment.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `E0793: reference to field of packed struct is unaligned` | A method call, `match`, or `&mut` on a `#[repr(packed)]` field | Copy the field out, or `(&raw const f).read_unaligned()` |
| Correct on x86-64, traps on ARM | `bytes.as_ptr() as *const u32` then dereference | `u32::from_le_bytes`, `read_unaligned`, or `align_to` |
| `error: casting &T to &mut T is undefined behavior` | Mutation through a shared reference | `UnsafeCell`; there is no other sound way |
| A `*const` silently became a `*mut` | `as` on a pointer changes mutability too | `ptr.cast::<T>()`, and `cast_mut` when you mean it |
| `warning: uses type dyn Trait, which is not FFI-safe` | A fat pointer in a C signature | Pointer plus length, or an opaque handle |
| Two unrelated handles accepted at the same call | Every handle is `*mut c_void` | One zero-sized `#[repr(C)]` opaque type per handle |
| Memory grows once per callback registration | The boxed closure context is never reclaimed | Provide the unregister path that calls `Box::from_raw` |
| Double close, or a read from a reused descriptor | `RawFd` states no owner | `OwnedFd` to own, `BorrowedFd<'_>` to lend |
| A field is corrupt on one target only | Hand-rolled bitfield masks | A bitfield crate, plus a round-trip test against real bytes |
| Sound in debug, unsound in release | `debug_assert!` guards an unsafe block | `assert!`, which survives the shipping profile |
| A handle outlives the data it points at | A raw-pointer struct has no variance or drop check | `PhantomData<&'a T>`, `PhantomData<T>`, or `PhantomData<*mut T>` |

Promote both FFI-safety lints, because they cover opposite directions and one alone leaves half
the boundary unchecked:

```toml
[workspace.lints.rust]
improper_ctypes = "deny"              # types you import from C
improper_ctypes_definitions = "deny"  # types you export to C
```

For the worked pattern behind each row, see
[references/ffi-layout-rules.md](references/ffi-layout-rules.md).

## Drop hazards

Severity: CRITICAL for a public unsafe API.

Soundness must not assume `Drop` runs. `mem::forget` is safe, and `ManuallyDrop::new` is safe. A
public unsafe API whose soundness depends on a guard's destructor running is unsound, because a
caller can forget the guard without writing a single `unsafe` block.

State the invariant in the `# Safety` section, and design the API so that forgetting the guard
is either impossible or harmless. The standard library shows both correct designs:

- `thread::spawn` requires `'static`. No guard is needed; the lifetime carries the safety.
- `thread::scope` captures the scope by reference inside the closure, so the borrow checker
  prevents the scope from being forgotten while a thread still runs.

A future polled inside `select!` can be dropped at any `.await`. Do not make a future's
correctness depend on its `Drop` running.

`Drop::drop` must not panic. When a panic is already unwinding and a `Drop` implementation
panics, the process aborts immediately. A double panic cannot be caught by `catch_unwind`. There
is no recovery path.

Any `.unwrap()`, `.expect()`, or panicking call inside `drop()` is a bomb that fires only while
an error is already in flight, which is the worst possible moment. `self.flush().unwrap()` in a
`Drop` impl is the common shape.

Rule: move every fallible cleanup into an explicit `close()`, `commit()`, or `flush()` that
returns `Result`. Leave `drop()` as a best-effort fallback that only logs. The worked pair is in
[references/unsafe-patterns.md](references/unsafe-patterns.md).

## One unsafe block breaks local reasoning

Severity: CRITICAL.

A single unsafe block anywhere in the call graph, including inside a dependency, can invalidate
a type invariant that safe code elsewhere relies on. You cannot judge soundness by reading one
function.

The failure shape: a dependency calls `str::from_utf8_unchecked` on a buffer whose validation
was defeated. The resulting `&str` violates a language invariant. Your safe code calls
`.chars()` on it and panics or triggers UB. The unsafe is in the dependency; the crash is in
your code.

Action when you audit:

1. `rg 'from_utf8_unchecked|from_raw_parts|String::from_raw_parts' --type rust -n`. Every hit
   needs a SAFETY comment that traces back to where the invariant is established.
2. `cargo deny --locked check` to surface a dependency with a known soundness advisory. See the
   `rust-security` skill.
3. When a dependency's unsafe transits through your API, restate the assumed invariant in your
   own `# Safety` section.

## Manual `unsafe impl Send` or `Sync`

Severity: CRITICAL.

A manual `unsafe impl Send for T` or `unsafe impl Sync for T` is a promise the compiler accepts
without checking. It stays accepted after the fields change.

The failure shape: you write the impl for `MyWrapper<T>`. Later `T` gains an `Rc<_>` field.
`Rc` is neither `Send` nor `Sync`, but your blanket impl still applies, so the compiler accepts
sending `MyWrapper<T>` across a thread. A double free or a data race follows at runtime.

Before you write the impl:

1. List every field type. For each, confirm it is `Send` or `Sync`, or state why the wrapper
   upholds the invariant despite the field.
2. Check the trait impls on the type. None may hand out shared access to non-`Sync` state.
3. Assert the auto trait on each field type at compile time, so a later change to an inner type
   fails the build instead of failing in production. The manual impl on the wrapper is
   unconditional, so assert the fields, not the wrapper. A
   `const _: () = { fn assert_send<T: Send>() {} let _ = assert_send::<Inner>; };` at module
   scope needs no dependency, and a field type that gains an `Rc<_>` fails it with E0277. Only a
   negative assertion, such as `assert_not_impl_all!`, still needs the `static_assertions`
   crate, because stable Rust has no clean form for a negative bound. That crate is stuck at
   1.1.0, released 2019-11-03. The worked assertion is in
   [references/unsafe-patterns.md](references/unsafe-patterns.md).
4. Tag the impl with a `// SAFETY:` comment that names the fields audited and the argument.

Objects from a C or C++ library are usually not thread-safe. Do not assume otherwise because
the Rust binding compiles.

## Reference fabrication

Severity: CRITICAL. Never hand a caller a `&T` or a `&mut T` built from `RefCell::as_ptr`.
`as_ptr` does not touch the dynamic borrow counter, so a later `borrow_mut()` succeeds instead
of panicking, and safe code mutates behind a live shared reference. Yield `Ref<'a, T>` instead,
so the caller holds the borrow. Treat the pattern as UB on inspection: Miri reports it only when
a test interleaves the fabricated reference with a mutation, so a clean Miri run proves nothing
here. Do not generalize the rule to `Cell::as_ptr` or `UnsafeCell::get`, which are the intended
raw-access APIs. The defect is specific: handing out a reference that outlives the call, from a
cell the code only shares.

The `ManuallyDrop<String>` plus `String::from_raw_parts` form is severity HIGH. It fabricates a
`&String` from a `&str`, because the layouts happen to line up. It is formally unsound, because
the `String` was never owned here and the pointer has the wrong provenance. It is also fragile:
a change to the internal layout or the allocator breaks it silently. Accept `&str` or
`impl AsRef<str>` instead. The only defensible context is legacy interop that cannot be changed.
There, document the full invariant, test under `MIRIFLAGS="-Zmiri-tree-borrows"`, and gate the
call with `cfg(not(miri))` when Miri rejects it.

[references/unsafe-patterns.md](references/unsafe-patterns.md) has the `RefCell::as_ptr`
demonstration and the three API fixes.

## Symbol collision in `cdylib` crates

Severity: CRITICAL.

Rust 2024 requires `#[unsafe(no_mangle)]`, `#[unsafe(export_name = "...")]`, and
`#[unsafe(link_section = "...")]`. The `unsafe` wrapper marks a hazard that predates the
edition: when two compilation units export the same unmangled symbol, the linker picks one
silently, and the wrong function runs. There is no compile-time diagnostic.

The JNI naming convention, `Java_<package>_<class>_<method>`, gives natural uniqueness. Any
other unmangled symbol does not. Audit every non-JNI export for uniqueness across all native
libraries that the host process may load at the same time, including libraries you do not own.
The fourth command in "Purpose" lists every unmangled export in the tree.

## When unsafe is legitimate

| Case | Verdict |
| --- | --- |
| An FFI export or import: `extern "C"`, `extern "system"`, handle construction | Legitimate |
| An OS-level call with no safe wrapper: `ioctl`, `setsockopt`, signal handling | Legitimate |
| A zero-copy handoff of a large buffer, after a copy was measured and rejected | Legitimate |
| SIMD intrinsics on a hot path, after a benchmark justified them | Legitimate |
| Protocol and format parsing | Use `zerocopy` or `bytes` under `#![forbid(unsafe_code)]` |
| Domain logic, configuration, state | Use `#![forbid(unsafe_code)]` |
| Anything a safe crate already wraps | Use the crate |

Performance is a reason only after a measurement. See the `rust-performance` skill for how to
produce one.

## Audit checklist

Use this when you review an unsafe block:

- [ ] Is there a `// SAFETY:` comment, and does it name the invariant that is upheld?
- [ ] For a raw pointer: non-null, aligned, initialized, and valid for the whole access?
- [ ] For an `extern` entry point: is the body wrapped in `catch_unwind` or an equivalent guard?
- [ ] Does the release profile set `panic = "abort"`, which makes that guard inert?
- [ ] For a `from_raw` handle: is the raw value valid and consumed exactly once?
- [ ] For a slice over a foreign buffer: is exclusive access guaranteed for the whole call?
- [ ] For a mapping: does the mapping outlive every slice built over it?
- [ ] For `mem::zeroed()`: is the type a plain C struct with no Rust-level invariant?
- [ ] For a union field: was the field written before it was read?
- [ ] For `unsafe impl Send` or `Sync`: is thread safety actually guaranteed by every field?
- [ ] Does any reference point into a `#[repr(packed)]` struct, or into unaligned bytes?
- [ ] Does any C signature carry a fat pointer: `dyn Trait`, a slice, or `&[T]`?
- [ ] Does every boxed callback context have an unregister path that reclaims it?
- [ ] Does a check that guards an unsafe block use `assert!` rather than `debug_assert!`?
- [ ] Is the unsafe block as small as it can be?
- [ ] Does any `Drop::drop` contain `.unwrap()`, `.expect()`, or another panicking call?
- [ ] Does any unmangled symbol collide with one in another library loaded at the same time?
- [ ] Can the code run under Miri with Tree Borrows?

```bash
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked
```

Tree Borrows is the aliasing model published at PLDI 2025 and is the recommended default. It
accepts more valid unsafe patterns than Stacked Borrows, so code that the older model rejected
may pass now. See the `rust-sanitizers-miri` skill for the full Miri and sanitizer workflow.

## Related skills

- `rust-sanitizers-miri` — Miri, Tree Borrows, and the sanitizers that check unsafe code
- `rust-panic-safety` — the panic policy that the FFI guards in this skill implement
- `rust-jni` — the JNI boundary in full, including threading and reference frames
- `uniffi-boundary` — the generated boundary that removes most hand-written unsafe
- `memory-model` — atomics, aliasing, and ordering
- `rust-lints` — where the lint floor above is configured
- `rust-debugging` — triaging a crash that unsafe code caused

For worked patterns, see [references/unsafe-patterns.md](references/unsafe-patterns.md).
