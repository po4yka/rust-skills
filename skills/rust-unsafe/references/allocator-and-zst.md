# Allocators, zero-sized values, and cells on Rust 1.100

## Keep the allocator with the allocation

Rust 1.100 stabilizes the core `Allocator` API and allocator parameters for
`Box` and `Vec`. This does not stabilize custom-allocator constructors for every
collection or for `Rc` and `Arc`. Check the method's stability and the package
MSRV before use. `Allocator` and `GlobalAlloc` are separate traits.

Use `Box::into_raw_with_allocator` or `Vec::into_raw_parts_with_allocator` when
ownership leaves Rust. Keep the allocator with the pointer, length, and capacity.
Reconstruct with the matching `_in` function. Plain `Box::from_raw` uses the
global allocator and is not a general inverse for a custom allocation.

```rust,run
use std::alloc::System;

fn main() {
    let mut values = Vec::with_capacity_in(4, System);
    values.extend([10_u32, 20]);
    let (ptr, len, cap, allocator) = values.into_raw_parts_with_allocator();
    // SAFETY: These parts and this allocator came from the same live Vec.
    // No other owner frees or accesses the allocation during reconstruction.
    let values = unsafe { Vec::from_raw_parts_in(ptr, len, cap, allocator) };
    assert_eq!(values.as_slice(), &[10, 20]);

    let value = Box::new_in(7_u32, System);
    let (ptr, allocator) = Box::into_raw_with_allocator(value);
    // SAFETY: The pointer and allocator came from this Box; ownership is unique.
    let value = unsafe { Box::from_raw_in(ptr, allocator) };
    assert_eq!(*value, 7);
}
```

Run `cargo run --locked --example <name>` for these round trips. It does not
prove a custom allocator's
alignment, lifetime, or deallocation contract. Test its failure paths and use
Miri on a compatible nightly when available.

## Construct a zero-sized value only with its invariants

Prefer a safe constructor or `Default`. Use `core::mem::conjure_zst::<T>()` only
when `T` is an inhabited zero-sized type and the value preserves its safety
invariants. A zero size does not prove that a type is inhabited. `!` and an empty
enum have no valid value. A zero-sized lock or interpreter token can require
external state even though it has no bytes. `conjure_zst` panics for a nonzero
size; that check does not establish the safety invariants.

## UnsafeCell still needs exclusive access

Rust 1.100 adds `UnsafeCell::replace`, `as_ref_unchecked`, and `as_mut_unchecked`.
They do not permit conflicting references or data races. Prove the required
access for the complete returned reference lifetime. Prefer `get_mut` when an
exclusive borrow of the cell is available. Keep synchronization and reentrancy
proofs in the safety comment.

## Sources

- [Allocator](https://doc.rust-lang.org/1.100.0/std/alloc/trait.Allocator.html)
- [conjure_zst](https://doc.rust-lang.org/1.100.0/core/mem/fn.conjure_zst.html)
- [UnsafeCell](https://doc.rust-lang.org/1.100.0/std/cell/struct.UnsafeCell.html)
