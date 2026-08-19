---
name: rust-discipline
description: Rust code discipline for API design, anti-patterns, panic policy, error propagation, RAII and Drop, allocation in hot paths, concurrency primitive choice, atomic ordering, unsafe encapsulation, FFI panic containment, and lint non-regression. Use when you author or review pub and pub(crate) signatures, struct definitions, and trait bounds, during code review or pre-merge self-check, and when you tighten existing Rust code.
license: BSD-3-Clause
---

# Rust Discipline

## Purpose

Catch high-signal Rust mistakes before they land. Apply these rules to public (`pub`) and
crate-public (`pub(crate)`) function signatures, struct definitions, and trait bounds.

Use this skill in three situations:

- You author a new API or change an existing signature.
- You review a diff.
- You tighten existing code before a merge.

Apply every rule to every changed signature in a diff, not only to the first one.

Each rule carries a severity:

| Severity | Meaning |
|----------|---------|
| CRITICAL | Blocks the merge. The defect is silent, or it breaks downstream code. |
| WARNING  | Fix it, or write a one-line justification in the diff. |

Deep trait-level and type-level traps live in
[`references/type-and-trait-traps.md`](references/type-and-trait-traps.md). Read that file
when you review a diff that adds a trait impl, a `Drop` impl, a newtype, or a lifetime
parameter. Method resolution and coherence traps live in
[`references/trait-resolution.md`](references/trait-resolution.md). Read that file when a diff
adds a `Deref` impl, an extension trait, a `downcast_ref` chain, or a second conversion impl on
one type pair. Traps that come from the shape of the data — hash keys, text reversal, and large
arrays — live in [`references/data-shape-traps.md`](references/data-shape-traps.md).

---

## API design

### Accept borrowed args, not owned references

**Severity: WARNING**

Accept `&str`, `&[T]`, and `&Path` instead of `&String`, `&Vec<T>`, and `&PathBuf`. The
owned-reference shapes force the caller to hold an allocation, even when the caller has a
slice. The borrowed shapes accept both.

```rust
// BAD: forces the caller to have a String
fn log(msg: &String) {}

// GOOD: accepts &str, String, Arc<str>, Cow<str>, and more
fn log(msg: &str) {}
```

For generic inputs, prefer `impl AsRef<T>` over a concrete `&T`:

```rust
fn open(path: impl AsRef<std::path::Path>) {}
```

Find violations:

```bash
rg ':\s*&(String|Vec<|PathBuf)\b' --type rust -n
```

Keep an iterator's extra reference out of a public bound. `items.iter().find(pred)` under
`F: Fn(&T) -> bool` fails with `E0277: expected a 'FnMut(&&T)' closure`, because
`Iterator::find` passes `&Self::Item` and `Item` is already `&T`. Widening the bound to
`Fn(&&T) -> bool` compiles and pins `&&T` into the API for ever. Re-borrow in the body instead:
`items.iter().find(|item| pred(item))`.

### Return a slice, not the container type

**Severity: WARNING**

`fn items_mut(&mut self) -> &mut Vec<String>` puts `Vec` in the public signature. A later switch
to `Box<[String]>` breaks every caller with `E0599: no method named 'push' found for mutable
reference '&mut [String]'`, which reads like a caller mistake and ships as a patch release. The
read accessor `-> &[String]` survives the same switch untouched. Inside one crate a
`&mut Vec<T>` accessor costs nothing; apply the rule to a published API.

```rust
pub struct Order {
    items: Vec<String>,
}
impl Order {
    pub fn items(&self) -> &[String] { &self.items }
    // `&mut Vec<String>` here would pin `Vec` into the public signature.
    pub fn items_mut(&mut self) -> &mut [String] { &mut self.items }
    // Name every operation that changes the length.
    pub fn add_item(&mut self, item: String) { self.items.push(item); }
}
```

### Store a callback as `Box<dyn Fn>`, not `Box<dyn FnMut>`

**Severity: WARNING**

No two closures share a type, so a `Vec<F>` never holds two of them, and `impl Fn` in a field
fails with `E0562`. The stored form is `Box<dyn Fn(..)>`. `Box<dyn FnMut(..)>` needs a unique
borrow at the call, so `publish(&self)` fails with `E0596` and must become `&mut self`, which
propagates to every caller and blocks sharing the owner behind an `Arc`. Require `Fn`, and put
the mutation inside the callback's own `Cell` or `Mutex`.

```rust
pub struct Bus {
    // `dyn Fn` keeps `publish(&self)`. `dyn FnMut` forces `publish(&mut self)`.
    subs: Vec<Box<dyn Fn(u32)>>,
}
impl Bus {
    pub fn subscribe(&mut self, f: impl Fn(u32) + 'static) { self.subs.push(Box::new(f)); }
    pub fn publish(&self, ev: u32) { for s in &self.subs { s(ev); } }
}
```

The field carries an implicit `+ 'static` bound. Clone the captured data; do not add a lifetime
parameter to the owner, and do not store `Weak` callbacks to dodge it. A `Weak` registration
dies when the caller releases its `Arc`, and the drop is silent: measured at 1 entry held, 0
callbacks fired, no warning and no error.

### Do not store `&'a mut H` in a struct field

**Severity: CRITICAL**

A `&'a mut H` field infects every use site with the lifetime `'a`. You then cannot store the
struct in another struct, and you cannot return it from a function. This is **lifetime
infection**.

```rust
// BAD: lifetime infection
struct Processor<'a> {
    handler: &'a mut dyn Handler,
}
// Every function that takes `Processor<'_>` must now carry the lifetime.
// `Vec<Processor<'_>>` is impossible.

// GOOD: generic H, plus delegating impls for &mut H and Box<H>
struct Processor<H: Handler> {
    handler: H,
}
impl<H: Handler> Handler for &mut H { /* delegate */ }
impl<H: Handler> Handler for Box<H> { /* delegate */ }
// Processor<&mut MyHandler> and Processor<Box<dyn Handler>> both work.
```

Write the delegation impls with a macro to remove the boilerplate:

```rust
macro_rules! impl_handler_for_refs {
    ($T:ident) => {
        impl<H: $T + ?Sized> $T for &mut H { /* delegate all methods */ }
        impl<H: $T + ?Sized> $T for Box<H> { /* delegate all methods */ }
    };
}
```

Find candidates, then check each hit for a `&'_ mut` field:

```bash
rg "struct .+<'.+>\s*\{" --type rust -n
```

### Use HRTB for callbacks that must not keep the reference

**Severity: WARNING**

`for<'a> Fn(&'a T) -> R`, where `R` does not depend on `'a`, is the correct shape for a
callback that may keep the return value but not the reference. The `for<'a>` bound stops the
callback from storing `&'a T`. The callback must extract owned data and return it.

If the callback stores a reference and you used a non-HRTB bound, the borrow checker
eventually rejects a valid use site. If you widened the lifetime to silence that error, the
code is probably unsound.

Rules:

- When the callback must not keep the argument reference, write `for<'a>` explicitly.
- When the return type depends on the argument lifetime — for example, the callback returns a
  slice of the input buffer — use a GAT or a named lifetime instead.
- Pick the bound from three separate axes. `move` decides the capture mode. The body decides
  the trait: a read-only body gives `Fn` even under `move`, and a body that moves a non-`Copy`
  capture out gives `FnOnce`, whose second call fails with `E0382`. The captured types decide
  the lifetime. A closure coerces to `fn` only with an empty capture set; one captured `i32`
  blocks it with `E0308`.
- Declare a method lifetime on the method, or elide it. `impl<'a> Doc { fn view(&'a self) ->
  View<'a> }` is early bound, so `Doc::view` fails a `for<'x>` bound with `implementation of
  'Fn' is not general enough` — no error code, no suggested fix. `impl Doc { fn view(&self) ->
  View<'_> }` is late bound and passes. A direct call compiles under both forms, so test the
  bound by passing the method path itself.

---

## Panic discipline

- **No `.unwrap()` in non-test code.** Use `?` to propagate. Use
  `.expect("<documented invariant>")` only when the invariant is unconditional.
- **`.expect` messages state invariants, not wishes.** `"should never fail"` is not
  acceptable. Write what must be true: `"config validated at startup"`,
  `"channel never closed: sender held for process lifetime"`.
- **`panic!`, `unreachable!`, and `todo!` are for impossible cases only.** Each occurrence
  carries a reason: `unreachable!("Step kind {kind:?} filtered earlier")`.
- **`#[should_panic]` is test-only.** Do not build library control flow on an expected panic.
  Return `Result` instead.
- **Panics must not cross an FFI boundary.** See the FFI section below.

See also: `rust-panic-safety`.

## Error propagation

- Prefer `?` over `match result { Ok(v) => v, Err(e) => return Err(e.into()) }` for
  pass-through.
- Use `anyhow::Context::context` for static messages. Use `with_context` only when the
  message needs allocation or formatting. `with_context(|| format!(...))` on a happy path is
  an allocation hazard, because the closure captures eagerly even when it never runs.
- **A library crate never returns `Box<dyn std::error::Error>`.** Define a crate-level error
  type with `thiserror`, and translate at the boundary.
- Push `map_err` adapters to module boundaries and public APIs. Inside a leaf function, a
  `map_err` hides the original error source.
- Pick one canonical error type per workspace layer. Either every engine crate returns one
  shared error type, or each crate defines its own enum and the caller translates. Do not mix
  the two conventions in one dependency chain.

See also: `ffi-error-progress-cancel`.

## Drop and RAII

- Prefer `std::os::fd::OwnedFd` and `OwnedSocket` over a raw `i32`. A raw file descriptor
  leaks on every error path that does not call `close()` explicitly.
- When you implement `Drop` on a cleanup-critical type, document the cleanup order and every
  ordering dependency between fields. Struct field declaration order is the drop order.
- Use `scopeguard::defer!` for fallible cleanup that must run on all exit paths. This includes
  panic paths, unless the profile sets `panic = "abort"`.
- When another component owns the descriptor and gives it to you, duplicate it before you take
  ownership. See `rust-unsafe`.
- `impl Drop` blocks partial moves out of the struct. See
  [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md).

## Match exhaustiveness

- **No `_ =>` wildcard on an internal (crate-private) enum.** A wildcard absorbs new variants
  silently and defeats the compiler exhaustiveness check. Write explicit arms.
- Mark a cross-crate public enum `#[non_exhaustive]`. Downstream code then cannot break when
  you add a variant.
- For a small internal enum (fewer than 8 variants), list every arm explicitly, even when the
  handling is identical. This forces a review when someone adds a variant.
- `if let`, `let else`, and `while let` are acceptable for single-variant extraction. They do
  not defeat exhaustiveness.
- **A `downcast_ref` chain is a match with the exhaustiveness check removed.** Measured with
  three implementors and two `if let Some(x) = any.downcast_ref::<T>()` arms: the build is
  clean, no lint fires, and the program handles 2 of 3 values. When the set of types is closed
  and the code needs the concrete data, use an enum; the same gap then fails with `E0004` and
  names the variant. See [`references/trait-resolution.md`](references/trait-resolution.md).

## Allocation in hot paths

A hot path is any code that runs per packet, per frame, per row, per record, or per byte.

- **Do not call `Vec::new()`, `String::from`, `format!`, `to_owned()`, or `.to_string()`** in
  an event-loop tick, a per-item classifier, a per-byte parser, or any inner decode loop.
- When the path must format, format into a reused `String`: add `use std::fmt::Write as _;`,
  then call `buf.clear()` and `write!(buf, "...")` per iteration. Measured on rustc 1.97.0,
  1000 iterations cost 1000 allocations with `format!` and 1 with the reused buffer. Without the
  `Write` import, `write!` fails with `E0599: cannot write into String`.
- Prefer `SmallVec` or `ArrayVec` with an inline capacity at the mode of the length
  distribution, not at the 95th percentile: a larger `N` grows every value, empty ones included.
  On 64-bit with smallvec 1.15.2 the size is `max(24, 16 + size_of::<[T; N]>())`, so
  `SmallVec<[u32; 4]>` is 32 bytes and `SmallVec<[u32; 32]>` is 144 bytes against 24 for
  `Vec<u32>` — six times the `memcpy` on every move. `ArrayVec<u32, 4>` is 20 bytes with
  arrayvec 0.7.8 and never spills, and a spilled `SmallVec<[u32; 4]>` jumps to capacity 8 and
  rejoins the normal `Vec` ladder instead of growing from `N`. See
  `skills/rust-hot-path/references/allocation-reduction.md` for the full table.
- Reuse buffers. Pass `&mut Vec<u8>` as an out-parameter instead of returning `Vec<u8>` by
  value.
- Do not call `.to_string()` in an error constructor on a hot path. Pass a `&'static str` or
  an enum discriminant, then format at the logging boundary.
- Value-passing (`fn(T) -> T`) of a large struct also costs a `memcpy`. See
  [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md).

See also: `rust-performance` for measurement with `cargo-bloat` and `cargo-llvm-lines`.

## Concurrency primitive selection

- **Use `RwLock` for read-heavy state**, at a read:write ratio of 3:1 or higher. Use `Mutex`
  otherwise. Under write contention an `RwLock` is slower than a `Mutex`.
- Document the lock order at the struct level with a `// Lock order: a -> b -> c` comment.
  Every nested acquisition follows that order.
- `parking_lot` 0.12.5 locks are not automatically faster or smaller than `std::sync` locks.
  Std improved its own lock implementations on several platforms, and the Rust Performance Book
  now tells you to measure both before you switch. `parking_lot` locks still do not poison. Add
  `parking_lot` only after you measure contention.
- **`parking_lot` and `tokio::sync` mutexes do not poison on panic.** `std::sync::Mutex` does.
  See [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md) before you
  migrate.
- **Never hold a lock across `.await`.** Acquire the guard, extract what you need, then drop
  the guard explicitly before any `.await`.
- **Wait on a `Condvar` only through a predicate.** A `Condvar` keeps no count, so a bare `wait`
  blocks for ever when the notify arrives first. Call
  `cv.wait_while(lock.lock().unwrap(), |v| *v == 0)`, stable since 1.42.0, which checks the
  predicate under the lock before it sleeps and after every wake. Measured with a worker that
  notifies 200 ms before the waiter starts: the bare form hangs and `timeout 3` kills it with
  exit 124; `wait_while` exits 0. The predicate reads only state that the same mutex protects.
- Do not mix `rayon` parallel iterators with async code. Keep a `rayon` region inside a
  dedicated blocking closure.

See also: `rust-async-internals`, `memory-model`.

## Atomic memory ordering

- Every new `AtomicBool`, `AtomicUsize`, or `AtomicPtr` call site carries a `// Ordering:`
  comment that states the happens-before contract.
- Do not copy `Relaxed` from neighbouring code without a re-audit. Ordering is per use, not
  per type.
- A publish/subscribe atomic — a flag that signals a completed write — needs `Release` on the
  store and `Acquire` on the load. `Relaxed` is silently wrong here on weakly ordered targets
  such as ARM64.
- Add a `loom` test or a targeted test for every new publish/subscribe atomic.

See also: `memory-model`.

## Blocking work in an async or parallel runtime

| Work shape | Correct escape |
|------------|----------------|
| Bounded CPU or syscall work under about 100 ms | `tokio::task::spawn_blocking` |
| Long-lived loop, or large blocking work that would starve the blocking pool | `std::thread::spawn` |
| Compute-bound data parallelism (decode, geometry, raster) | `rayon` |
| Blocking I/O in a synchronous engine with no runtime | Keep it synchronous. Do not add a runtime for it. |

Rules:

- Never call a blocking syscall — `std::thread::sleep`, `std::fs::*`, `std::net::*` — directly
  inside async code without one of these escapes.
- Do not perform blocking I/O inside a `rayon` task. Load the data before the parallel
  section.
- Do not add `tokio` or `async-std` as a direct dependency of a synchronous engine crate. A
  transitive `tokio` behind a blocking HTTP client stays encapsulated behind blocking calls.

See also: `rust-async-internals`.

## Unsafe boundary encapsulation

- Keep an `unsafe fn` `pub(crate)` behind a safe `pub` wrapper. An external caller never
  writes `unsafe { ... }` to use your crate.
- Every `unsafe` block carries a `// SAFETY:` comment. Every `pub unsafe fn` carries a
  `# Safety` rustdoc section. Enforce both with lints, not with review alone.
- If you must relax `missing_safety_doc` or `not_unsafe_ptr_arg_deref`, scope the `allow` to
  the `extern "system"` or `extern "C"` entry-point module. An internal `unsafe fn` in a
  non-FFI module still carries a `# Safety` section.

Set the gate in the workspace `Cargo.toml`, then inherit it in every member crate:

```toml
# workspace Cargo.toml
[workspace.lints.clippy]
undocumented_unsafe_blocks = "deny"
multiple_unsafe_ops_per_block = "deny"
missing_safety_doc = "deny"
not_unsafe_ptr_arg_deref = "deny"
```

```toml
# member crate Cargo.toml
[lints]
workspace = true
```

`undocumented_unsafe_blocks` and `multiple_unsafe_ops_per_block` together make one
`// SAFETY:` comment per unsafe operation mandatory.

See also: `rust-unsafe`, `rust-sanitizers-miri`.

## FFI boundary: panics and error translation

**Severity: CRITICAL**

A panic that unwinds across an FFI boundary is undefined behavior. Depending on the
generator, it either aborts the process or corrupts the host runtime.

- **Do not panic inside an FFI entry point.** Return `Result<T, BoundaryError>` for all
  fallible work, and let the binding layer translate it.
- Use `std::panic::catch_unwind` at the outermost entry point only when you cannot remove an
  unexpected panic path. Log the payload, then return a forward-compatible catch-all error
  variant.
- Define one boundary error type. Keep it flat, give it a `Display` impl, and give it a
  catch-all variant for forward compatibility. Translate the internal crate error into it with
  a `From` impl at the boundary. Do not annotate the internal error type with the binding
  generator's derive.
- When a binding generator produces the bridging glue, do not hand-write `extern "C"` entry
  points or raw JNI calls next to it. If a hand-written boundary is genuinely required — for
  example, a zero-copy buffer handoff — apply maximum rigor: wrap it immediately, allow no
  panic across the boundary, and take no raw pointer as a parameter.
- Handle every consumer platform symmetrically. An error type that serializes cleanly for one
  host language and not for another is a defect.

See also: `uniffi-boundary`, `rust-jni`, `ffi-error-progress-cancel`, `rust-panic-safety`.

## Lint non-regression

- Never silence a `clippy::correctness` or `clippy::suspicious` finding with `#[allow(...)]`.
  Set both groups to `deny` at the workspace level, and fix the code instead.
- A new `ignore` entry in `deny.toml` needs a tracking issue and a time-boxed expiry date in
  the same commit.
- Keep the `disallowed-methods` list in `clippy.toml` enforced on new code. Do not add a call
  to a disallowed method and then `#[allow]` it locally.
- An `#[allow]` for a single lint of the `clippy::pedantic` group is acceptable at module or
  block scope with a one-line justification. A crate-wide `#![allow(clippy::pedantic)]` is
  not.
- Enable `clippy::arithmetic_side_effects` on every parser and on every path that computes a
  length from untrusted input.

See also: `rust-lints`, `rust-security`.

---

## Quick review checklist

Apply this checklist to every changed `pub` or `pub(crate)` API, and to every Rust pull
request.

**API design**

1. Any `&String`, `&Vec<T>`, or `&PathBuf` parameter? Use `&str`, `&[T]`, `&Path`, or
   `impl AsRef<...>`.
2. Any `&'a mut Trait` stored in a struct field? Use a generic `H: Trait` instead.
3. Any callback without `for<'a>` where the caller must not keep the reference? Add the HRTB.
4. Any `pub` accessor that returns `&mut Vec<T>` or `&mut String`? Return `&mut [T]` or
   `&mut str`, and name each length-changing operation. Any public bound that names `&&T`?
5. Any callback stored as `Box<dyn FnMut>` where `Box<dyn Fn>` works? Any `Weak` callback
   registry that drops registrations silently?
6. Any `Fn` bound picked from the `move` keyword instead of the body? Any callback method whose
   lifetime sits on the `impl` block instead of the method?

**Panics, errors, and resources**

7. Any new `.unwrap()`, or any bare `.expect()` with no invariant in the message, outside
   tests?
8. Any `Box<dyn std::error::Error>` returned from a library crate?
9. Any raw `i32` file descriptor held across an error path? Any `Drop` impl with no documented
   ordering?
10. Any `_ =>` arm in a match over an internal enum? Any `downcast_ref` chain over a closed set
    of types?

**Performance and concurrency**

11. Any allocation inside an event-loop tick, a per-item decode loop, or a parser hot path?
12. Any lock held across `.await`? Any `RwLock` that protects a write-heavy field? Any `rayon`
    parallel iterator mixed with async code? Any `Condvar::wait` outside a predicate loop or a
    `wait_while` call?
13. Any new atomic with no `// Ordering:` comment? Any `Relaxed` on a publish/subscribe flag?
14. Any blocking syscall inside async with no `spawn_blocking` and no dedicated thread? Any
    blocking I/O inside a `rayon` task?

**Unsafe, FFI, and lints**

15. Any internal `unsafe fn` with no `# Safety` rustdoc section? Any `unsafe` block with no
    `// SAFETY:` comment?
16. Any FFI entry point that can panic instead of returning a `Result`?
17. Any new `#[allow(clippy::correctness | suspicious)]`? Any new `deny.toml` ignore with no
    tracking issue and no expiry?

**Trait and type-system traps** (details in
[`references/type-and-trait-traps.md`](references/type-and-trait-traps.md),
[`references/trait-resolution.md`](references/trait-resolution.md), and
[`references/data-shape-traps.md`](references/data-shape-traps.md))

18. Any `impl Drop` on a struct where a field must be consumed? Use a dedicated guard type
    with `ManuallyDrop`.
19. Any `fn(T) -> T` that takes a struct past the target's inline-copy boundary (128 bytes on
    x86_64, 256 on aarch64) on a hot path?
20. Any custom `PartialEq` with no matching custom `Hash`, or the reverse, on a `HashMap` or
    `HashSet` key?
21. Any `#[derive(Clone)]` on a struct that contains `Arc<T>` where the caller might expect an
    isolated copy?
22. Any `Deref` impl on a newtype that is not a smart pointer? Any `Deref` relied on to satisfy
    a trait bound or a `dyn Trait` coercion? Neither one walks the deref chain.
23. Any migration from `std::sync::Mutex` to `parking_lot` or `tokio::sync::Mutex` that relied
    on poison detection?
24. Any unchecked arithmetic on a value derived from untrusted input?
25. Any `Arc<T>` that points back to its parent container?
26. Any function that takes `&'a T` and also writes references into a storage parameter that
    shares the same `'a`? Split the lifetimes, or store owned data.
27. Any `impl<T: ...> PubTrait for T` on a public trait that is not sealed? Seal the trait, or
    write explicit per-type impls.
28. Any `Box::new([T; N])`, or any return of `[T; N]` by value, for `N` over 16 KiB? Use
    `Vec::into_boxed_slice` or `Box::new_uninit_slice`. `into_boxed_slice` may cost a full copy
    when capacity is meaningfully above length; collect into `Box<[T]>` directly when the length
    is exact.
29. Any extension-trait method whose name already exists on the type, or on a type in its deref
    chain? The shadowing is silent, and adding the method to a published trait breaks downstream
    builds with `E0034`.
30. Any `impl From<X> for Y` beside an `impl TryFrom<X> for Y`? The `core` blanket impl makes
    the pair `E0119`, and the choice between them is permanent.

If the answer to any item is yes, revise the change before you merge it.

---

## Related skills

| Skill | Use it for |
|-------|------------|
| `rust-lints` | Workspace lint tables, `clippy.toml`, and lint rollout |
| `rust-unsafe` | `unsafe` review, aliasing rules, and raw pointer handling |
| `rust-panic-safety` | Unwind safety, `catch_unwind`, and abort profiles |
| `rust-performance` | Profiling, benchmarking, and allocation measurement |
| `rust-hot-path` | What to change once a profile names the hot spot: allocation rate, type size, hasher choice, bounds checks |
| `memory-model` | Atomics, orderings, and `loom` |
| `rust-serde` | Types whose encoded form is a contract |
| `rust-code-style` | Module layout, naming, and the rustdoc contract |

For techniques that move a check from run time to compile time — newtype, `#[non_exhaustive]`,
sealed traits, typestate, `const fn` and const generics, compile-time layout assertions — see
[references/type-level-api.md](references/type-level-api.md).
| `rust-async-internals` | Executors, task scheduling, and blocking escapes |
| `rust-crate-architecture` | Crate splits, visibility, and dependency direction |
| `rust-code-style` | Formatting, naming, and rustdoc conventions |
| `uniffi-boundary`, `rust-jni`, `ffi-error-progress-cancel` | FFI contracts and error mapping |
| `rust-security`, `rust-sanitizers-miri` | Advisory triage, Miri, and sanitizers |
