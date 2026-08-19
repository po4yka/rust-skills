# Miri UB Patterns Reference

Worked examples of the undefined behaviour (UB) classes that Miri detects, the
message Miri prints, and the correct pattern. Use this file when a Miri run
fails and you need the shape of the defect.

## Undefined behaviour caught by Miri

### Pointer provenance violations

A pointer stays valid only while the allocation it points into stays at the
same address. Any operation that can reallocate invalidates every pointer
derived before it.

```rust
// Wrong: the pointer is reused after a reallocation.
let mut v: Vec<u32> = Vec::with_capacity(4);
let ptr = v.as_ptr();
v.push(1); v.push(2); v.push(3); v.push(4);
v.push(5);                  // Capacity exceeded: the buffer moves.
let val = unsafe { *ptr };  // UB: the pointer is dangling.
// Miri: pointer must be in-bounds at offset 0

// Correct: derive the pointer after the last operation that can reallocate.
v.push(5);
let ptr = v.as_ptr();       // Fresh pointer into the new buffer.
```

Same defect class:

- A slice taken from a `Vec` and held across a `push`, `insert`, `reserve`,
  `extend` or `shrink_to_fit`.
- A pointer into a `String` held across a `push_str`.
- A pointer into a `HashMap` value held across an insert.

### Transmutation errors

A transmute never validates. Miri validates on the first use of the value.

```rust
// UB: an enum discriminant that no variant uses.
#[repr(u8)]
enum Kind { A = 0, B = 1, C = 2 }

let x: u8 = 99;
let k = unsafe { std::mem::transmute::<u8, Kind>(x) };  // UB
// Miri: enum value has invalid tag

// UB: a bool that is not 0 or 1.
let x: u8 = 2;
let b = unsafe { std::mem::transmute::<u8, bool>(x) };  // UB

// UB: a reference to unaligned data.
let data = [0u8; 5];
let ptr = data[1..].as_ptr() as *const u32;  // Not 4-byte aligned.
let val = unsafe { *ptr };                   // UB on most platforms.
```

Correct patterns:

- Decode an external tag with `TryFrom` and return an error for an unknown
  value. Never transmute a byte that came from a file, a socket or FFI.
- Read a field out of an unaligned byte buffer with `ptr::read_unaligned`, or
  with `u32::from_le_bytes` on a copied array. Both are correct; the byte-array
  form needs no `unsafe`.

### Stacked Borrows violations

A raw pointer and a reference derived from it cannot both be used. The
reborrow must end before the raw pointer is used again.

```rust
// UB: the raw pointer is used while a reborrow is live.
let mut x = 5u32;
let raw = &mut x as *mut u32;
let r = unsafe { &mut *raw };   // Reborrow of the raw pointer.
let _ = unsafe { *raw };        // UB: `raw` used while `r` is live.
// Miri: attempting a read access ... tag does not exist in the borrow stack

// Correct: end the reborrow scope before the raw access.
{
    let r = unsafe { &mut *raw };
    *r = 10;
}
let _ = unsafe { *raw };        // Now valid: the reborrow has ended.
```

Run this class of code under both aliasing models. A defect that Stacked
Borrows misses can appear under Tree Borrows, and the reverse:

```bash
cargo +nightly miri test --locked
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked
```

### Uninitialized memory

```rust
use std::mem::MaybeUninit;

// UB: a read before initialization.
let mut uninit: MaybeUninit<u64> = MaybeUninit::uninit();
let ptr = uninit.as_mut_ptr();
let val = unsafe { ptr.read() };  // UB
// Miri: using uninitialized data, but this operation requires
//       initialized memory

// Correct: write first, then read.
unsafe { ptr.write(42) };
let val = unsafe { ptr.read() };  // OK

// UB: partial initialization.
let mut buf = MaybeUninit::<[u8; 4]>::uninit();
let p = buf.as_mut_ptr() as *mut u8;
unsafe { p.write(1) };             // Only byte 0 is initialized.
let arr = unsafe { buf.assume_init() };  // UB: bytes 1..4 are uninitialized.
```

Correct pattern for a buffer that you fill later: allocate with
`vec![0u8; len]`. The zero fill is cheap, it is safe, and the optimizer removes
it when the whole buffer is overwritten. Reach for `MaybeUninit` only after a
measurement shows the fill is a real cost.

### Lifetime extension

```rust
// UB: a reference to a local escapes the function.
fn bad<'a>() -> &'a u32 {
    let x = 42u32;
    unsafe { &*(&x as *const u32) }  // UB: dangling after return.
}
// Miri: pointer to alloc ... was dereferenced after this allocation got freed
```

The borrow checker rejects the safe form of this code. A cast through a raw
pointer defeats the check and produces UB instead of a compile error. Never use
a raw-pointer cast to silence a lifetime error.

### Aliasing through `Box` and FFI

```rust
// UB: `Box` and a raw pointer both claim unique access.
let mut boxed = Box::new(State::new());
let raw: *mut State = &mut *boxed as *mut _;
unsafe { ffi_register(raw); }  // The foreign side stores `raw`.
boxed.field = 42;              // A load through the Box, which LLVM treats
                               // as noalias.
// Miri with -Zmiri-tree-borrows reports the aliasing violation.
```

Correct patterns:

- `Box::into_raw` transfers ownership. Never touch the original `Box` again.
  Recover it with `Box::from_raw` exactly once, and only when the foreign side
  has released it.
- `Pin<Box<T>>` when the foreign side only borrows the pointer.

## MIRIFLAGS quick reference

The flag table and the recommended combinations are in `SKILL.md`, section 9.

## Miri limitations

Miri interprets Rust. It cannot execute anything that is not Rust.

Miri cannot run:

- `extern "C"` or `extern "system"` functions that have no Miri shim. This
  includes every entry point of a C or C++ library reached through a `-sys`
  crate.
- Generated FFI scaffolding, for example a UniFFI or JNI binding layer.
- JNI calls, which need a live JVM.
- Inline assembly: `asm!` and `global_asm!`.
- Platform-specific syscalls such as `epoll`, `ioctl` and `io_uring`. File-backed
  `mmap` is also out of reach; Miri shims only a small set of libc calls.
- Long-running programs. The interpreter overhead is about 100 times.

### Workarounds

The stub, skip and exclude strategies, the selection table and the stubbing
rules are in `SKILL.md`, section 6. Apply them from there. Every path that Miri
now skips needs an ASan or HWASan run instead.

## Sanitizer comparison for Rust

| Tool | Detects | Requires | Overhead |
|---|---|---|---|
| Miri | UB in safe and unsafe Rust, per the language rules | nightly; pure Rust only | about 100x |
| ASan | Heap and stack memory errors at runtime | nightly for the Rust build | about 2x |
| HWASan | Same class as ASan, tag-based | nightly; ARM64, Android 10+ | about 15% RAM, about 5% CPU |
| MTE | Same class as HWASan, hardware tags | arm64 Android 14+, supporting SoC | about 3% in async mode |
| TSan | Data races at runtime | nightly for the Rust build | 5x to 15x |
| MSan | Reads of uninitialized memory | nightly; every object instrumented | about 3x |
| UBSan | Integer UB, null dereference and similar, inside C or C++ code | clang or gcc `-fsanitize=undefined` on the C or C++ dependency; rustc has no UBSan option | under 2x |
| `loom` | Exhaustive interleavings of an atomics-based structure | stable | high, bounded model |
| `cargo check --locked` | Type and lifetime errors | stable | fast |
| Clippy | Common bug patterns | stable | fast |

## Coverage decision table

Use this table to decide which tool to run against each crate in a workspace.

| Crate shape | Miri | Sanitizers | Notes |
|---|---|---|---|
| `#![forbid(unsafe_code)]`, pure Rust | Yes | Optional | Miri still finds UB reached through dependencies |
| Hand-written `unsafe` on raw pointers | Yes, required | ASan, and TSan if threaded | Run both aliasing models |
| Uses `MaybeUninit` or partial initialization | Yes, required | MSan | Miri gives the exact field |
| Concurrency with atomics | Yes, with `-Zmiri-seed` and `-Zmiri-num-cpus` | TSan | Add `loom` for exhaustive coverage |
| Depends on a `-sys` crate that links C or C++ | No | ASan or HWASan, required | Exclude from the Miri run |
| Declares its own `extern "C"` functions | Yes, with `#[cfg(miri)]` stubs | ASan on the real path | The stub removes Miri coverage of the foreign side |
| Generated FFI scaffolding, for example UniFFI or JNI | No | HWASan or MTE on the device | Gate the crossing tests with `#[cfg_attr(miri, ignore)]` |
| Inline assembly or `std::arch` SIMD | No, unless a fallback exists | ASan on the real path | Add a pure-Rust fallback behind `#[cfg(miri)]` |
