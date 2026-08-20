---
name: rust-discipline
description: Use when you author or review pub and pub(crate) signatures, struct definitions, and trait bounds, during code review or a pre-merge self-check, or when you tighten existing Rust code. Covers Rust code discipline for API design, anti-patterns, error propagation, RAII and Drop, hot-path allocation, concurrency primitives, atomic ordering, unsafe encapsulation, FFI panic containment, and lint non-regression. Triggers on method ambiguity, autoderef, UFCS, E0034, trait coherence, or blanket impl overlap.
license: BSD-3-Clause
---

# Rust Discipline

## Purpose

Catch high-signal Rust mistakes before they land. Apply these rules to public (`pub`) and
crate-public (`pub(crate)`) function signatures, struct definitions, and trait bounds.

Use it when you author or change a signature, when you review a diff, and when you tighten code
before a merge. Apply every rule to every changed signature, not only to the first one.

Each rule carries a severity:

| Severity | Meaning |
|----------|---------|
| CRITICAL | Blocks the merge. The defect is silent, or it breaks downstream code. |
| WARNING  | Fix it, or write a one-line justification in the diff. |

Deep material lives in the reference files. Open one when the diff matches its row.

| Reference | Read it when the diff adds |
|-----------|----------------------------|
| [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md) | a trait impl, a `Drop` impl, a newtype, or a lifetime parameter |
| [`references/trait-resolution.md`](references/trait-resolution.md) | a `Deref` impl, an extension trait, a `downcast_ref` chain, a pointer-forwarding impl, a blanket impl, or a second conversion impl on one type pair |
| [`references/data-shape-traps.md`](references/data-shape-traps.md) | a hash key, a text reversal, or a large array |
| [`references/argument-shapes.md`](references/argument-shapes.md) | a parameter or return shape on a `pub` signature |
| [`references/drop-and-raii.md`](references/drop-and-raii.md) | a `Drop` impl, a guard type, or cleanup that must survive a panic |
| [`references/type-level-api.md`](references/type-level-api.md) | a newtype, a sealed trait, a typestate, or a `const` generic |
| [`references/review-checklist.md`](references/review-checklist.md) | any change you are about to merge; it is the 31-question pre-merge pass |

---

## API design

### Accept borrowed args, not owned references

**Severity: WARNING**

Accept `&str`, `&[T]`, and `&Path` instead of `&String`, `&Vec<T>`, and `&PathBuf`. The
owned-reference shapes force the caller to hold an allocation, even when the caller has a
slice. The borrowed shapes accept both.

```rust
// BAD: forces the caller to have a String.
fn log(msg: &String) {}
```

```rust
// GOOD: accepts &str, String, Arc<str>, Cow<str>, and more.
fn log(msg: &str) {}
```

For generic inputs, prefer `fn open(path: impl AsRef<std::path::Path>)` over a concrete `&Path`.

Find violations:

```bash
rg ':\s*&(String|Vec<|PathBuf)\b' --type rust -n
```

One exception is real. Keep `&String` or `&Vec<T>` when the body calls `capacity()`, or another
allocation-state method that no slice exposes. See
[`references/argument-shapes.md`](references/argument-shapes.md#when-string-and-vect-are-correct).

Keep an iterator's extra reference out of a public bound. `items.iter().find(pred)` under
`F: Fn(&T) -> bool` fails with `E0277: expected a 'FnMut(&&T)' closure`, because `Iterator::find`
passes `&Self::Item` and `Item` is already `&T`. Widening the bound to `Fn(&&T) -> bool` pins
`&&T` into the API for ever. Re-borrow in the body: `items.iter().find(|item| pred(item))`.

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

Each closure expression has one unique anonymous type. Multiple evaluations of
the same expression have that type, so a `Vec<F>` can hold those instances. It
cannot hold values from different closure expressions without type erasure, and
`impl Fn` in a field fails with `E0562`. The stored form is `Box<dyn Fn(..)>`.
`Box<dyn FnMut(..)>` needs a unique borrow at the call, so `publish(&self)` fails
with `E0596` and must become `&mut self`, which propagates to every caller and
blocks sharing the owner behind an `Arc`. Require `Fn`, and put the mutation
inside the callback's own `Cell` or `Mutex`.

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
parameter to the owner, and do not store `Weak` callbacks to dodge it. A `Weak` registration dies
when the caller releases its `Arc`: measured at 1 entry held, 0 callbacks fired, no diagnostic.

### Do not store `&'a mut H` in a struct field

**Severity: CRITICAL**

A `&'a mut H` field infects every use site with the lifetime `'a`. You then cannot store the
struct in another struct, you cannot return it from a function, and `Vec<Processor<'_>>` is
impossible. This is **lifetime infection**.

```rust
// BAD: lifetime infection
struct Processor<'a> {
    handler: &'a mut dyn Handler,
}
```

Take a generic `H` instead, and add one forwarding impl per pointer the caller may pass. Write
`+ ?Sized` on every one of them. Without it the impl carries an implicit `H: Sized` and excludes
`dyn Handler`, which is the only case the pattern exists to serve; the call site then fails with
`error[E0277]: the trait bound '&mut dyn Handler: Handler' is not satisfied`.

```rust
struct Request;
trait Handler { fn handle(&mut self, r: Request); }
struct Processor<H: Handler> { handler: H }

// `+ ?Sized` admits `dyn Handler`. `H::handle(self, ..)` names the inner impl;
// `self.handle(..)` here resolves back to this impl and overflows the stack.
impl<H: Handler + ?Sized> Handler for &mut H {
    fn handle(&mut self, r: Request) { H::handle(self, r) }
}
impl<H: Handler + ?Sized> Handler for Box<H> {
    fn handle(&mut self, r: Request) { H::handle(self, r) }
}

// Both instantiations exist, and neither carries a lifetime parameter.
fn use_both(_a: Processor<Box<dyn Handler>>, _b: Processor<&mut dyn Handler>) {}
```

The method receiver decides which pointers can forward at all, and a bridge blanket impl
`impl<T: Other> Handler for T` makes every forwarding impl `E0119`. Settle both before the trait
ships, and generate the impls with a macro; see
[`references/trait-resolution.md`](references/trait-resolution.md).

Find candidates, then check each hit for a `&'_ mut` field:

```bash
rg "struct .+<'.+>\s*\{" --type rust -n
```

### Use HRTB for callbacks that must not keep the reference

**Severity: WARNING**

`for<'a> Fn(&'a T) -> R`, where `R` does not depend on `'a`, is the correct shape for a
callback that may keep the return value but not the reference. The `for<'a>` bound stops the
callback from storing `&'a T`. The callback must extract owned data and return it.

Rules:

- When the callback must not keep the argument reference, write `for<'a>` explicitly. A callback
  that stashes the reference then fails with `error[E0521]: borrowed data escapes outside of
  closure`. The same closure under a fixed `'a` bound is accepted with no diagnostic at all, so
  E0521 shows the bound is correct. Do not widen the lifetime to clear it.
- When the callback is a trait whose output borrows from the argument — a projection that returns
  a slice of the input — use a GAT (`type Out<'a>`), not a lifetime parameter on the trait. A
  `where for<'a> K: Proj<'a, T>` bound silently forces `T: 'static`; rustc says so in a note,
  `due to a current limitation of the type system, this implies a 'static lifetime`. The GAT form
  carries no such bound. The two shapes are not interchangeable.
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
  message needs allocation or formatting. `with_context(|| format!(...))` does not allocate
  the formatted message on the success path; it calls the closure only for `Err`. The closure
  captures variables when it is created, so do not clone an owned capture before the call
  unless ownership requires it.
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
  Measure both before you switch. `parking_lot` locks still do not poison. Add `parking_lot`
  only after you measure contention.
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

A Rust panic that reaches a non-unwind ABI aborts the process on Rust 1.81 and later;
before 1.81 it is undefined behavior. Either way the host runtime reports a native crash
and the panic message is lost. See `rust-panic-safety` for the rules.

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

Apply [`references/review-checklist.md`](references/review-checklist.md) to every changed `pub`
or `pub(crate)` API, and to every Rust pull request. It carries 31 questions in five groups: API
design, panics and resources, performance and concurrency, unsafe and FFI, and trait and
type-system traps. If the answer to any item is yes, revise the change before you merge it.

---

## Related skills

| Skill | Use it for |
|-------|------------|
| `rust-lints` | Workspace lint tables, `clippy.toml`, and lint rollout |
| `rust-unsafe` | `unsafe` review, aliasing rules, and raw pointer handling |
| `rust-panic-safety` | Unwind safety, `catch_unwind`, and abort profiles |
| `rust-performance` | Profiling, benchmarking, and allocation measurement |
| `rust-hot-path` | What to change once a profile names the hot spot: allocation rate, type size, hasher choice, bounds checks |
| `rust-callback-bounds` | Which bound accepts which closure, `for<'a> Fn(&'a T) -> &'a K`, and the cost of a generic `F` field against `Box<dyn Fn>` |
| `rust-type-erasure` | When a type-keyed store beats an enum, and how to key values that are not `'static` |
| `rust-event-loop-state` | Who owns the handler set and who owns the state when every handler needs `&mut` to one object |
| `rust-variance` | Whether a lifetime coercion is allowed, and why added interior mutability is a breaking change |
| `memory-model` | Atomics, orderings, and `loom` |
| `rust-serde` | Types whose encoded form is a contract |
| `rust-code-style` | Module layout, naming, the rustdoc contract, and formatting |
| `rust-async-internals` | Executors, task scheduling, and blocking escapes |
| `rust-crate-architecture` | Crate splits, visibility, and dependency direction |
| `uniffi-boundary`, `rust-jni`, `ffi-error-progress-cancel` | FFI contracts and error mapping |
| `rust-security`, `rust-sanitizers-miri` | Advisory triage, Miri, and sanitizers |
