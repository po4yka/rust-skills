---
name: rust-discipline
description: Use when designing or reviewing Rust API shape (pub signatures, trait bounds, blanket and sealed impls, newtypes, Drop or RAII guards), or when method resolution or trait coherence fails (method ambiguity, autoderef, UFCS, E0034, E0119 blanket impl overlap, E0117 orphan rule). Also use for a pre-merge review of such a diff and its semver hazards.
license: BSD-3-Clause
---

# Rust Discipline

Review rules for Rust API shape: `pub` and `pub(crate)` signatures, struct definitions, trait
bounds, and trait impls. Each rule targets a defect that compiles and then breaks a caller, a
downstream crate, or a later release. Apply the rules to every changed signature in the diff.

| Severity | Meaning |
|----------|---------|
| CRITICAL | Blocks the merge. The defect is silent, or it breaks downstream code and a release cannot undo it. |
| WARNING  | Fix it, or write a one-line justification in the diff. |

## Verify

| Claim | Check | What a green result does not prove |
|-------|-------|------------------------------------|
| No lint regression | `cargo clippy --all-targets --locked -- -D warnings` | Clippy denies `derived_hash_with_manual_eq` by default. It does not see two manual `Hash` and `PartialEq` impls that disagree. |
| A public API change keeps SemVer | `cargo semver-checks check-release` on a published crate, if it is installed. Pass `--baseline-rev <rev>` for an unpublished one. | Measured with cargo-semver-checks 0.50.0 on rustc 1.98.1: it flags a new variant on an exhaustive enum, a new `#[non_exhaustive]`, a new `pub` field on a literal-constructible struct, and a lost `Send` or `Sync`. It does not flag `&str` changed to `impl AsRef<str>`, a new blanket impl on a public trait, or a new provided trait method whose name can collide (E0034). Review those three by hand. |
| A bound accepts every promised caller | A test that passes each caller shape the API promises. For a `for<'a>` bound, pass the function or method path itself. | Only the shapes the test passes. |
| A hash key keeps the `Eq`/`Hash` contract | A test that inserts through one form and looks up through the other | Only the forms the test uses. |

cargo-semver-checks reads rustdoc JSON, whose format changes between rustc releases; 0.50.0 needs
Rust 1.93 or later. Update the tool when a new stable rustc arrives. The `rust-crate-release` skill owns the version-bump decision.

## References

Open a reference only when the diff matches its row.

| Reference | Read it when the diff |
|-----------|-----------------------|
| [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md) | adds a trait impl, a newtype, a lifetime parameter, or a blanket impl on a public trait |
| [`references/trait-resolution.md`](references/trait-resolution.md) | adds a `Deref` impl, an extension trait, a `downcast_ref` chain, a pointer-forwarding impl, a blanket impl, a second conversion impl on one type pair, or a foreign trait impl on a wrapper type |
| [`references/data-shape-traps.md`](references/data-shape-traps.md) | adds a hash key or an `Ord` impl, reverses or truncates text, or builds a large array for the heap |
| [`references/argument-shapes.md`](references/argument-shapes.md) | picks a parameter, callback, or return shape on a `pub` signature, or makes a concrete parameter generic |
| [`references/drop-and-raii.md`](references/drop-and-raii.md) | adds a `Drop` impl, a guard type, or cleanup that must survive a panic |
| [`references/type-level-api.md`](references/type-level-api.md) | adds a newtype, a sealed trait, a typestate, a `#[non_exhaustive]` type, or a `const` generic |
| [`references/review-checklist.md`](references/review-checklist.md) | is under a review request or a merge gate that asks for a full pass |

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

Take a generic `<P: AsRef<Path>>` only when call-site convenience matters more than one body per
argument type, and keep the body in a private concrete function. A published reference parameter
(`&str`, `&Path`, `&[T]`) that becomes generic breaks every caller that coerces the function to a
`fn(&T)` pointer (E0308) or passes it to an `Fn(&T)` bound (`implementation of 'Fn' is not general
enough`): a type parameter cannot stand for a higher-ranked reference. See
[`references/argument-shapes.md`](references/argument-shapes.md).

Find violations:

```bash
rg ':\s*&(String|Vec<|PathBuf)\b' --type rust -n
```

Two exceptions are real. Keep `&String` or `&Vec<T>` when the body calls `capacity()` or another
allocation-state method that no slice exposes, or when the function compares container identity.
See
[`references/argument-shapes.md`](references/argument-shapes.md#when-string-and-vect-are-correct).

Keep an iterator's extra reference out of a public bound. `items.iter().find(pred)` under
`F: Fn(&T) -> bool` fails with `E0277: expected an 'FnMut(&&T)' closure, found 'F'`, because
`Iterator::find` passes `&Self::Item` and `Item` is already `&T`. Widening the bound to
`Fn(&&T) -> bool` pins `&&T` into the API for ever. Re-borrow in the body:
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

Each closure expression has its own anonymous type, so a `Vec<F>` cannot hold closures from two
expressions, and `impl Fn` in a field fails with `E0562`. Store `Box<dyn Fn(..)>`.
`Box<dyn FnMut(..)>` needs a unique borrow at the call, so `publish(&self)` fails with `E0596` and
must become `&mut self`, which propagates to every caller and blocks sharing the owner behind an
`Arc`. Require `Fn`, and put the mutation inside the callback's own `Cell` or `Mutex`.

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

**Severity: CRITICAL** on a published type; WARNING inside one crate.

A `&'a mut H` field infects every use site with the lifetime `'a`. You then cannot store the
struct in another struct, you cannot return it from a function, and `Vec<Processor<'_>>` is
impossible. This is **lifetime infection**.

```rust
trait Handler {}

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
ships, and generate the impls with a macro. In a recursive method, take `&mut W` with
`W: Handler + ?Sized`, not `impl Handler` by value: that form passes `cargo check` and fails
`cargo build` at the recursion limit. Read
[`references/trait-resolution.md`](references/trait-resolution.md) when you add a forwarding impl.

Find candidates, then check each hit for a `&'_ mut` field:

```bash
rg "struct .+<'.+>\s*\{" --type rust -n
```

### Use HRTB for callbacks that must not keep the reference

**Severity: WARNING**

`for<'a> Fn(&'a T) -> R`, where `R` does not depend on `'a`, is the correct shape for a
callback that may keep the return value but not the reference. The `for<'a>` bound stops the
callback from storing `&'a T`. The callback must extract owned data and return it.

- When the callback must not keep the argument reference, write `for<'a>` explicitly. A callback
  that stashes the reference then fails with `error[E0521]: borrowed data escapes outside of
  closure`. The same closure under a fixed `'a` bound is accepted with no diagnostic at all, so
  E0521 shows the bound is correct. Do not widen the lifetime to clear it.
- When the callback returns a borrow of its argument, write `for<'a> Fn(&'a T) -> &'a K` with
  `K: ?Sized`. Do not add a trait or a GAT for it.
- A closure's body, not `move`, decides whether it implements `Fn`, `FnMut`, or `FnOnce`. `move`
  changes only the capture mode. Declare a callback method's lifetime on the method, or elide it:
  an `impl<'a>` lifetime fails a `for<'x>` bound when the caller passes the method path.

Read [`references/argument-shapes.md`](references/argument-shapes.md#callback-bounds-past-the-plain-borrow)
when you pick a callable bound, pass a method path to a `for<'a>` bound, or need a callback output
that stays a type parameter over `'a`. The `rust-callback-bounds` skill holds the full acceptance
table for callable bounds and fields.

---

## Panics and error returns

This section is the catalog's single home for the `unwrap` and `expect` rule.

- Use `.unwrap()` in tests and `examples/` only. In other code, propagate with `?`.
- Use `.expect("<invariant>")` in non-test code only for a real invariant. The message states
  what must be true: `"config validated at startup"`, `"sender held for process lifetime"`.
  `"should never fail"` states a wish, not an invariant.
- State the lock-poisoning policy at every `lock()`. Write `.expect("<name> mutex poisoned")`
  when a panic under the lock must also stop the next user. Write
  `.unwrap_or_else(PoisonError::into_inner)` when the data stays valid after a panic mid-update.
  A bare `.lock().unwrap()` hides the choice. Read
  [`references/type-and-trait-traps.md`](references/type-and-trait-traps.md#parking_lot-and-tokio-mutexes-do-not-poison-on-panic)
  when you pick the policy, or before you migrate to a `parking_lot` or `tokio::sync` mutex,
  which do not poison.
- Give `panic!`, `unreachable!`, and `todo!` a reason:
  `unreachable!("step kind {kind:?} filtered earlier")`. Use them only for cases the code makes
  impossible.
- Return `Result` from a library path that can fail. Do not build control flow on an expected
  panic.
- Enforce the `unwrap` half. Set `unwrap_used` in `[lints.clippy]` and
  `allow-unwrap-in-tests = true` in `clippy.toml`. That key exempts only `#[test]` and
  `#[cfg(test)]` code, so add `#![expect(clippy::unwrap_used, reason = "example")]` to each
  `examples/` file that calls `.unwrap()`. The `rust-lints` skill holds the rollout.

The `rust-code-style` skill, when it is installed, owns the choice of error type (`thiserror` in a
library, `anyhow` in a binary). Use one error convention per dependency chain: one shared error
type, or one enum per crate that the caller translates. Do not mix the two. The
`rust-panic-safety` skill owns panic strategy, `catch_unwind`, and every panic that can reach an
FFI boundary. The `ffi-error-progress-cancel` skill owns the boundary error type.

## Drop and RAII

- Prefer `std::os::fd::OwnedFd` and `OwnedSocket` over a raw `i32`. A raw descriptor leaks on
  every error path that does not call `close()`.
- Struct fields drop in declaration order, after the `Drop::drop` body. When you implement `Drop`
  on a cleanup-critical type, document the order and each dependency between fields.
- `impl Drop` blocks every move of a non-`Copy` field out of the struct (E0509). Put `Drop` on a
  one-field guard that holds an `Option`, and keep the aggregate `Drop`-free.
- Use `scopeguard::defer!` for cleanup that must run on every exit path, including unwinding.
  Under `panic = "abort"` no destructor runs after a panic.
- Never argue soundness from a guard's `Drop`. `mem::forget` is safe, so a caller can skip it.

[`references/drop-and-raii.md`](references/drop-and-raii.md) has the seven error codes that
`impl Drop` turns on, the escape hatches, and the guard example.

## Match exhaustiveness

- **No `_ =>` wildcard on a crate-private enum.** A wildcard absorbs a new variant silently. List
  every arm, and join arms with identical handling as `A | B =>`. Enforce it with
  `#![warn(clippy::wildcard_enum_match_arm)]` (restriction group) on the modules that match local
  enums. The lint also fires on a foreign `#[non_exhaustive]` enum such as `io::ErrorKind`, where
  `_` is required, so put `#[expect(clippy::wildcard_enum_match_arm, reason = "...")]` on those
  matches.
- Mark a public enum that downstream code matches `#[non_exhaustive]` in its first release.
  Adding the attribute later is a breaking change.
- `if let`, `let else`, and `while let` are fine for single-variant extraction.
- **A `downcast_ref` chain is a match with the exhaustiveness check removed.** A new implementor
  compiles, no lint fires, and the chain skips it. When the set of types is closed and the code
  needs the concrete data, use an enum; the same gap then fails with `E0004` and names the
  variant. See [`references/trait-resolution.md`](references/trait-resolution.md).

## Locks and condition variables

- Document the lock order at the struct level with a `// Lock order: a -> b -> c` comment.
  Every nested acquisition follows that order.
- `parking_lot` locks are no larger than `std::sync` locks, but not automatically faster. Measure
  contention before you switch, or before you pick `RwLock` over `Mutex`.
- **Wait on a `Condvar` only through a predicate.** A `Condvar` keeps no count, so a bare `wait`
  blocks for ever when the notify arrives first. Call
  `cv.wait_while(lock.lock().expect("queue mutex poisoned"), |n| *n == 0)`, which checks the
  predicate under the lock before it sleeps and after every wake. Measured with a worker that
  notifies 200 ms before the waiter starts: the bare form hangs and `timeout 3` kills it with
  exit 124; `wait_while` exits 0. The predicate reads only state that the same mutex protects.

A blocking-lock guard (`std::sync::Mutex` or `RwLock`, or a `parking_lot` lock) held across
`.await` makes the future `!Send` and can deadlock the executor. `clippy::await_holding_lock`
finds them. The `rust-async-internals` skill owns that rule, the blocking-work table, and `rayon`
next to async code.

## Lint suppression

Reject a new `#[allow]` where `#[expect(lint, reason = "...")]` works, and any suppression of a
`clippy::correctness` or `clippy::suspicious` finding. The `rust-lints` skill, when it is
installed, owns the suppression order, the `priority = -1` rule, and `clippy.toml`. The
`rust-security` skill owns `deny.toml` exceptions.

---

## Review checklist

For a review request or a merge gate, run
[`references/review-checklist.md`](references/review-checklist.md): 33 questions in four groups.
For one changed signature, apply the API design group only. If an answer is yes, revise the
change before you merge it.

## Topics other skills own

Route these topics by skill name, when the skill is installed.

| Topic | Skill |
|-------|-------|
| Allocation, type size, hasher choice, and `SmallVec` sizing on a profiled hot path | `rust-hot-path` |
| Profiling, benchmarks, and allocation measurement | `rust-performance` |
| Atomic orderings, the ordering comment that names the data it publishes, `update`/`try_update`, and when to write a `loom` test | `memory-model`; `loom` setup in `rust-test-tools` |
| Blocking work in async code, locks across `.await`, executors | `rust-async-internals` |
| `unsafe` review, `// SAFETY:` comments, and the unsafe lint gate | `rust-unsafe` |
| Panics at an FFI boundary, `catch_unwind`, and abort profiles | `rust-panic-safety` |
| FFI contracts and error mapping | `uniffi-boundary`, `rust-jni`, `ffi-error-progress-cancel` |
| Which bound accepts which closure, and callable fields | `rust-callback-bounds` |
| Type-keyed stores and the `'static` bound of `Any` | `rust-type-erasure` |
| Handler sets that each need `&mut` to one state object | `rust-event-loop-state` |
| Lifetime coercion and variance as a breaking change | `rust-variance` |
| Types whose encoded form is a contract | `rust-serde` |
| Module layout, naming, visibility, and formatting | `rust-code-style` |
| Crate splits and dependency direction | `rust-crate-architecture` |
| Workspace lint tables and `clippy.toml` | `rust-lints` |
| Advisory triage, `deny.toml`, Miri, and sanitizers | `rust-security`, `rust-sanitizers-miri` |
| SemVer bump and publish decisions | `rust-crate-release` |
