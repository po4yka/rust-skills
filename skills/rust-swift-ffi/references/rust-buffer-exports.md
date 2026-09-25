# Rust buffer exports for Swift

The Rust side of the `rs_buffer_t` contract from `SKILL.md`, with borrowed
Swift input. CI compiles and runs this block on the pinned toolchain. Miri
(nightly 2026-05-15, Stacked Borrows and Tree Borrows) reports no undefined
behavior and no leak for it.

```rust,run
use std::ptr;

#[repr(C)]
pub struct RsBuffer {
    ptr: *mut u8,
    len: usize,
    capacity: usize,
}

impl RsBuffer {
    const EMPTY: RsBuffer = RsBuffer { ptr: ptr::null_mut(), len: 0, capacity: 0 };

    fn from_vec(bytes: Vec<u8>) -> RsBuffer {
        if bytes.is_empty() {
            return RsBuffer::EMPTY; // drops any spare capacity now
        }
        let (ptr, len, capacity) = bytes.into_raw_parts(); // Rust 1.93+
        RsBuffer { ptr, len, capacity }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rs_buffer_release(buffer: RsBuffer) {
    if buffer.ptr.is_null() {
        return;
    }
    if buffer.len > buffer.capacity {
        return; // a changed value from C; log the contract violation and leak
    }
    // SAFETY: outside this module only `from_vec` builds a non-null `RsBuffer`
    // (private fields, not `Copy`), so the parts come from one `Vec` and are
    // consumed once. A C caller must pass the unchanged value once.
    drop(unsafe { Vec::from_raw_parts(buffer.ptr, buffer.len, buffer.capacity) });
}

/// # Safety
/// A non-null `ptr` points to `len` initialized bytes that stay valid and
/// unchanged until the call returns.
unsafe fn borrowed<'a>(ptr: *const u8, len: usize) -> Option<&'a [u8]> {
    if len == 0 {
        return Some(&[]); // an empty Swift buffer can have a nil baseAddress
    }
    if ptr.is_null() || len > isize::MAX as usize {
        return None;
    }
    Some(unsafe { std::slice::from_raw_parts(ptr, len) })
}

fn main() {
    let mut bytes = Vec::with_capacity(64);
    bytes.extend_from_slice(b"ok");
    let out = RsBuffer::from_vec(bytes);
    assert_eq!(out.capacity, 64); // release needs the real capacity, not len
    assert_eq!(unsafe { borrowed(out.ptr, out.len) }, Some(&b"ok"[..]));
    rs_buffer_release(out);
    rs_buffer_release(RsBuffer::from_vec(Vec::with_capacity(16)));
    let changed_by_c = RsBuffer { ptr: ptr::NonNull::dangling().as_ptr(), len: 2, capacity: 1 };
    rs_buffer_release(changed_by_c); // returns early; never reaches `from_raw_parts`
    assert_eq!(unsafe { borrowed(ptr::null(), 0) }, Some(&[][..]));
    assert_eq!(unsafe { borrowed(ptr::null(), 4) }, None);
}
```

What each part shows:

- `from_vec` returns the canonical empty value for an empty `Vec`. A
  `Vec::new()` has a dangling non-null pointer, and Swift zero-initializes
  `rs_buffer_t()`, so only the null form means "nothing to free".
- The first assertion shows that capacity can differ from length. The release
  function rebuilds the `Vec` with the real capacity. Do not rely on
  `shrink_to_fit` to make them equal: it does not guarantee
  `capacity == len`.
- `rs_buffer_release` returns early for the null form and for
  `len > capacity`, which `Vec::from_raw_parts` forbids. It never rebuilds a
  `Vec` from either.
- `borrowed` maps every zero-length input to `&[]`, including a null pointer,
  and rejects a null pointer with a non-zero length. It never passes null to
  `slice::from_raw_parts`, which requires a non-null pointer even for length
  zero.
- The `# Safety` section states what code cannot check: a non-null pointer
  points to one live allocation with `len` initialized bytes. Keep that
  precondition on every export that takes a borrowed Swift pointer.
- `Vec::into_raw_parts` is stable since Rust 1.93. On an older MSRV, use
  `let mut v = ManuallyDrop::new(vec);` and read `v.as_mut_ptr()`, `v.len()`,
  and `v.capacity()`.

Add the operation's own size limit to `borrowed` before you build the slice.
Wrap each export in the panic guard from the `rust-panic-safety` skill when it
is installed.
