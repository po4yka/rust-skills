# Aliasing, auto traits, and Miri

The proof side of unsafe: what makes an abstraction unsound after it compiles, and the checks
that find it. [unsafe-patterns.md](unsafe-patterns.md) holds the patterns you write.
[SKILL.md](../SKILL.md) holds the rules.

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

### You cannot implement `Send` for a reference type

`Send` and `Sync` carry a default impl, so rustc accepts a manual impl only for a struct, enum,
or union that you own:

```rust,compile_fail
struct MyType(i32);
unsafe impl Send for &MyType {}
```

```text
error[E0321]: cross-crate traits with a default impl, like `Send`, can only be implemented
              for a struct/enum type, not `&MyType`
```

There is one lever, and it is `MyType: Sync`. `&T: Send` holds exactly when `T: Sync`. No
`unsafe impl` written on the reference type substitutes for it.

### A derive is a `&self` API

"Callers cannot obtain `&T` from `&Wrapper<T>`, so `Wrapper<T>` is always `Sync`" is a false
safety argument, and it survives review because the leak is generated code. `#[derive(Debug)]`,
`#[derive(Clone)]`, `#[derive(PartialEq)]`, `#[derive(Hash)]`, and a derived `Serialize` each
produce a `&self` method that hands `&T` to `T`'s own impl. `Wrapper<T>: Sync` means
`&Wrapper<T>: Send`, so that `&T` reaches a second thread and `T`'s impl mutates its interior
state there with no synchronization.

```rust
#[derive(Debug)]                              // <- this derive is the leak
pub struct NoSharedAccess<T>(T);
impl<T> NoSharedAccess<T> {
    pub fn get_mut(&mut self) -> &mut T { &mut self.0 }   // only `&mut`, looks safe
}
unsafe impl<T> Sync for NoSharedAccess<T> {}  // UNSOUND
```

Give the wrapper a `T` whose `Debug` impl clones an `Rc`, and the non-atomic refcount races. Two
scoped threads and 300 iterations under Miri are enough:

```text
error: Undefined Behavior: Data race detected between (1) non-atomic read on thread `unnamed-1`
       and (2) retag write of type `usize` on thread `unnamed-2` at alloc271
  --> library/core/src/cell.rs:513:31
```

An unconditional `unsafe impl<T> Sync for Wrapper<T> {}` is sound only for a type with no `&self`
API at all, derives included. Otherwise bound it, `unsafe impl<T: Sync> Sync for Wrapper<T> {}`,
or delete the manual impl and let the auto impl decide.

Do not decide this with a native stress test. A raced non-atomic refcount is symmetric: a lost
decrement leaks, a lost increment frees early, and the leak direction has no symptom. Four
threads by three million balanced clone-and-drop pairs through an unsound `Sync` exited 0 with a
strong count of 11427 where 1 was correct, and never crashed. Miri reports the race
deterministically on a few hundred iterations. Use Miri.

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

## The `ManuallyDrop<String>` fabrication, and why Miri clears it

This pattern builds a `&String` out of a `&str` by rebuilding the `String` header over the
borrowed buffer and then suppressing the destructor:

```rust
use std::marker::PhantomData;
use std::mem::ManuallyDrop;
use std::ops::Deref;

pub struct StringRef<'a> {
    data: ManuallyDrop<String>,
    _lifetime: PhantomData<&'a str>,
}

impl<'a> StringRef<'a> {
    pub fn new(s: &'a str) -> Self {
        // SAFETY: there is none. `String::from_raw_parts` requires a buffer that
        // came from the global allocator with exactly this capacity, and a `&str`
        // supplies neither guarantee.
        let data = unsafe {
            ManuallyDrop::new(String::from_raw_parts(s.as_ptr() as *mut u8, s.len(), s.len()))
        };
        Self { data, _lifetime: PhantomData }
    }
}

impl Deref for StringRef<'_> {
    type Target = String;
    fn deref(&self) -> &String { &self.data }
}
```

Measured on Miri 0.1.0: this runs clean under the default Stacked Borrows, under
`-Zmiri-tree-borrows`, and under `-Zmiri-strict-provenance`, for a `&'static str` literal and for
a sub-slice of a heap `String`, including a `.clone()` of the deref target. The provenance is
correct, because the pointer comes from a live allocation. The allocator and capacity
precondition is observable only at deallocation, and `ManuallyDrop` prevents that. Miri has
nothing to report.

The private field is therefore the whole safety argument, and `ManuallyDrop::into_inner` is a
safe method that removes it:

```rust,ignore
let lit = "Hello World";
let s = unsafe {
    ManuallyDrop::new(String::from_raw_parts(lit.as_ptr() as *mut u8, lit.len(), lit.len()))
};
let owned: String = ManuallyDrop::into_inner(s);   // a safe call; UB when `owned` drops
```

```text
error: Undefined Behavior: constructing invalid value of type &mut [u8]:
       encountered mutable reference pointing to read-only memory
   --> library/core/src/ptr/mod.rs:820:24
    |
820 |     unsafe { drop_glue(&mut *to_drop) }
```

A sub-slice of a heap `String` fails differently, with `trying to retag from <737> for Unique
permission ... but that tag only grants SharedReadOnly permission for this location`. Without
`ManuallyDrop` at all, the native binary aborts with SIGABRT and prints nothing. Never expose the
field, never derive `Clone`, and never add `DerefMut`. Accept `&str` or `impl AsRef<str>`
instead.

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

### Never materialize two `&mut` from one raw pointer

Both models reject it, and no compile-time diagnostic exists for it. Each `&mut *p` performs a
`Unique` retag, and the second retag kills the first reference:

```rust,ignore
let s1 = unsafe { &mut *p };   // p: *mut State
let s2 = unsafe { &mut *p };   // second Unique retag invalidates s1
s1.counter += 1;               // Stacked Borrows fails here
s2.counter += 10;              // Tree Borrows fails here
```

```text
error: Undefined Behavior: attempting a read access using <506> at alloc179[0x0],
       but that tag does not exist in the borrow stack for this location

error: Undefined Behavior: read access through <488> at alloc179[0x0] is forbidden
```

The shape hides in two common designs. One is state smuggled through `Waker::data()`, where every
concurrently polled future rebuilds a `&mut State` from the same pointer. The other is a
parameter extractor that hands out `&mut T` per parameter. Keep the `*mut T` raw, pass it down,
and form at most one `&mut` at a time from it.

### Moving a `Box` invalidates every pointer taken from it earlier

`Box<T>` wraps `Unique<T>`, so a move retags it and every outstanding tag derived from the old box
dies. Move the `Box` into its final owner **first**, then take the pointer you hand to foreign
code:

```rust
// BAD: the pointer is taken before the Box reaches its final home.
let mut b = Box::new(7u32);
let p: *mut u32 = &mut *b;
let moved = b;              // Unique retag invalidates `p`
unsafe { *p += 1; }         // UB under both models
```

```rust
// GOOD: settle the allocation first, then derive the pointer.
struct Guard { cb: Box<u32> }
let mut g = Guard { cb: Box::new(7u32) };
let p: *mut u32 = &mut *g.cb;
unsafe { *p += 1; }
```

Stacked Borrows blames the raw write; Tree Borrows blames the later use of the moved box:

```text
help: <557> was later invalidated at offsets [0x0..0x4] by a Unique retag
   |     let moved = b;                 // move the Box

error: Undefined Behavior: reborrow through <535> at alloc261[0x0] is forbidden
   = help: the accessed tag <535> has state Disabled which forbids this reborrow
```

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
