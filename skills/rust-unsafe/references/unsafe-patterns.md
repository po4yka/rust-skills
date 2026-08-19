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

## `unsafe trait` and `unsafe fn` are separate axes

`unsafe` on a trait and `unsafe` on a method constrain different people. Neither one implies the
other.

| Declaration | Who carries the obligation | Compiler rule |
| --- | --- | --- |
| `unsafe trait T` | The implementor | A plain `impl T for X` is `error[E0200]: the trait T requires an unsafe impl declaration` |
| A plain `trait T` | Nobody beyond the type system | `unsafe impl T for X` is `error[E0199]: implementing the trait T is not unsafe` |
| `unsafe fn m()` in a trait | The caller | The call site needs an `unsafe { ... }` block |
| A safe `fn m()` in an `unsafe trait` | Nobody at the call site | The call needs no `unsafe` block |

Do not write the rule as "an `unsafe trait` makes its methods unsafe to call". A safe method of
an `unsafe trait` is called with no block. The mirror trap costs as much: `unsafe impl` on a
safe trait is E0199, so you cannot use the keyword to signal that an impl is delicate.

Put the `# Safety` section where the obligation sits. An invariant that the implementor must
uphold belongs on the trait. An invariant that the caller must uphold belongs on the method. A
trait can carry both.

```rust
/// # Safety
/// The implementor must keep `len()` equal to the initialized prefix.
unsafe trait RawView {
    fn len(&self) -> usize; // Safe to call. No unsafe block at the call site.
    /// # Safety
    /// `i` must be less than `self.len()`.
    unsafe fn at(&self, i: usize) -> u8;
}

struct Buf(Vec<u8>);

// SAFETY: `Buf` owns a fully initialized `Vec`, so `len()` is exact.
unsafe impl RawView for Buf {
    fn len(&self) -> usize { self.0.len() }
    unsafe fn at(&self, i: usize) -> u8 {
        // SAFETY: the caller guarantees `i < self.len()`.
        unsafe { *self.0.get_unchecked(i) }
    }
}

fn main() {
    let buf = Buf(vec![1, 2, 3]);
    let n = buf.len();               // No unsafe block: the method is safe.
    let byte = unsafe { buf.at(1) }; // SAFETY: 1 < 3.
    assert_eq!((n, byte), (3, 2));
}
```

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

## A JNI entry point with a tri-state guard

`jni` 0.22 gives a tri-state guard. `EnvUnowned::with_env` plus `into_outcome` separates a caught
panic from a normal error, so you do not lose that distinction at the exit:

```rust
use jni::{EnvUnowned, Outcome};

pub(crate) fn create_entry(mut env: EnvUnowned<'_>, config: JString<'_>) -> jlong {
    match env
        .with_env(move |env| -> jni::errors::Result<jlong> {
            Ok(create_session(env, config)?)
        })
        .into_outcome()
    {
        Outcome::Ok(handle) => handle,
        Outcome::Err(_err) => 0,       // throw a Java exception, return the default
        Outcome::Panic(_payload) => 0, // already caught: log it, throw, return the default
    }
}
```

On `jni` 0.21 and earlier, which has no `EnvUnowned`, wrap the body in
`catch_unwind(AssertUnwindSafe(|| { ... }))` and throw a Java exception in the `Err` arm. Raw
`catch_unwind` is also the only option in `JNI_OnLoad` and `JNI_OnUnload`, where `EnvUnowned` is
not available.

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

## Syscall, ioctl, union, and descriptor wrappers

`mem::zeroed()` is sound here because a plain `repr(C)` struct has no Rust-level invariant. Cast
with `.cast()`, not `as *mut _`: the method preserves pointer provenance, which matters to
Miri's Tree Borrows model.

```rust
// SAFETY: `ifreq` is a plain C struct with no Rust-level invariants, and
// all-zero bytes is a valid uninitialized value that is overwritten below.
let mut ifr: libc::ifreq = unsafe { std::mem::zeroed() };
ifr.ifr_name = make_ifr_name();
```

```rust
/// # Safety
/// `fd` must be a live socket descriptor. `T` must match the layout the kernel
/// writes for the given `level` and `name` pair.
unsafe fn getsockopt_raw<T>(
    fd: libc::c_int,
    level: libc::c_int,
    name: libc::c_int,
) -> io::Result<(T, libc::socklen_t)> {
    // SAFETY: `T` is a plain C struct chosen by the caller to match the option.
    let mut val: T = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<T>() as libc::socklen_t;
    // SAFETY: `fd` is live per the caller contract; `val` and `len` are valid
    // for writes of the sizes passed.
    let rc = unsafe { libc::getsockopt(fd, level, name, (&mut val as *mut T).cast(), &mut len) };
    if rc == 0 { Ok((val, len)) } else { Err(io::Error::last_os_error()) }
}
```

An `ioctl` SAFETY comment states three facts: the descriptor is valid, the struct fields the
kernel reads are populated, and which request number is issued and what it does.

```rust
// SAFETY: `sock` is a valid AF_INET/SOCK_DGRAM descriptor; `ifr` has `ifr_name`
// and the MTU field set; SIOCSIFMTU sets the interface MTU.
let rc = unsafe { libc::ioctl(sock.as_raw_fd(), libc::SIOCSIFMTU, &ifr as *const _) };
if rc < 0 {
    return Err(Error::Ioctl("SIOCSIFMTU", io::Error::last_os_error()));
}
```

A C union field read is unsafe because the compiler cannot know which variant was written last.
Zero the struct first, then write before you read:

```rust
// SAFETY: `ifr` was zeroed above, and `ifru_flags` is written before any read.
unsafe {
    ifr.ifr_ifru.ifru_flags = IFF_TUN | IFF_NO_PI;
}
```

A descriptor that a foreign caller passes in is borrowed, not owned. Duplicate it before you
take ownership, or the foreign runtime closes it under you:

```rust
// SAFETY: `raw` is a live descriptor for the duration of this call.
// `BorrowedFd` does not take ownership; `dup` returns an independent descriptor.
let owned = unsafe { nix::unistd::dup(BorrowedFd::borrow_raw(raw))? };
```

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

`ptr::read` on a byte slice from I/O needs `ptr::read_unaligned` instead, as the next section
shows. The rules that govern it are in [SKILL.md](../SKILL.md).

## Unaligned reads from untrusted bytes

Four forms of the same parse, worst first:

```rust
// BAD: assumes an alignment the input slice does not promise.
let header: Header = unsafe { std::ptr::read(buf.as_ptr() as *const Header) };

// CORRECT: an explicit unaligned read.
let header: Header = unsafe { std::ptr::read_unaligned(buf.as_ptr() as *const Header) };

// BETTER: no unsafe at all.
use zerocopy::FromBytes;
let header = Header::read_from_prefix(buf).ok_or(Error::Truncated)?;

// Or, for a streaming parser, endianness-explicit and safe:
use bytes::Buf;
let mut cur = std::io::Cursor::new(buf);
let magic = cur.get_u32_le();
```

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

`NonNull` documents the non-null invariant in the type instead of in a comment:

```rust
use std::ptr::NonNull;

let boxed = Box::new(Buffer::new());
let nn: NonNull<Buffer> = NonNull::new(Box::into_raw(boxed)).expect("Box::into_raw is non-null");
// SAFETY: `nn` came from a live Box and has not been freed.
let borrowed = unsafe { nn.as_ref() };
// SAFETY: `nn` still points at the allocation from Box::into_raw, consumed once.
let owned_again = unsafe { Box::from_raw(nn.as_ptr()) };
```

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

## A `Drop` impl that cannot abort the process

A panic inside `drop()` during an unwind aborts the process. Move every fallible cleanup into an
explicit `close()`, and leave `drop()` as a best-effort fallback that only logs.

```rust
// DANGEROUS: aborts the process when dropped during an unwind.
impl Drop for BufferedWriter {
    fn drop(&mut self) {
        self.flush().unwrap();
    }
}
```

```rust
// CORRECT: log and discard in drop; expose an explicit fallible close.
impl Drop for BufferedWriter {
    fn drop(&mut self) {
        if let Err(err) = self.flush() {
            tracing::error!(error = %err, "flush on drop failed");
        }
    }
}

impl BufferedWriter {
    pub fn close(mut self) -> Result<(), Error> {
        self.flush()
    }
}
```

## Asserting an auto trait on each field

A manual `unsafe impl Send` on a wrapper is unconditional, so it stays accepted after the fields
change. Assert the fields, not the wrapper. The assertion needs no dependency:

```rust
pub struct Inner {
    pub id: u32,
}

pub struct MyWrapper {
    pub inner: Inner,
}
unsafe impl Send for MyWrapper {}

const _: () = {
    fn assert_send<T: Send>() {}
    let _ = assert_send::<Inner>;
};
```

An `Inner` that gains an `Rc<_>` field fails this with E0277.

## Reference fabrication with `RefCell::as_ptr`

`RefCell::as_ptr` returns the raw pointer and does not touch the dynamic borrow counter. An
`unsafe` deref that hands a caller a `&'a T` or a `&'a mut T` therefore produces a reference the
`RefCell` does not track. A later `borrow_mut()` succeeds instead of panicking, and safe caller
code mutates the data behind a live shared reference.

```rust
use std::cell::RefCell;
use std::rc::Rc;

fn main() {
    // Unsound: `as_ptr` skips the borrow flag, so `leaked` is not exclusive.
    let cell = Rc::new(RefCell::new(String::from("moo")));
    let leaked: &String = unsafe { &*cell.as_ptr() };
    cell.borrow_mut().push_str(" MOO"); // Safe code. No `already borrowed` panic.
    println!("{leaked}");               // Prints `moo MOO`.
}
```

Measured on rustc 1.97.0, edition 2024: the program compiles, prints `moo MOO`, and exits 0. A
`&String` observed a mutation and nothing panicked.

The pattern appears when a borrowing iterator is written over `Rc<RefCell<T>>`. The safe form
does not compile. Returning `&*cell.borrow()` from `next` is `error[E0515]: cannot return value
referencing temporary value`, because the `Ref` guard dies at the end of `next`. `as_ptr` plus
`unsafe` removes the error and leaves the API unsound.

Change the API shape. In order of preference:

1. Yield the guard: `type Item = Ref<'a, T>`. The caller holds the borrow, so the counter works.
2. Yield an owned handle, `Rc<RefCell<T>>`, and let the caller call `borrow()` itself.
3. Store the elements in a `Vec` or an arena and iterate a real slice. No interior mutability
   and no unsafe.

```rust
use std::cell::{Ref, RefCell};
use std::rc::Rc;

pub struct List<T> { items: Vec<Rc<RefCell<T>>> }
pub struct Iter<'a, T> { inner: std::slice::Iter<'a, Rc<RefCell<T>>> }

impl<T> List<T> {
    pub fn iter(&self) -> Iter<'_, T> { Iter { inner: self.items.iter() } }
}

impl<'a, T> Iterator for Iter<'a, T> {
    type Item = Ref<'a, T>;
    fn next(&mut self) -> Option<Ref<'a, T>> { Some(self.inner.next()?.borrow()) }
}
```

Both Miri aliasing models reject the unsound form, but only when the program interleaves the
fabricated reference with a mutation. A test suite that never holds a yielded reference across a
`borrow_mut()` passes Miri clean. Treat the pattern as UB on inspection. Miri is a confirmation
here, never the gate. See the `rust-sanitizers-miri` skill for the two messages.

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
