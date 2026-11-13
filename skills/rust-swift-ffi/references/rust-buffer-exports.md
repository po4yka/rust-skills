# Rust buffer exports for Swift

Contents:

- Scoped input and owned output
- Safety and verification

The Rust side of the `rs_buffer_t` contract from `SKILL.md`, with borrowed
Swift input. CI compiles and runs this block on the pinned toolchain. It
checks owned results and buffer release. It does not prove that a foreign
pointer satisfies the safety contract.

## Scoped input and owned output

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
/// For a non-empty accepted input, `ptr` points to `len` initialized bytes
/// in one allocation. They stay valid and unchanged until this call returns,
/// including while `use_bytes` runs. The address range must not wrap.
unsafe fn with_borrowed<R>(
    ptr: *const u8,
    len: usize,
    use_bytes: impl for<'a> FnOnce(&'a [u8]) -> R,
) -> Option<R> {
    if len == 0 {
        return Some(use_bytes(&[])); // an empty Swift buffer can have a nil baseAddress
    }
    if ptr.is_null() || len > isize::MAX as usize {
        return None;
    }
    // SAFETY: the caller keeps this allocation valid and unchanged throughout
    // the callback. Its higher-ranked bound prevents a slice reference escaping.
    Some(use_bytes(unsafe { std::slice::from_raw_parts(ptr, len) }))
}

fn main() {
    let mut bytes = Vec::with_capacity(64);
    bytes.extend_from_slice(b"ok");
    let out = RsBuffer::from_vec(bytes);
    assert_eq!(out.capacity, 64); // release needs the real capacity, not len
    // SAFETY: `out` keeps the allocation alive, and the callback only reads it.
    let owned = unsafe { with_borrowed(out.ptr, out.len, |bytes| bytes.to_vec()) };
    rs_buffer_release(out);
    assert_eq!(owned, Some(b"ok".to_vec())); // the owned result survives release
    rs_buffer_release(RsBuffer::from_vec(Vec::with_capacity(16)));
    let changed_by_c = RsBuffer { ptr: ptr::NonNull::dangling().as_ptr(), len: 2, capacity: 1 };
    rs_buffer_release(changed_by_c); // returns early; never reaches `from_raw_parts`
    // SAFETY: these cases return an empty slice or reject the pointer before a read.
    assert_eq!(unsafe { with_borrowed(ptr::null(), 0, |bytes| bytes.len()) }, Some(0));
    assert_eq!(unsafe { with_borrowed(ptr::null(), 4, |bytes| bytes.len()) }, None);
}
```

## Safety and verification

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
- `with_borrowed` maps every zero-length input to `&[]`, including a null pointer,
  and rejects a null pointer with a non-zero length. It never passes null to
  `slice::from_raw_parts`, which requires a non-null pointer even for length
  zero.
- The callback receives a slice only while the foreign memory stays valid.
  `for<'a>` prevents its slice reference from escaping in `R`. Return owned
  data when the result must survive the callback. Do not retain a raw pointer
  for later use or call foreign code that mutates or frees the input.
- The `# Safety` section requires one live allocation for the whole callback.
  Keep that contract on every export that takes a borrowed Swift pointer.
  A helper that returns `&'a [u8]` instead must require validity and no mutation
  for the whole returned `'a`, not just until the helper returns.
- `Vec::into_raw_parts` is stable since Rust 1.93. On an older MSRV, use
  `let mut v = ManuallyDrop::new(vec);` and read `v.as_mut_ptr()`, `v.len()`,
  and `v.capacity()`.

Add the operation's own size limit to `with_borrowed` before you build the slice.
Wrap each export body in `catch_unwind` and return a reserved panic status; the
`rust-panic-safety` skill, when it is installed, owns that guard.
