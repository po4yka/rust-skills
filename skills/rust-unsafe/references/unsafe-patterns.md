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

## An output lifetime that appears in no input is unbounded

`raw_slice` above returns `&'a [T]`, and `'a` appears in no argument. The caller picks `'a`, and
the caller may pick `'static`. Nothing warns. Lifetime inference solves for the output from the
constraints in the signature, and a raw pointer carries none, so there is no upper bound.
`<*const T>::as_ref`, which returns `Option<&'a T>`, has the same shape and the same hazard.

```rust
/// # Safety
/// No caller can discharge this contract. `'a` is unbounded: inference picks it,
/// up to `'static`, and the signature gives the caller nowhere to attach it.
pub unsafe fn deref_unbounded<'a, T>(p: *const T) -> &'a T {
    // SAFETY: stated above, and the statement is not satisfiable.
    unsafe { &*p }
}
```

That compiles clean, and the returned reference outlives its owner. Tie the output lifetime to an
input the caller must already hold:

```rust
/// # Safety
/// `p` must point into `_owner`, and must stay valid for all of `'a`.
pub unsafe fn deref_bounded<'a, T, O>(p: *const T, _owner: &'a O) -> &'a T {
    // SAFETY: the caller guarantees `p` points into `_owner`, which lives for `'a`.
    unsafe { &*p }
}
```

An escape is now `error[E0597]: ... does not live long enough`, reported at the call site, with
`borrowed value does not live long enough` on the owner argument.

Marking the function `unsafe` does not repair the shape. `unsafe` moves blame to the caller, and
the caller has no lever: the signature gives it no place to state which borrow the result belongs
to. The obligation sits with the implementor. When the value is reachable from something the
caller already names, take `&'a self` or a `&'a Owner` parameter and make the function safe. When
a trait must produce a borrowed value, use a generic associated type, which puts the lifetime
back into the signature:

```rust
pub struct Store;

pub trait Extract {
    type Out<'w>;
    fn from_store<'w>(store: &'w Store) -> Self::Out<'w>;
}
```

Keep an unbounded output lifetime only where the SAFETY comment names the owner, the function is
private, and the owning type holds the data, as in the `mmap_as_slice` case in
[ffi-layout-rules.md](ffi-layout-rules.md).

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
`with_env`/`resolve` guard live in the plain `_entry` function, which is ordinary Rust that
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

## A JNI entry point with a policy exit

`EnvUnowned::with_env` catches the panic and returns a `#[must_use]` `EnvOutcome`. `resolve`
rebuilds an `Env` and applies an `ErrorPolicy` to the error and to the caught panic, so it is
the only place the entry point can throw:

```rust
use jni::errors::ThrowRuntimeExAndDefault;
use jni::objects::JString;
use jni::sys::jlong;
use jni::{Env, EnvUnowned};

pub(crate) fn create_entry<'local>(
    mut env: EnvUnowned<'local>,
    config: JString<'local>,
) -> jlong {
    env.with_env(|env| -> jni::errors::Result<jlong> { create_session(env, config) })
        .resolve::<ThrowRuntimeExAndDefault>()
}

fn create_session(_env: &mut Env<'_>, _config: JString<'_>) -> jni::errors::Result<jlong> {
    todo!()
}
```

`into_outcome` gives the raw `Outcome::{Ok, Err, Panic}` instead of a resolved value. Take it
only when the exit does not throw: `EnvUnowned` has no JNI methods, so nothing after that call
can raise an exception. Write your own `ErrorPolicy` when the error and the panic need
different messages.

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

Use `mem::zeroed()` only when the exact type documents that all-zero bytes are a
valid value. `repr(C)` controls layout. It does not remove Rust value invariants.

```rust
// SAFETY: `ifreq` is a plain C struct with no Rust-level invariants, and
// all-zero bytes is a valid uninitialized value that is overwritten below.
let mut ifr: libc::ifreq = unsafe { std::mem::zeroed() };
ifr.ifr_name = make_ifr_name();
```

```rust
use std::io;

/// # Safety
/// `fd` must be a live socket descriptor. `T` must match the layout the kernel
/// writes for the given `level` and `name` pair. On success, the option must
/// initialize exactly `size_of::<T>()` bytes with a valid value of `T`.
unsafe fn getsockopt_raw<T>(
    fd: libc::c_int,
    level: libc::c_int,
    name: libc::c_int,
) -> io::Result<(T, libc::socklen_t)> {
    let mut val = std::mem::MaybeUninit::<T>::uninit();
    let mut len = std::mem::size_of::<T>() as libc::socklen_t;
    // SAFETY: `fd` is live per the caller contract; `val` and `len` are valid
    // for writes of the sizes passed.
    let rc = unsafe { libc::getsockopt(fd, level, name, val.as_mut_ptr().cast(), &mut len) };
    if rc != 0 {
        return Err(io::Error::last_os_error());
    }
    if len as usize != std::mem::size_of::<T>() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "short socket option"));
    }
    // SAFETY: the caller contract requires a fully initialized, valid `T`.
    Ok((unsafe { val.assume_init() }, len))
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

Four forms of the same parse, worst first. Each one is a whole example, because only the first
is wrong and a reader must be able to copy the others without carrying the mistake along.

The bad form compiles, runs, and returns the right bytes on an x86-64 development host. Nothing
in the toolchain reports it except Miri:

```rust
#[repr(C)]
#[derive(Clone, Copy)]
struct Header { magic: u32, len: u32 }

fn parse(buf: &[u8]) -> Header {
    // BAD: `read` requires an aligned pointer, and a byte slice promises nothing.
    unsafe { std::ptr::read(buf.as_ptr() as *const Header) }
}
```

The correct form states that the read tolerates misalignment, and checks the length first:

```rust
#[repr(C)]
#[derive(Clone, Copy)]
struct Header { magic: u32, len: u32 }

fn parse(buf: &[u8]) -> Option<Header> {
    if buf.len() < std::mem::size_of::<Header>() {
        return None;
    }
    // SAFETY: the length is checked, and `read_unaligned` needs no alignment.
    Some(unsafe { std::ptr::read_unaligned(buf.as_ptr() as *const Header) })
}
```

The better form removes the `unsafe` block. `zerocopy` proves the layout at compile time and
returns the remaining bytes with the value:

```rust
use zerocopy::{FromBytes, Immutable, KnownLayout};

#[derive(FromBytes, KnownLayout, Immutable, Clone, Copy)]
#[repr(C)]
struct Header { magic: u32, len: u32 }

fn parse(buf: &[u8]) -> Option<Header> {
    let (header, _rest) = Header::read_from_prefix(buf).ok()?;
    Some(header)
}
```

A streaming parser reads field by field with an explicit endianness, and never casts a pointer:

```rust
use bytes::Buf;

fn magic(buf: &[u8]) -> Option<u32> {
    let mut cursor = std::io::Cursor::new(buf);
    if cursor.remaining() < 4 {
        return None;
    }
    Some(cursor.get_u32_le())
}
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

`add`, `offset`, and `wrapping_add` return a new pointer and never modify the receiver, so a
cursor translated from C's `p++` must be assigned back: `self.ptr = unsafe { self.ptr.add(1) };`.
Dropping the assignment compiles, and the cursor never advances. The only signal is a warning:

```text
warning: unused return value of `std::ptr::mut_ptr::<impl *mut T>::add` that must be used
  = note: returns a new pointer rather than modifying its argument
```

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

## Broken UTF-8 fails nowhere near where you built it

`str::from_utf8_unchecked` is guarded for one case only: a byte-string literal. The
deny-by-default lint `invalid_from_utf8_unchecked` catches that case.

```text
error: calls to `std::str::from_utf8_unchecked` with an invalid literal are undefined behavior
  |                        the literal was valid UTF-8 up to the 1 bytes
  = note: `#[deny(invalid_from_utf8_unchecked)]` on by default
```

For bytes produced at run time nothing checks anything: not the lint, not
`-C debug-assertions=on`, and not Miri. UTF-8 validity is a library invariant, not a language
validity invariant, so Miri's abstract machine sees nothing wrong at construction. A clean Miri
run over the code that builds the `&str` proves nothing about that `&str`.

The undefined behavior surfaces in the consumer, and only in one kind of consumer:

```rust,ignore
// `v` ends with a lone 0xF0, so `s` is not valid UTF-8.
let s: &str = unsafe { std::str::from_utf8_unchecked(&v) };

let _ = s.replace("a", "b");   // fine: a byte-wise search, it never decodes
let _ = s.chars().count();     // fine: specialized to count non-continuation bytes
for _c in s.chars() {}         // UB: this is the only one that decodes
```

`Chars::count` delegates to `core`'s `count_chars`, which counts non-continuation bytes and never
builds a `char`. Only `Chars::next` reaches the decoder:

```text
error: Undefined Behavior: entering unreachable code
  --> library/core/src/str/validations.rs:48:23
   |
48 |     let y = unsafe { *bytes.next().unwrap_unchecked() };
```

Write the reproducing test as a decode loop. A test that ends in `.chars().count()` passes and
reports that the buffer is fine.

### `black_box` is not a soundness argument

Never justify an `unsafe` block with "`std::hint::black_box` stops the compiler from optimizing
the check away". The std documentation says `black_box` is provided on a best-effort basis and
"must not be relied upon to control critical program behavior". An argument that depends on an
optimizer failing to notice something is not an argument.

The shape appears when code validates bytes and then reuses the buffer:

```rust,ignore
// Do not do this. The unsafe block buys nothing over the safe call.
let s = match String::from_utf8_lossy(std::hint::black_box(&v)) {
    Cow::Owned(s) => s,
    Cow::Borrowed(_) => unsafe { String::from_utf8_unchecked(v) },
};
```

```rust,ignore
// Do this. One validation pass, no unsafe, and the bad input is reported.
let s = String::from_utf8(v)?;
```

`String::from_utf8` runs the same single scan, reuses the same buffer with no copy, and its
`FromUtf8Error` carries `utf8_error().valid_up_to()` so you can report the offending offset.

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

The auto-trait proofs, the two reference fabrications, the aliasing models, and the Miri and
clippy invocations are in [miri-and-aliasing.md](miri-and-aliasing.md).
