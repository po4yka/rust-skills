# Drop and RAII

Read this file before you add `impl Drop` to a type, and when a diff moves a `Drop` impl from one
type to another. `impl Drop` is not a hook you attach to a struct. It is a property of the type
that turns on eight error codes at once, at sites far from the impl.

Every result below is from rustc 1.97.0, edition 2024, `aarch64-apple-darwin`.

---

## The cost table

Each row is an error that `impl Drop` turns on. None of these errors exists before you add the
impl. The restriction is on the *type*, not on the body: an empty `fn drop(&mut self) {}` costs
exactly as much as a full one.

| Code | Site the error lands on | Exact message | Fix |
| --- | --- | --- | --- |
| E0509 | a move of any non-`Copy` field: `take(value.name)` | `cannot move out of type 'S', which implements the 'Drop' trait` | move `Drop` to a one-field guard |
| E0509 | destructuring: `let S { a, b } = value;` | same message, `note: move occurs because these variables have types that don't implement the 'Copy' trait` | bind by reference, or destructure a guard-free aggregate |
| E0509 | functional record update: `S { a: new, ..old }` | same message, `help: clone the value from the field instead of using the functional record update syntax` | build the whole struct explicitly |
| E0507 | `if let Some(x) = self.field` inside `Drop::drop` | `cannot move out of 'self.h' as enum variant 'Some' which is behind a mutable reference` | match on `self`, or call `self.h.take()` |
| E0184 | `#[derive(Copy)]` on the same type | `the trait 'Copy' cannot be implemented for this type; the type has a destructor` | remove `Copy`, or remove `Drop` |
| E0367 | `impl<T: Debug> Drop for S<T>` over `struct S<T>` | `'Drop' impl requires 'T: Debug' but the struct it is implemented for does not` | repeat the bound on the struct, or drop it from the impl |
| E0740 | a union field of that type | `field must implement 'Copy' or be wrapped in 'ManuallyDrop<...>' to be used in a union` | wrap the field in `ManuallyDrop<T>` |
| E0502, E0505 | any use of the borrowed value after the guard is created | `mutable borrow might be used here, when '_g' is dropped and runs the 'Drop' code for type 'Guard'` | close the scope, or call `drop(guard)` |
| E0597 | the borrowed value is declared after the holder | `'s' does not live long enough` plus `borrow might be used here, when '_h' is dropped and runs the 'Drop' code for type 'Holder'` | declare the borrowed value first |

`Copy` fields are exempt from E0509. `eat_u32(value.n)` with `n: u32` compiles on a `Drop` type.

---

## Moving a field out inside `Drop::drop`

`Drop::drop` receives `&mut self`. It never receives `self`. So the natural line fails:

```rust,compile_fail
struct Handle;
impl Handle {
    fn report(&self, _message: &str) {}
}

struct Guard {
    handle: Option<Handle>,
}

impl Drop for Guard {
    fn drop(&mut self) {
        if let Some(handle) = self.handle {
            handle.report("destroyed before use");
        }
    }
}
```

```text
error[E0507]: cannot move out of `self.handle` as enum variant `Some` which is behind a mutable reference
help: consider borrowing here
```

Two fixes work, and they are not equivalent.

**Fix 1 — match on `self`, not on the field.** Match ergonomics then bind `handle` as `&mut Handle`
and no move happens. Use this when `drop` only reads the field.

```rust
struct Handle;
impl Handle {
    fn report(&self, _message: &str) {}
}

struct Guard {
    handle: Option<Handle>,
}

impl Drop for Guard {
    fn drop(&mut self) {
        let Self { handle: Some(handle) } = self else { return };
        handle.report("destroyed before use");
    }
}
```

**Fix 2 — take ownership out of the field.** Use this when `drop` must pass the value to a
function that consumes it.

```rust
struct Handle;
fn consume(_handle: Handle) {}

struct Guard {
    handle: Option<Handle>,
}

impl Drop for Guard {
    fn drop(&mut self) {
        let Some(handle) = self.handle.take() else { return };
        consume(handle);
    }
}
```

Do not accept rustc's `help: consider borrowing here` without reading it. It turns Fix 2 into
Fix 1 silently, and the consuming call then fails with a second error.

---

## The four escape hatches

Pick by the field type, not by habit.

| Hatch | Requires | Leaves behind | Use it when |
| --- | --- | --- | --- |
| `self.field.take()` | the field is `Option<T>` | `None` | the field is already optional for a domain reason |
| `std::mem::take(&mut self.field)` | `T: Default` | `T::default()` | `String`, `Vec<T>`, any collection |
| `std::mem::replace(&mut self.field, cheap)` | a cheap valid `T` | `cheap` | `T` has no `Default` but a null-ish value exists |
| `ManuallyDrop::take(&mut self.field)` | `unsafe`, exactly one call | nothing valid | the field must have no empty state at all |

`mem::take` on a trait object does not compile. `Box<dyn Trait>` has no `Default`:

```text
error[E0277]: the trait bound `dyn Data: Default` is not satisfied
    = note: required for `Box<dyn Data>` to implement `Default`
note: required by a bound in `std::mem::take`
```

Measure before you reach for the `unsafe` `ManuallyDrop` form. It buys size only when the payload
has no niche. Measured with `struct BoxedHandle(Box<u32>)`: `BoxedHandle`, `Option<BoxedHandle>`
and `#[repr(transparent)] struct Guard(ManuallyDrop<BoxedHandle>)` are all 8 bytes, so the unsafe
rewrite saves nothing. With `struct PlainHandle(u32)`: 4 bytes against 8 for `Option<PlainHandle>`,
and only then does the trade have a payoff. Any `Box`, `NonNull`, `&T` or `NonZero*` payload has a
niche.

---

## Drop order

```rust
struct Noisy(&'static str);
impl Drop for Noisy {
    fn drop(&mut self) {
        println!("drop {}", self.0);
    }
}

struct Outer {
    first: Noisy,
    second: Noisy,
    third: Noisy,
}

impl Drop for Outer {
    fn drop(&mut self) {
        println!("drop Outer body");
    }
}

fn main() {
    // prints: drop Outer body, drop f1, drop f2, drop f3
    let _outer = Outer { first: Noisy("f1"), second: Noisy("f2"), third: Noisy("f3") };
}
```

| Container | Order | Measured output |
| --- | --- | --- |
| a type with a user `Drop` | body first, then fields in **declaration** order | `drop Outer body`, `f1`, `f2`, `f3` |
| locals in a scope | **reverse** declaration order | `l3`, `l2`, `l1` |
| tuple, array, `Vec<T>` | front to back | `t1`, `t2`, `t3` |
| a partially moved struct | the moved field drops where it moved to; the rest drop at end of scope | `eaten inside fn`, `drop px`, `after eat`, `drop py` |

The field you declare **last** stays alive longest inside a struct. This is the opposite of C++,
where members are destroyed in reverse declaration order. When one field must outlive another
during cleanup, declare the longer-lived one last, and write the reason next to it.

---

## The two ways `impl Drop` changes the borrow checker

**1. NLL stops ending the borrow early.** Without `Drop`, a borrow ends at its last use. With
`Drop`, the implicit call at end of scope is a use, so the borrow lives to the closing brace.

```rust,compile_fail
struct Guard<'a>(&'a mut u32);
impl<'a> Drop for Guard<'a> {
    fn drop(&mut self) {}
}

fn main() {
    let mut count = 0u32;
    let _guard = Guard(&mut count);
    println!("{count}"); // E0502 with the Drop impl; compiles without it
}
```

The diagnostic names the cause: `mutable borrow might be used here, when '_guard' is dropped and
runs the 'Drop' code for type 'Guard'`. Fix it with an explicit `drop(guard)` or a tighter scope.

**2. Dropck requires the borrowed value to strictly outlive the holder.** Without `Drop`, this
compiles. With `Drop`, it is E0597.

```rust,compile_fail
struct Holder<'a>(&'a String);
impl<'a> Drop for Holder<'a> {
    fn drop(&mut self) {}
}

fn main() {
    let _holder;
    let text = String::from("x");
    _holder = Holder(&text); // E0597: `text` does not live long enough
}
```

The note `values in a scope are dropped in the opposite order they are defined` is the fix
instruction: declare `text` before `_holder`.

The standard library relaxes dropck with `unsafe impl<#[may_dangle] 'a> Drop for ...`, which is how
`Vec<T>` and `Box<T>` accept a `T` that borrows a shorter-lived local. That attribute is not
available to you: it is gated behind `dropck_eyepatch` and gives
`error[E0658]: 'may_dangle' has unstable semantics and may be removed in the future` on stable.
Restructure the declaration order instead.

---

## The design rule: one guard field, never the aggregate

E0509 belongs to the type that implements `Drop`. Confine that type to one field and you confine
every cost in the table above to that field. The aggregate then keeps partial moves, and no other
field needs an `Option` or an `unwrap`.

```rust
trait Data {
    fn inspect(&self);
}

struct ErrorHandle;
impl ErrorHandle {
    fn report(&self, _message: &str) {}
}

struct NotUsedGuard(Option<ErrorHandle>);

impl NotUsedGuard {
    fn new(handle: ErrorHandle) -> Self {
        Self(Some(handle))
    }

    fn disarm(mut self) {
        self.0 = None;
    }
}

impl Drop for NotUsedGuard {
    fn drop(&mut self) {
        let Self(Some(handle)) = self else { return };
        handle.report("destroyed before use");
    }
}

struct Gadget {
    data: Box<dyn Data>,
    not_used: NotUsedGuard,
}

impl Gadget {
    // No Option, no unwrap: `data` is a plain field.
    fn inspect(&self) {
        self.data.inspect();
    }

    // Legal partial move: the guard field is consumed, then `data` moves out.
    fn use_it(self) -> Box<dyn Data> {
        self.not_used.disarm();
        self.data
    }
}
```

Put `impl Drop for Gadget` on the aggregate instead and `self.data` in `use_it` becomes E0509. The
reflexive repair is `data: Option<Box<dyn Data>>` plus an `unwrap` in every method, which moves a
compile-time guarantee into a run-time panic.

---

## Leaking is safe, so a guard is never a soundness argument

`std::mem::forget`, `Box::leak`, a `Rc`/`Arc` cycle, `ManuallyDrop`, and `std::process::exit` all
skip the destructor. None of them is `unsafe`. Measured: `mem::forget(guard)` returns and the
`Drop` body never runs.

Destructors are guaranteed on exactly one non-local path — unwinding. A `catch_unwind` around a
scope that holds a guard still runs the guard's `drop`.

The consequence for review: **never write a safety comment whose argument is "the guard runs".**
A caller can leak the guard and every invariant the guard restores stays broken. If the invariant
is a memory-safety invariant, the design is unsound whatever the guard does. See
`skills/rust-unsafe/SKILL.md` for the rule and the API shapes that survive a forgotten guard, and
`skills/rust-pin-projection/SKILL.md` for the one guarantee the language does give: a pinned value
is dropped before its memory is reused.

Use a guard for the things leaking cannot corrupt: closing a descriptor, releasing a lock,
decrementing a metric, flushing a buffer. `scopeguard::defer!` covers the fallible variant.
