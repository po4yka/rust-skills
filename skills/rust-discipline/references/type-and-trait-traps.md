# Type-system and trait traps

Read this file when a diff adds a trait impl, a `Drop` impl, a newtype, or a lifetime parameter.
Each trap is silent: the code compiles, and the defect appears later at run time, at a downstream
consumer, or on a different target.

Each item states a severity, a wrong example, a correct example, and a rule. Traps that come from
the shape of the data — hash keys, text reversal, and large arrays — live in
[data-shape-traps.md](data-shape-traps.md). What each parameter bound accepts and rejects lives in
[argument-shapes.md](argument-shapes.md). The full cost of `impl Drop` lives in
[drop-and-raii.md](drop-and-raii.md).

---

## `impl Drop` blocks partial moves

**Severity: WARNING**

When a struct implements `Drop`, Rust forbids a move of any field out of it. The restriction
applies inside `Drop::drop` itself. This surprises you when you want to consume a `Vec<T>`
field after you signal completion.

```rust
// BAD: impl Drop prevents a move out of `data`
struct Sink {
    data: Vec<u8>,
}
impl Drop for Sink {
    fn drop(&mut self) {
        let owned = std::mem::take(&mut self.data); // forced to use take()
    }
}

// GOOD: a dedicated guard type keeps `data` moveable
#[repr(transparent)]
struct SinkGuard(std::mem::ManuallyDrop<Vec<u8>>);
impl Drop for SinkGuard {
    fn drop(&mut self) {
        // SAFETY: the value is taken exactly once, here, and never used again.
        let owned = unsafe { std::mem::ManuallyDrop::take(&mut self.0) };
        flush(owned);
    }
}
```

Rule: before you add `impl Drop` to a struct, check whether downstream code, or `Drop::drop`
itself, must consume a field. If yes, move the `Drop` onto a dedicated one-field guard type and
keep the aggregate `Drop`-free. Reach for the `unsafe` `ManuallyDrop` + `#[repr(transparent)]` form
only after `size_of` shows it saves a word. Measured on rustc 1.97.0: a payload with a niche —
`Box`, `NonNull`, `&T`, `NonZero*` — makes `T`, `Option<T>` and `ManuallyDrop<T>` all 8 bytes, so
the safe `Option` guard costs nothing and the `unsafe` rewrite buys nothing.

[drop-and-raii.md](drop-and-raii.md) holds the rest: the eight error codes `impl Drop` turns on
with their exact messages, the E0507 that `if let Some(x) = self.field` gives inside `Drop::drop`,
the four escape hatches, drop order, and the two ways `impl Drop` changes the borrow checker.

---

## Value-passing performance trap

**Severity: WARNING on hot paths**

`fn(T) -> T` copies the value in and out. Once `T` crosses the target's inline-copy boundary,
each call emits a `memcpy` call. rustc does not rewrite it into `&mut T` mutation. This is not a
panic-safety restriction, and no build setting removes it.

The boundary is target-dependent. Measured on rustc 1.97.0 at `-O`, with a
`#[derive(Clone, Copy)] struct T([u8; N])` copied through a function: `x86_64-unknown-linux-gnu`
emits no `memcpy` call up to and including 128 bytes, and one call from 129 bytes up.
`aarch64-apple-darwin` emits none up to and including 256 bytes, and one from 257 bytes up. At
`-C opt-level=0` the boundary is 32 and 33 bytes on both targets, so a debug build cannot probe
the release boundary.

```rust
// BAD on a hot path: forces a memcpy in and a memcpy out
fn transform(mut state: BigState) -> BigState {
    state.counter += 1;
    state
}
```

```rust
// GOOD on a hot path: in-place mutation
struct BigState {
    payload: [u8; 1024],
    counter: u64,
}

fn transform(state: &mut BigState) {
    state.counter += 1;
}
```

Three repairs look plausible and none of them works. Measured on rustc 1.97.0,
`aarch64-apple-darwin`, `-C opt-level=3`, with a 1032-byte state mutated in a loop:

| Form | `memcpy` calls per iteration | Instructions | Stack frame |
| --- | --- | --- | --- |
| `fn evolve_mut(&mut BigState)` | 0 | 14 | none |
| `#[inline] fn evolve(BigState) -> BigState` | 2 | 27 | 1040 bytes |
| the same, rebuilt with `-C panic=abort` | 2 | 27 | 1040 bytes |
| `take_mut`-style `ptr::read` + closure + `ptr::write` | 3 | 42 | 2080 bytes |

`#[inline]` and `#[inline(always)]` both leave the two `memcpy` calls in place: the move into the
callee's argument slot and back out of its return slot are MIR-level copies, and LLVM hands them to
a stack temporary. `-C panic=abort` produces a body that is identical instruction for instruction,
so `panic = "abort"` in the release profile buys nothing here.

The `take_mut` rewrite is the worst of the three. It adds a copy instead of removing one, and it
turns any panic inside the closure into an unconditional abort:

```rust
// ANTI-PATTERN: more copies than the plain value-passing call, and it aborts on panic.
pub fn take<T, F: FnOnce(T) -> T>(mut_ref: &mut T, closure: F) {
    unsafe {
        let old = std::ptr::read(mut_ref);
        let new = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| closure(old)))
            .unwrap_or_else(|_| std::process::abort());
        std::ptr::write(mut_ref, new);
    }
}
```

Measured: a panic inside the closure exits the process with status 134 (`128 + SIGABRT`), and an
enclosing `catch_unwind` never returns. The abort is forced by construction — the closure consumed
a bitwise copy and may have dropped it, so unwinding past `take` would leave the original for a
second drop. Write `fn evolve_mut(&mut BigState)` instead.

Use `fn(T) -> T` only in two cases:

- A state-machine transition where the ownership transfer is the semantic. A builder method
  `fn set_foo(mut self) -> Self` is the standard example.
- A type that stays under the boundary of every target you ship. 128 bytes clears both targets
  measured above.

Profile with `cargo-flamegraph` or Criterion before you choose value-passing on any path that
runs per item. `skills/rust-hot-path/references/type-size-reduction.md` holds the probe recipe
that measures the boundary on your own target, and the ways to shrink a type below it.

The builder receiver shape is the case where the choice is not about copy cost. The three shapes
are not interchangeable, and the receiver decides where the builder can live:

| Setter receiver | Chains | Survives a loop | Terminal builder method |
| --- | --- | --- | --- |
| `fn set(&mut self)` returning `()` | no | yes | `fn build(self) -> T` |
| `fn set(mut self) -> Self` | yes | no | `fn build(self) -> T` |
| `fn set(&mut self) -> &mut Self` | yes | yes | `fn build(self) -> T` from a bound builder |

An owned `self -> Self` setter moves the builder on every call. The second iteration of a loop
then fails with `error[E0382]: use of moved value` and the note `'b' moved due to this method
call, in previous iteration of loop`. A `&mut self -> &mut Self` setter chains and loops, and it
keeps `fn build(self) -> T`. Only the start of the chain constrains the terminal method. Bind the
builder to a variable and the owned build compiles. Start the chain from a temporary, as in
`CfgBuilder::default().name("a").build()`, and it fails with `error[E0507]: cannot move out of a
mutable reference`, with the note `'CfgBuilder::build' takes ownership of the receiver 'self',
which moves value`. The third failure — an owned setter called on a *field* from a `&mut self`
method — is in [argument-shapes.md](argument-shapes.md), together with the `.clone()` that rustc
suggests for it and must not get.

```rust
#[derive(Default, Debug)]
struct Cfg {
    name: String,
    retries: u32,
}

#[derive(Default)]
struct CfgBuilder {
    inner: Cfg,
}

impl CfgBuilder {
    fn name(&mut self, value: &str) -> &mut Self {
        self.inner.name = value.into();
        self
    }

    fn retries(&mut self, value: u32) -> &mut Self {
        self.inner.retries = value;
        self
    }

    // Owned terminal. It needs a bound builder, never a temporary.
    fn build(self) -> Cfg {
        self.inner
    }
}

fn main() {
    let mut builder = CfgBuilder::default();
    builder.name("a").retries(3);
    for attempt in 0..3u32 {
        builder.retries(attempt);
    }
    let cfg = builder.build();
    println!("{cfg:?}");
}
```

Rule: choose the receiver from the call sites, not from the doc example. Conditional or
loop-driven configuration needs `&mut self -> &mut Self`, and keeps `fn build(self) -> T`. Reach
for `fn build(&mut self) -> T` with `std::mem::take` only when the chain must stay one expression
that starts from a temporary. That form costs two things. A second `build()` succeeds and returns
the default: measured on rustc 1.97.0, one `name("real")` setter then two builds prints
`first : Cfg { name: "real", retries: 0 }` and `second: Cfg { name: "", retries: 0 }`. It also
forces `Default` on the built type. Keep the owned `self -> Self` setter when a double build must
be impossible, and accept that it cannot be looped over.

---

## `#[derive(Clone)]` on resource-backed types

**Severity: WARNING**

A derived `Clone` on a struct that holds a resource-backed type — `Arc<Mutex<Connection>>`,
`Arc<Pool>`, `Arc<Cache>` — does not duplicate the resource. It clones the handle. Callers
often expect an isolated copy.

Document the sharing on the type:

```rust
/// Cloning shares the underlying connection pool.
#[derive(Clone)]
pub struct Client {
    pool: std::sync::Arc<Pool>,
}
```

For a raw handle such as `OwnedFd`, `TcpStream`, or a memory-mapped file, `Clone` does not
compile, and the compiler catches the mistake. The silent case is always `Arc<T>`.

---

## `Deref` on a non-pointer type causes method collision

**Severity: WARNING**

`Deref<Target = T>` on a newtype that is not a smart pointer exposes every method of `T`
through auto-deref. This creates silent method shadowing, and it creates a semver break when
either type gains a method.

```rust
// BAD: Deref on a plain domain newtype
struct UserId(u64);
impl std::ops::Deref for UserId {
    type Target = u64;
    fn deref(&self) -> &u64 { &self.0 }
}
// UserId now exposes every u64 method through auto-deref, and leaks the representation.
```

`Deref` gives method reuse, never substitutability: method lookup and `&Target` coercion follow
the chain, trait-bound solving and unsizing to `dyn Trait` do not.

Rule: implement `Deref` only on a smart pointer. For a domain newtype, write explicit accessor
methods, or implement `AsRef` and `From`. For polymorphism, declare a trait and implement it on
each type: `Vec<Box<dyn T>>`, a `&dyn T` parameter, and a generic bound each need the impl, and
none of them accepts a `Deref` in its place. The compiler reports nothing at the point the mistake
is made, only at the first polymorphic use site, by which time the rewrite is a full API change.
[trait-resolution.md](trait-resolution.md) holds the resolution order, the three sites that keep
failing after you add `Deref`, and the exact E0277 each one gives.

---

## `parking_lot` and `tokio` mutexes do not poison on panic

**Severity: WARNING**

`std::sync::Mutex` poisons itself when the thread that holds the guard panics. A later
`lock()` then returns `Err(PoisonError)`. Both `parking_lot::Mutex` and `tokio::sync::Mutex`
remove poisoning: the lock is simply released on panic. Code that migrates from `std` may
still assume that poisoning protects it.

Rule: when you use a `parking_lot` or `tokio` mutex, do not rely on poison detection. If a
panicking writer can leave the guarded data inconsistent, either validate the invariant on the
reader side, or stay on `std::sync::Mutex` and handle `PoisonError` deliberately.

---

## Integer overflow panics in debug and wraps in release

**Severity: WARNING**

Rust panics on integer overflow in a debug build, and wraps silently in a release build. The
usual victims are counter increments, byte-length calculations, and index arithmetic in
parsers.

```rust
let total: u32 = a + b; // panics in debug on overflow; wraps in release

// CORRECT for a fallible path:
let total = a.checked_add(b).ok_or(Error::Overflow)?;

// CORRECT for intentional wrapping (ring buffers, sequence numbers):
let total = a.wrapping_add(b);

// CORRECT for saturation (rate limiters, dimension clamps):
let total = a.saturating_add(b);
```

Rule: use `checked_*` on any value derived from untrusted input, and map the `None` to a
typed error. Enable `clippy::arithmetic_side_effects` on every parser and on every path that
computes a size from external data.

---

## `Arc` reference cycles without `Weak` leak permanently

**Severity: WARNING**

Reference counting cannot break a cycle. Two `Arc`s that point at each other are never
deallocated. Nothing panics and nothing errors. The process simply grows.

```rust
// CYCLE: pool -> connection -> pool. Neither value is ever dropped.
struct Pool { connections: Vec<Arc<Connection>> }
struct Connection { pool: Arc<Pool> }
```

```rust
// FIX: Weak for the child-to-parent direction. The count never holds the cycle.
struct Pool { connections: Vec<Arc<Connection>> }
struct Connection { pool: Weak<Pool> }
```

Rule: in any parent-child relationship where the child needs a reference back to the parent,
use `Weak<T>` for the child-to-parent direction.

---

## A `Weak` registry never reaps dead slots

**Severity: WARNING**

`Weak` breaks the cycle, and it also moves the registration lifetime out of the registry. A
registry that stores `Vec<Weak<dyn Observer>>` accepts a registration whose only `Arc` the caller
drops on the next line. `attach` returns successfully, `notify` then delivers nothing, and no error
appears anywhere. The dead slot also stays in the `Vec` for the life of the subject, so the
registry grows without bound.

Measured on rustc 1.97.0 with two `attach` calls, one observer dropped at once: `slots=2 live=1`,
one delivery, and the `Vec` still two entries long until a reap runs.

```rust
use std::sync::{Arc, Weak};

trait Observer {
    fn observe(&self, state: u32);
}

struct Subject {
    observers: Vec<Weak<dyn Observer>>,
    state: u32,
}

impl Subject {
    fn attach(&mut self, observer: &Arc<dyn Observer>) {
        self.observers.push(Arc::downgrade(observer));
    }

    fn notify(&mut self) {
        // Reap first, or the Vec grows for the life of the subject.
        self.observers.retain(|slot| slot.strong_count() > 0);
        let state = self.state;
        self.observers
            .iter()
            .filter_map(Weak::upgrade)
            .for_each(|observer| observer.observe(state));
    }
}
```

Rule: reap on every notify with `retain(|slot| slot.strong_count() > 0)`. Reaping forces
`notify(&mut self)`; when notify must take `&self`, move the reap into `attach` or give the
registry interior mutability. Either the registry owns the `Arc` and hands the caller a
subscription guard, or `attach` documents that the caller owns the registration lifetime. Do not
put an associated type on the observer trait: a bare `dyn Observer` is then `error[E0191]: the
value of the associated type 'Subject' in 'Observer' must be specified`, which locks the registry
to one subject type. Take the subject as a plain method argument.

---

## Lifetime laundering across input and storage

**Severity: CRITICAL**

A function that takes `&'a T` and writes derived references into a long-lived
`HashMap<_, &'a U>` looks elegant. The shared `'a` forces every call site to pick a single
lifetime that spans both the input borrow and the cache. In real code that intersection
collapses to empty almost immediately.

```rust
use std::collections::HashMap;

// BAD: 'a binds the input slice and the cache values together.
fn first_word<'a>(s: &'a str, cache: &mut HashMap<String, &'a str>) -> &'a str {
    if let Some(cached) = cache.get(s) { return cached; }
    let word = s.split_whitespace().next().unwrap_or("");
    cache.insert(s.to_string(), word);
    word
}
```

The definition above compiles. The call sites do not. The cache outlives any single `s`, so the
first call pins `'a` to the first input, and a second call from a different scope fails.

```rust
use std::collections::HashMap;

// GOOD: split the lifetimes with a documented contract.
fn first_word<'cache, 'input: 'cache>(
    s: &'input str,
    cache: &mut HashMap<String, &'cache str>,
) -> &'cache str { todo!() }
```

```rust
use std::collections::HashMap;

// BETTER: store owned data and decouple the lifetimes entirely.
// The return then borrows the cache, so name that lifetime; elision cannot pick it.
fn first_word<'c>(s: &str, cache: &'c mut HashMap<String, String>) -> &'c str { todo!() }
```

Rule: when one `&'a` parameter appears in both an input position and a storage position,
either split the lifetimes with a documented `'input: 'cache` bound, or store owned data. The
single-lifetime form is a trap planted for the next caller.

Find candidates:

```bash
rg "fn .+<'[a-z]+>.*HashMap.*&'[a-z]+" --type rust -n
```

---

## A `Cow` field infects the struct with a lifetime

**Severity: WARNING**

The same failure family as the section above, from one field. A `Cow<'a, str>` field puts `'a` on
the struct and on every signature that touches it, exactly like a `&'a mut T` field.

`skills/rust-copy-on-write/SKILL.md` holds the whole decision: the E0515 and E0521 shapes, the
`into_static` exit, and the hit rate that decides whether the field is worth a lifetime at all.

---

## A blanket impl in a public API is a semver hazard

**Severity: CRITICAL**

`impl<T: Foo> Bar for T` on a `pub trait Bar` lets a downstream crate write
`impl Bar for MyType` only while `MyType: !Foo`. When a later minor release adds another
blanket impl, narrows a bound, or implements `Foo` for a type the downstream crate uses,
downstream compilation breaks. The error appears in the consumer's CI, months after you ship
the change.

```rust
// HAZARD: a downstream `impl Bar for MyType where MyType: Display`
// can conflict with this on a future version bump.
pub trait Bar { fn bar(&self) -> String; }
impl<T: Display> Bar for T {
    fn bar(&self) -> String { format!("{}", self) }
}
```

```rust
// SAFE: the trait is sealed, so no downstream impl can ever exist,
// and the blanket impl is therefore free of conflict risk.
mod private { pub trait Sealed {} }
pub trait Bar: private::Sealed { fn bar(&self) -> String; }
impl<T: Display + private::Sealed> Bar for T {
    fn bar(&self) -> String { format!("{}", self) }
}
```

Rule: allow a blanket `impl<T: ...> PubTrait for T` only when `PubTrait` is sealed, that is,
it extends a private trait. Otherwise write explicit per-type impls. Going from sealed to
unsealed later is free. Going from blanket to explicit later is a downstream-breaking semver
bump.

Find candidates:

```bash
rg "^impl<T(:\s*\w[\w:+ ]*)?>\s+\w+\s+for\s+T\b" --type rust -n
```

---

## A blanket impl on an empty trait is not a bound alias

**Severity: WARNING**

`trait Featured {}` plus `impl<T: Clone + Debug> Featured for T {}` names a bound set and
propagates nothing. Generic code over `T: Featured` cannot call any method of `Clone` or `Debug`.
The first call fails with `error[E0599]: no method named 'clone' found for type parameter 'T' in
the current scope`, and the help suggests restricting the parameter again, which is the whole cost
the alias was meant to remove. A supertrait declaration propagates every bound to each use site,
and the same blanket impl still applies the trait to every qualifying type automatically.

```rust
use std::fmt::Debug;

// An empty trait plus a blanket impl names a bound set and propagates nothing.
// `T: Featured` alone cannot call `clone`.
trait Featured {}
impl<T: Clone + Debug> Featured for T {}

// A supertrait propagates every bound to each use site. The same blanket impl
// still applies the trait to every qualifying type.
trait Alias: Clone + Debug {}
impl<T: Clone + Debug> Alias for T {}

fn duplicate<T: Alias>(value: T) -> (T, T) {
    let copy = value.clone();
    (value, copy)
}
```

Rule: write the bound set as a supertrait list, never as an empty trait with a blanket impl. The
supertrait form is not free in the other direction: adding a supertrait to a published trait breaks
every existing impl, so declare the full list in the first release. The blanket impl itself still
carries the conflict hazard of the section above, so seal the trait.

---

## A `Clone` supertrait or a `-> Self` method destroys dyn compatibility

**Severity: WARNING**

Each half removes `dyn Trait` on its own, and each gives `error[E0038]`. `Clone` requires
`Self: Sized`, so no vtable can be built. A method that names `Self` in return position gets no
vtable slot. `Debug` alone stays dyn compatible.

The error lands at every `dyn Render` and `Box<dyn Render>` use site, never at the trait
definition, so a one-word edit to the supertrait list breaks code that never mentions `Clone`.

```rust
use std::fmt::Debug;

// `trait Render: Clone + Debug` has no `dyn Render`. `where Self: Sized` on the
// method that names `Self` keeps the rest of the trait usable behind `dyn`.
trait Render: Debug {
    fn draw(&self);

    fn duplicate(&self) -> Self
    where
        Self: Sized;
}

#[derive(Clone, Debug)]
struct Dot;

impl Render for Dot {
    fn draw(&self) {}

    fn duplicate(&self) -> Self {
        self.clone()
    }
}

fn draw_all(items: &[Box<dyn Render>]) {
    items.iter().for_each(|item| item.draw());
}
```

Rule: never put `Clone` in the supertrait list of a trait you intend to use behind `dyn`, and add
`where Self: Sized` to every method that names `Self` in return position. That clause has a cost:
the method cannot be called through `dyn Trait` at all. `skills/rust-compiler-errors/SKILL.md`
holds the E0038 triage — the five shapes that remove the vtable, the `...because` note that names
which one you hit, and the `clone_box` replacement for a `Clone` supertrait.

---

## A trait bound on a struct definition is viral and guarantees nothing

**Severity: WARNING**

`struct Container<T: Featured>` does not reach the caller as a guarantee. It only forces every impl
block, every function signature, and every derive on that type to repeat the bound. An impl block
that omits it fails with `error[E0277]: the trait bound 'T: Featured' is not satisfied` pointing at
the impl header, with `note: required by a bound in 'Container'`. The reflexive fix, copying the
bound onto that impl too, spreads the constraint through the file until an unrelated caller cannot
satisfy it.

```rust
trait Featured: Clone {}

// No bound on the definition. Every impl block is then free to omit it.
struct Container<T> {
    item: T,
}

impl<T> Container<T> {
    fn get(&self) -> &T {
        &self.item
    }
}

// The bound sits on the one impl that needs it.
impl<T: Featured> Container<T> {
    fn duplicate(&self) -> T {
        self.item.clone()
    }
}
```

Rule: declare the type parameter bare, and put each bound on the impl block that needs it. One case
does need the bound on the definition: a `where` clause that an associated type or a const generic
expression depends on. Do not remove such a bound blindly. Removing a bound from a published struct
is not a breaking change; adding one is.
