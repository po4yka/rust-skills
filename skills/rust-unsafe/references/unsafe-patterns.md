# Unsafe patterns reference

Worked patterns for the rules in [SKILL.md](../SKILL.md). Copy the shape, not the type names.

## Safety comment format

Every `unsafe { ... }` block needs a `// SAFETY:` comment above it. Every `unsafe fn` needs a
`/// # Safety` rustdoc section that lists what the caller must guarantee. The two are different
documents: the rustdoc states the contract, the inline comment states why this call site meets
it.

```rust
/// # Safety
/// `ptr` must be non-null, aligned to `align_of::<T>()`, and point at `len`
/// initialized values of type `T`. The memory must stay valid and must not be
/// mutated for the lifetime `'a` of the returned slice.
unsafe fn raw_slice<'a, T>(ptr: *const T, len: usize) -> &'a [T] {
    // SAFETY: the caller guarantees `ptr` is non-null, aligned, and valid for
    // `len` initialized elements.
    unsafe { std::slice::from_raw_parts(ptr, len) }
}
```

The inner `unsafe` block is required even inside an `unsafe fn`, because
`#![deny(unsafe_op_in_unsafe_fn)]` is part of the lint floor. Without it, an `unsafe fn` becomes
a region where every operation is implicitly permitted and no operation is individually
justified.

## A macro for repeated FFI exports

When a crate exports many entry points with the same guard, stamp them out with a macro. The
macro keeps the guard uniform, and it stops a hand-written export from silently omitting it.

```rust
macro_rules! export_jni {
    ($name:ident, ($($arg:ident: $arg_ty:ty),* $(,)?), $ret:ty, $entry:ident) => {
        #[unsafe(no_mangle)]
        pub extern "system" fn $name(
            env: EnvUnowned<'_>,
            _this: JObject<'_>,
            $($arg: $arg_ty),*
        ) -> $ret {
            $entry(env, $($arg),*)
        }
    };
}
```

The generated function does one thing: delegate. All logic, error mapping, and the
`with_env`/`into_outcome` guard live in the plain `_entry` function, which is ordinary Rust that
you can unit-test without a JVM.

## A hand-rolled `extern "C"` entry point

Use this only when a generated boundary is not an option. Every pointer argument gets its own
SAFETY comment, because each carries a different invariant.

```rust
/// # Safety
/// `pixel_ptr` must be non-null, aligned for 4 bytes, writable, exclusively owned
/// by the caller for the duration of this call, and valid for `width * height * 4`
/// bytes. `spec` must be a valid null-terminated UTF-8 string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn render_into_buffer(
    pixel_ptr: *mut u8,
    width: u32,
    height: u32,
    spec: *const std::os::raw::c_char,
) -> i32 {
    let result = std::panic::catch_unwind(|| {
        // SAFETY: the caller guarantees `pixel_ptr` is valid for
        // `width * height * 4` bytes, writable, and not aliased.
        let pixels = unsafe {
            std::slice::from_raw_parts_mut(pixel_ptr, (width * height * 4) as usize)
        };
        // SAFETY: the caller guarantees `spec` is a valid null-terminated C string.
        let spec = unsafe { std::ffi::CStr::from_ptr(spec) }
            .to_str()
            .map_err(|_| Error::InvalidRequest)?;
        render_pixels(pixels, width, height, spec)
    });
    match result {
        Ok(Ok(())) => 0,
        Ok(Err(_)) => -1,
        Err(_) => -2, // panic caught; never unwind into the caller
    }
}
```

Return a plain integer status. Do not return a `Result`, a `String`, or any type whose layout
the foreign caller cannot rely on.

## Wrapping a caller-owned buffer in a library object

Some C++ libraries can render into a buffer the caller allocated. The wrapper object must not
outlive the buffer, and the type system cannot express that across the boundary, so the rule
goes in the contract and the object stays private.

```rust
/// # Safety
/// `pixels` must stay valid and exclusively writable for the whole lifetime of
/// the returned surface. The surface must be dropped before `pixels` is released
/// or read from any other context.
unsafe fn surface_from_buffer(
    pixels: &mut [u8],
    width: i32,
    height: i32,
) -> Option<Surface> {
    let info = ImageInfo::new(
        (width, height),
        ColorType::RGBA8888,
        AlphaType::Premul,
        ColorSpace::new_srgb(),
    );
    let row_bytes = (width as usize) * 4;
    // SAFETY: the caller guarantees `pixels` is valid for `width * height * 4`
    // bytes and outlives the returned surface.
    unsafe { surfaces::wrap_pixels(&info, pixels, row_bytes, None) }
}
```

When the library hands back a raw pointer to its own pixels, copy out immediately. Do not store
the pointer, and do not let it escape the scope where the owning object is known to be alive.

```rust
fn read_pixels(surface: &mut Surface, height: i32) -> Vec<u8> {
    let Some(pixmap) = surface.peek_pixels() else {
        return Vec::new();
    };
    let row_bytes = pixmap.row_bytes();
    let data = pixmap.addr() as *const u8;
    // SAFETY: `peek_pixels` returned Some, so `addr()` is non-null and aligned,
    // and it is valid for `height * row_bytes` bytes while `surface` is alive
    // and no drawing operation is in progress. The copy happens before the
    // borrow of `surface` ends.
    let slice = unsafe { std::slice::from_raw_parts(data, (height as usize) * row_bytes) };
    slice.to_vec()
}
```

Prefer the safe read-back API when the library offers one. A copy into an owned `Vec` costs one
memcpy and removes the entire class of lifetime error above.

## Reads and writes that create no reference

These three functions move values through a raw pointer without ever forming a `&` or `&mut`,
so they do not interact with the aliasing model the way a reference does. That is exactly why
they are the right tool for partially initialized or externally owned memory.

```rust
// ptr::read copies `T` out without binding a lifetime.
// SAFETY: `ptr` is valid, aligned, and points at an initialized value.
let val: u32 = unsafe { std::ptr::read(ptr) };

// ptr::write stores `T` without dropping whatever was there before.
// SAFETY: `dst` is valid for writes and aligned; the previous value, if any,
// was already moved out or is not initialized.
unsafe { std::ptr::write(dst, new_val) };

// ptr::copy_nonoverlapping is memcpy. Overlap is UB; use ptr::copy for memmove.
// SAFETY: `src` and `dst` are valid for `count` elements and do not overlap.
unsafe { std::ptr::copy_nonoverlapping(src, dst, count) };
```

`ptr::read` on a byte slice from I/O needs `ptr::read_unaligned` instead. See the untrusted
byte-buffer rules in [SKILL.md](../SKILL.md).

## Pointer arithmetic

```rust
// wrapping_add: always sound to compute. Do not dereference an out-of-bounds result.
let p = ptr.wrapping_add(2);

// add: UB when the result leaves the allocation, even without a dereference.
// SAFETY: `ptr + 2` stays inside the same allocation.
let third = unsafe { *ptr.add(2) };

// offset_from: both pointers must belong to the same allocation.
// SAFETY: `end` and `start` point into the same contiguous slice.
let count = unsafe { end.offset_from(start) };
```

`add` is UB on computation, not on dereference. This surprises people: computing a pointer one
past the end of an allocation is allowed, computing two past is not.

## Transmute safety table

| From | To | Sound? | Use instead |
| --- | --- | --- | --- |
| `u32` | `f32` | Yes, same size | `f32::from_bits(u)` |
| `[u8; 4]` | `u32` | Yes | `u32::from_ne_bytes(arr)` |
| `&T` | `*const T` | Yes | `ptr as *const T` |
| `*mut T` | `*const T` | Yes | `ptr as *const T` |
| `Box<T>` | `*mut T` | Yes | `Box::into_raw(b)` |
| `&'a T` | `&'b T`, longer lifetime | **No** | Restructure the lifetimes |
| `u8` | `bool` | **No**, unless 0 or 1 | Match on the value |
| `u8` | `MyEnum` | **No**, unless a valid tag | `MyEnum::try_from(u)` |
| `Vec<T>` | `Vec<U>` | **No** | Convert element by element |
| `&[u8]` | `&[Header]` | **No** | `zerocopy::FromBytes` |

Every "Yes" row has a named function. Use the function: it cannot be applied to the wrong pair
of types, and it survives a refactor that changes one of them.

## Aliasing models: Stacked Borrows and Tree Borrows

Miri checks unsafe code against a formal aliasing model. Tree Borrows, published at PLDI 2025,
is the current recommended model. It accepts more valid patterns than the older Stacked Borrows,
so code the older model rejected may pass now.

```bash
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked
```

The classic violation both models reject:

```rust
let mut x = 5u32;
let raw = &mut x as *mut u32;
let shared = &x;         // a shared borrow of `x`
let _ = unsafe { *raw }; // VIOLATION: the tag `raw` carries was invalidated
```

Under Stacked Borrows the rules are:

1. Each borrow pushes a new tag onto the borrow stack for that location.
2. A `&mut T` access pops every borrow above it, which invalidates them.
3. A `&T` access stays valid while the shared reference is on the stack.
4. A raw-pointer access requires its tag to still be on the stack.

Tree Borrows replaces the stack with a tree and tracks each pointer's permission separately,
which is what makes it more permissive. The practical guidance is unchanged: do not derive a
raw pointer, then use a reference to the same place, then use the raw pointer again.

## Miri invocations

```bash
# Baseline.
cargo +nightly miri test --locked

# The recommended model for new unsafe code.
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test --locked

# Stricter provenance checking; catches integer-to-pointer casts.
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test --locked

# One test only.
cargo +nightly miri test --locked test_my_unsafe_fn
```

Miri cannot execute a foreign function. Skip a test that crosses a real FFI boundary, and cover
that path with `cargo-careful` instead:

```rust
#[test]
#[cfg_attr(miri, ignore)]
fn ffi_roundtrip() { /* ... */ }
```

See the `rust-sanitizers-miri` skill for the stubbing strategy that lets more of a crate run
under Miri, and the `rust-test-tools` skill for `cargo-careful`.

## Clippy invocations for unsafe

```bash
cargo clippy --locked --all-targets -- \
  -W clippy::undocumented_unsafe_blocks \
  -W clippy::multiple_unsafe_ops_per_block \
  -W clippy::transmute_undefined_repr \
  -W clippy::ptr_as_ptr
```

Use the command line only to try a lint out. Once you keep a lint, move it into
`[workspace.lints]` so that CI and every developer get the same result. See the `rust-lints`
skill.
