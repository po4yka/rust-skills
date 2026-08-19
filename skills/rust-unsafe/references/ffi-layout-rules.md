# FFI layout and pointer-shape rules

Rules about the *shape* of data that crosses a boundary: alignment, pointer width, field
layout, and handle ownership. [SKILL.md](../SKILL.md) covers the safety contract of an unsafe
block. This file covers the cases where the contract is met and the layout is still wrong.

Every example in this file compiles on rustc 1.97, edition 2024.

## Never reference a field of a `#[repr(packed)]` struct

A packed struct has no padding, so a field can sit at a misaligned address. A reference must
always be aligned. Since Rust 1.72 the compiler rejects the reference outright:

```text
error[E0793]: reference to field of packed struct is unaligned
  = note: creating a misaligned reference is undefined behavior
          (even if that reference is never dereferenced)
```

A method call, a `match` on the field, and a `&mut` binding all create a reference. They all
fail. Copy the field out, or go through a raw pointer:

```rust
#[repr(C, packed)]
pub struct Packet {
    pub header: u8,
    pub value: u32,   // offset 1, not 4
}

// Copying is safe: no reference is created.
pub fn value_copy(p: &Packet) -> u32 {
    p.value
}

// Reading through a raw pointer is safe when the read tolerates misalignment.
pub fn value_read(p: &Packet) -> u32 {
    // SAFETY: `&raw const` never creates a reference, and `read_unaligned` does
    // not require alignment. The field is initialized because `p` is a reference
    // to a fully initialized `Packet`.
    unsafe { (&raw const p.value).read_unaligned() }
}

pub fn set_value(p: &mut Packet, value: u32) {
    // SAFETY: same as above; `write_unaligned` does not require alignment.
    unsafe { (&raw mut p.value).write_unaligned(value) }
}
```

Use `&raw const` and `&raw mut`. They are the native syntax since Rust 1.82 and they replace
`ptr::addr_of!` and `ptr::addr_of_mut!`. The macros still work, but the operator is the form to
write in new code.

The clippy lint `unaligned_references` no longer exists. Do not put it in `workspace.lints`:
clippy rejects an unknown lint name and the whole lint job fails.

Prefer a layout that avoids the problem. A byte-array field needs no packing and no unaligned
access:

```rust
#[repr(C)]
pub struct PacketBytes {
    pub header: u8,
    pub value: [u8; 4],
}

impl PacketBytes {
    // No unsafe at all. The wire order is explicit, which also fixes endianness.
    pub fn value(&self) -> u32 {
        u32::from_be_bytes(self.value)
    }
}
```

## Never cast a byte pointer to a wider type and dereference it

A `&[u8]` from I/O carries no alignment guarantee. A cast to `*const u32` compiles, and the
dereference is undefined behavior when the address is not 4-byte aligned. On x86-64 it produces
the right answer, which is why the bug reaches production. On ARM and RISC-V it traps.

Three correct options, in order of preference:

```rust
// 1. Safe conversion from a fixed-size byte array. No unsafe, explicit endianness.
pub fn read_u32(bytes: &[u8]) -> Option<u32> {
    Some(u32::from_le_bytes(bytes.get(..4)?.try_into().ok()?))
}

// 2. An unaligned read when the source really is a byte stream.
pub fn read_u32_unaligned(bytes: &[u8]) -> Option<u32> {
    if bytes.len() < 4 {
        return None;
    }
    // SAFETY: the length is checked, and `read_unaligned` does not require
    // alignment. `u32` has no invalid bit pattern, so any four bytes are valid.
    Some(unsafe { bytes.as_ptr().cast::<u32>().read_unaligned() })
}

// 3. `align_to` when a bulk read is worth the split. It returns the unaligned
//    head, the aligned middle, and the unaligned tail.
pub fn aligned_middle(bytes: &[u8]) -> usize {
    // SAFETY: `u32` has no invalid bit pattern and no padding, so reinterpreting
    // aligned bytes as `u32` is valid.
    let (_head, middle, _tail) = unsafe { bytes.align_to::<u32>() };
    middle.len()
}
```

Enable `clippy::cast_ptr_alignment`. It catches the `as *const u32` form. It does not catch
every case, so the rule stands on its own.

Never use `align_to` for a type that has an invalid bit pattern. `bool`, `char`, a `NonZero`
type, and every enum have invalid bit patterns. Reinterpreting arbitrary bytes as one of them is
undefined behavior even when the alignment is correct.

## A slice over a caller-owned buffer or a mapping

State all three guarantees in the SAFETY comment, and state them again at the foreign call site:

```rust
// SAFETY: `ptr` points at the start of a caller-allocated RGBA8 buffer of
// `width * height * 4` bytes. The caller guarantees:
//   1. Non-null, and aligned for `u32`.
//   2. Exclusively writable: no concurrent read or write from the caller.
//   3. Valid for the entire duration of this call.
let pixels = unsafe { std::slice::from_raw_parts_mut(ptr.cast::<u32>(), (width * height) as usize) };
```

The same rule covers a slice built over a memory-mapped region. The mapping must outlive the
slice, and the region must not be mutated while the slice is live:

```rust
/// # Safety
/// `base` must be the start of a valid mapping of at least `len` bytes. The
/// mapping must stay alive for `'map`, and must not be written while the
/// returned slice is live.
unsafe fn mmap_as_slice<'map>(base: *const u8, len: usize) -> &'map [u8] {
    // SAFETY: the caller guarantees the mapping is valid, read-only, and lives
    // for at least `'map`.
    unsafe { std::slice::from_raw_parts(base, len) }
}
```

A fabricated lifetime like `'map` above is a promise the compiler cannot check. Keep the
function private, and make the owning type hold the mapping so the borrow checker enforces the
relationship for every caller.

## Never cast `&T` to `&mut T`

This is a hard error, not a lint you can allow:

```text
error: casting `&T` to `&mut T` is undefined behavior, even if the reference is unused,
       consider instead using an `UnsafeCell`
  = note: `#[deny(invalid_reference_casting)]` on by default
```

The clippy lint `cast_ref_to_mut` was renamed to the rustc lint `invalid_reference_casting`. If
you need mutation through a shared reference, the type must contain an `UnsafeCell`. There is no
other sound way to get one.

## Prefer `pointer::cast` over `as`

```rust
pub fn to_u32(p: *const u8) -> *const u32 {
    p.cast::<u32>()
}
```

`as` on a pointer silently changes mutability as well as the pointee type. `cast` changes only
the pointee type, so a `*const` cannot become a `*mut` by accident. Use `cast_mut` and
`cast_const` when you do intend the change, so the intent is written down. Enable
`clippy::ptr_as_ptr`.

## Never put a fat pointer in a C signature

A trait object pointer and a slice pointer are two words wide. A C pointer is one word:

| Type | Size on a 64-bit target |
| --- | --- |
| `*const u8` | 8 |
| `*const dyn Trait` | 16 |
| `*const [u8]` | 16 |
| `&[u8]` | 16 |

C cannot build the second word, and it cannot read it. The compiler warns:

```text
warning: `extern` block uses type `dyn T`, which is not FFI-safe
  = note: trait objects have no C equivalent
  = note: `#[warn(improper_ctypes)]` on by default
```

`improper_ctypes` covers declarations you import. `improper_ctypes_definitions` covers
`extern "C"` functions you export. Promote both to `deny` in `workspace.lints`.

Pass a slice as a pointer and a length. Pass a trait object behind an opaque handle that the
Rust side owns, as in the next section.

## Use a distinct opaque type, not `c_void`

`*mut c_void` accepts any pointer, so the compiler cannot tell one handle from another. A
zero-sized opaque struct gives each handle its own type and restores the type check:

```rust
use core::marker::{PhantomData, PhantomPinned};

#[repr(C)]
pub struct Handle {
    _data: [u8; 0],
    // Not Send, not Sync, not Unpin, and not constructible outside this module.
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

unsafe extern "C" {
    pub unsafe fn handle_new() -> *mut Handle;
    pub unsafe fn handle_free(handle: *mut Handle);
}
```

The `[u8; 0]` field makes the type zero-sized with a C-compatible layout. The `PhantomData`
field removes the auto traits, so the handle cannot be sent to another thread by accident.

## Pass a closure to C as data plus a function pointer

C has no closures. Split the closure into a plain `extern "C"` function and a context pointer.
The function is the code, the context is the data.

```rust
use std::os::raw::c_void;
use std::panic::{catch_unwind, AssertUnwindSafe};

unsafe extern "C" {
    unsafe fn c_register(
        callback: Option<unsafe extern "C" fn(i32, *mut c_void)>,
        context: *mut c_void,
    );
}

unsafe extern "C" fn trampoline<F: FnMut(i32)>(value: i32, context: *mut c_void) {
    if context.is_null() {
        return;
    }
    // SAFETY: `context` is the pointer that `register` leaked from a `Box<F>`.
    // The C library returns it unchanged and calls back on the registering
    // thread only, so no other reference to it exists during this call.
    let callback = unsafe { &mut *(context as *mut F) };
    // A panic must not unwind into C. See the panic-safety section in SKILL.md.
    let _ = catch_unwind(AssertUnwindSafe(|| callback(value)));
}

pub fn register<F: FnMut(i32) + 'static>(callback: F) -> *mut c_void {
    let context = Box::into_raw(Box::new(callback)) as *mut c_void;
    // SAFETY: `trampoline::<F>` reads `context` as `*mut F`, which is the type
    // that was boxed. The box stays alive until `unregister` reclaims it.
    unsafe { c_register(Some(trampoline::<F>), context) };
    context
}

/// # Safety
/// `context` must be a pointer that `register::<F>` returned, with the same `F`,
/// and the C library must have stopped calling the callback.
pub unsafe fn unregister<F: FnMut(i32) + 'static>(context: *mut c_void) {
    // SAFETY: the caller guarantees the pointer came from `Box::into_raw` on a
    // `Box<F>` and that no callback is in flight.
    drop(unsafe { Box::from_raw(context as *mut F) });
}
```

The monomorphized `trampoline::<F>` is what makes this work: each `F` gets its own symbol with
the C ABI. Always provide the unregister path. Without it the box leaks, and the leak grows once
per registration.

Use `Option<unsafe extern "C" fn(..)>` for a nullable callback, not a raw pointer. A function
pointer is non-null, so `Option` of one is still a single word and it maps to a C null.

## Use `OwnedFd` and `BorrowedFd`, not `RawFd`

A `RawFd` is an `i32`. It says nothing about who closes it, so a double close or a
use-after-close is a plain integer bug that the compiler cannot see. The I/O safety types encode
the ownership:

```rust
use std::os::fd::{AsFd, AsRawFd, BorrowedFd, FromRawFd, OwnedFd};

// Borrow: the lifetime ties the descriptor to the owner.
pub fn borrow(file: &std::fs::File) -> BorrowedFd<'_> {
    file.as_fd()
}

// Own: closing is now the type's job.
pub fn own(file: std::fs::File) -> OwnedFd {
    OwnedFd::from(file)
}

/// # Safety
/// `fd` must be open, and no other object may own it. This function takes
/// ownership; the descriptor is closed when the returned value is dropped.
pub unsafe fn adopt(fd: i32) -> OwnedFd {
    // SAFETY: the caller guarantees sole ownership of an open descriptor.
    unsafe { OwnedFd::from_raw_fd(fd) }
}
```

Use `as_raw_fd` only at the call that hands the number to C, and keep the owner alive across
that call. Windows has the same three types under `std::os::windows::io` for handles and
sockets.

## Do not hand-roll bitfields

C bitfield layout is implementation defined. The bit order inside a storage unit, the straddling
rule, and the padding all vary by compiler and by target. A hand-written mask and shift pair
encodes one compiler's choice, and the mismatch appears as a corrupted field on a different
target.

Represent the storage unit as a plain integer and generate the accessors. `bitflags` covers flag
sets. `modular-bitfield` and `bitfield-struct` cover packed fields with explicit widths. Whatever
you pick, write a round-trip test against a byte vector captured from the real peer.

## Use `assert!`, not `debug_assert!`, to guard an unsafe block

`debug_assert!` disappears in a release build. A check that guards an unsafe block must survive
the profile that ships:

```rust
/// # Safety
/// `index` must be in bounds for `slice`.
pub unsafe fn get_unchecked_checked<T>(slice: &[T], index: usize) -> &T {
    assert!(index < slice.len(), "index {index} out of bounds");
    // SAFETY: the assertion above proved the index is in bounds.
    unsafe { slice.get_unchecked(index) }
}
```

Use `debug_assert!` only for an invariant that is already guaranteed by construction and that
you check to catch a refactor. If the check is what makes the unsafe block sound, it is not a
debug assertion.

## Attach `PhantomData` to a struct that holds raw pointers

A raw pointer is invariant in its pointee and carries no lifetime, so a struct that holds one
gets no variance and no drop check from the compiler. State the intent:

```rust
use core::marker::PhantomData;

// Behaves like `&'a T`: covariant in `T`, and `'a` is enforced.
pub struct Ref<'a, T> {
    ptr: *const T,
    _marker: PhantomData<&'a T>,
}

// Behaves like `T`: the drop checker knows a `T` may be dropped here.
pub struct Owned<T> {
    ptr: *mut T,
    _marker: PhantomData<T>,
}
```

`PhantomData<&'a T>` for a borrow, `PhantomData<T>` for ownership, and
`PhantomData<*mut T>` to remove `Send` and `Sync`. Getting this wrong produces a type that
compiles and outlives its data.

## Restrict `union` to C interop

A `union` has no tag, so the compiler cannot check which variant is live. Reading a field that
was never written is undefined behavior.

- Use a `union` only to match a C type that is itself a union.
- Never store a reference or a lifetime-carrying type in a variant. The compiler cannot
  determine when the borrow ends.
- Pair every union with the discriminant that the C API uses, and read the discriminant first.
- Prefer an `enum` whenever the layout is yours to choose. It carries the tag for you.

## Related

- [unsafe-patterns.md](unsafe-patterns.md) — safety comments, transmute, Miri, and clippy runs
- [SKILL.md](../SKILL.md) — the lint floor, panic guards, and the audit checklist
