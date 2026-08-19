# Type-system and trait traps

Read this file when a diff adds a trait impl, a `Drop` impl, a newtype, a lifetime parameter,
or a large fixed-size array. Each trap is silent: the code compiles, and the defect appears
later at run time, at a downstream consumer, or on a different target.

Each item states a severity, a wrong example, a correct example, and a rule.

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
itself, must consume a field. If yes, use a dedicated guard type with `ManuallyDrop` and
`#[repr(transparent)]`.

---

## Value-passing performance trap

**Severity: WARNING on hot paths**

`fn(T) -> T` copies the value in and out. Once `T` crosses the target's inline-copy boundary,
each call emits a `memcpy` call. rustc cannot rewrite it into `&mut T` mutation, because panic
semantics require the original value to stay valid until the function returns.

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

// GOOD on a hot path: in-place mutation
fn transform(state: &mut BigState) {
    state.counter += 1;
}
```

Use `fn(T) -> T` only in two cases:

- A state-machine transition where the ownership transfer is the semantic. A builder method
  `fn set_foo(mut self) -> Self` is the standard example.
- A type that stays under the boundary of every target you ship. 128 bytes clears both targets
  measured above.

Profile with `cargo-flamegraph` or Criterion before you choose value-passing on any path that
runs per item. `skills/rust-hot-path/references/type-size-reduction.md` holds the probe recipe
that measures the boundary on your own target, and the ways to shrink a type below it.

---

## `Hash` and `PartialEq` contract violation

**Severity: CRITICAL**

The standard library requires that `k1 == k2` implies `hash(k1) == hash(k2)`. If you write
`PartialEq` by hand and derive `Hash`, or the reverse, `HashMap` and `HashSet` return silently
incorrect results.

```rust
// BUG: the derived Hash uses the original case; the manual PartialEq ignores case.
#[derive(Hash)]
struct Tag(String);
impl PartialEq for Tag {
    fn eq(&self, other: &Self) -> bool {
        self.0.to_lowercase() == other.0.to_lowercase()
    }
}
impl Eq for Tag {}
// HashSet<Tag> stores "Foo" and "foo" as two different entries.
```

Rule: when you write a custom `PartialEq`, write a matching custom `Hash` that hashes the same
normalized form. Add a test that inserts through one form and looks up through the other.

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

Rule: implement `Deref` only on a smart pointer. For a domain newtype, write explicit accessor
methods, or implement `AsRef` and `From`.

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

## Lifetime laundering across input and storage

**Severity: CRITICAL**

A function that takes `&'a T` and writes derived references into a long-lived
`HashMap<_, &'a U>` looks elegant. The shared `'a` forces every call site to pick a single
lifetime that spans both the input borrow and the cache. In real code that intersection
collapses to empty almost immediately.

```rust
// BAD: 'a binds the input slice and the cache values together.
fn first_word<'a>(s: &'a str, cache: &mut HashMap<String, &'a str>) -> &'a str {
    if let Some(cached) = cache.get(s) { return cached; }
    let word = s.split_whitespace().next().unwrap_or("");
    cache.insert(s.to_string(), word);
    word
}
// The cache outlives any single `s`. The first call pins 'a to the first input.
// A second call from a different scope fails to compile.

// GOOD: split the lifetimes with a documented contract
fn first_word<'cache, 'input: 'cache>(
    s: &'input str,
    cache: &mut HashMap<String, &'cache str>,
) -> &'cache str { /* ... */ }

// BETTER: store owned data and decouple the lifetimes entirely
fn first_word(s: &str, cache: &mut HashMap<String, String>) -> &str { /* ... */ }
```

Rule: when one `&'a` parameter appears in both an input position and a storage position,
either split the lifetimes with a documented `'input: 'cache` bound, or store owned data. The
single-lifetime form is a trap planted for the next caller.

Find candidates:

```bash
rg "fn .+<'[a-z]+>.*HashMap.*&'[a-z]+" --type rust -n
```

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

## Large stack arrays and the `Box::new([0u8; N])` pitfall

**Severity: WARNING**

`Box::new([0u8; N])` does not allocate `N` bytes directly on the heap. The expression first
builds `[0u8; N]` on the caller's stack, then `Box::new` copies it into a heap allocation. A
debug build performs no placement optimization, so the stack copy is always materialized. It
overflows a constrained thread stack — mobile and embedded targets commonly give a thread
about 1 MiB to 2 MiB — at roughly `N >= 256 KiB`. A release build sometimes removes the copy
through NRVO, but that optimization is fragile. Any intermediate
`let buf = Box::new([0u8; N]);` can materialize the stack copy again.

```rust
// BAD: overflows the stack in debug; relies on brittle NRVO in release.
let buf: Box<[u8; 1024 * 1024]> = Box::new([0u8; 1024 * 1024]);

// BAD: returning a large array by value forces a memcpy through the stack.
fn make_buf() -> [u8; 1024 * 1024] { [0u8; 1024 * 1024] }

// GOOD: allocate on the heap from the start.
let buf: Box<[u8]> = vec![0u8; 1024 * 1024].into_boxed_slice();

// GOOD (Rust 1.82 or later): allocate directly, with no zeroed stack temporary.
let buf: Box<[u8]> = unsafe {
    let mut b = Box::<[u8]>::new_uninit_slice(1024 * 1024);
    std::ptr::write_bytes(b.as_mut_ptr().cast::<u8>(), 0, 1024 * 1024);
    b.assume_init()
};
```

Rule: build any array larger than 16 KiB for heap residence with `Vec::into_boxed_slice` or
`Box::new_uninit_slice`. Never write `Box::new([T; N])` for a large `N`, and never return
`[T; N]` by value for a large `N`. Hot-path code additionally falls under the no-allocation
rule in the main skill.

`Vec::into_boxed_slice` is not free. It calls `shrink_to_fit` whenever capacity exceeds length,
which issues a `realloc` that may move the buffer. Measured with a `Vec<u32>` at length 3:
capacity 3 and capacity 4 keep the data pointer; capacity 8 and capacity 1000 move it. State the
cost as "may cost a full copy when capacity is meaningfully above length", not as "always
copies". The reverse direction has no such cost: `<[T]>::into_vec` never reallocates. When the
length is exact, build the boxed slice straight from the iterator, which allocates once:

```rust
let squares: Box<[u32]> = (0..1024u32).map(|n| n * n).collect();
```

Find candidates:

```bash
rg "Box::new\(\s*\[0?[a-z0-9_]+\s*;\s*[0-9]{4,}" --type rust -n
rg "fn .* -> \[[a-z0-9_]+\s*;\s*[0-9]{4,}\]" --type rust -n
```
