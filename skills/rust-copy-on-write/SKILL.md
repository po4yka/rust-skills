---
name: rust-copy-on-write
description: Use when choosing between borrowed and owned data at an API boundary (Cow<str>, Cow<[T]>, to_mut, into_owned, a Cow struct field), or when clone cost drives a data-structure choice (Arc<str>, Arc<[T]>, the persistent collection crates im, imbl, rpds). Not for an allocation site that a profile already names; use `rust-hot-path`. Triggers on "Cow", "copy-on-write", "borrowed or owned", "borrow or clone", "clone cost", "persistent collection", "immutable data structure", "structural sharing", or "zero-copy string parse".
license: BSD-3-Clause
---

# Rust copy-on-write

Every number below was measured on rustc 1.98.1, edition 2024, aarch64-apple-darwin, release
profile, with the counting allocator in [Measure before you decide](#measure-before-you-decide).
Allocation counts repeat exactly across runs. Times do not; a range is the observed range.
Re-measure on your target.

## Route the decision to a section

| You are about to | Go to |
| --- | --- |
| Return `String` where most calls change nothing | [`Cow` in return position](#cow-in-return-position) |
| Chain two or more string or slice transforms | [`Cow` in argument position](#cow-in-argument-position) |
| Write `cow.to_mut()` in front of a method | [`to_mut()`](#to_mut-is-for-mut-self-methods-only) |
| Put a `Cow` field in a struct, or share a value a cache or a task holds | [A `Cow` field infects the struct](#a-cow-field-infects-the-struct-with-a-lifetime) |
| Write `Cow<'_, String>` or `Cow<'_, Vec<T>>` | [The `Cow` parameter is the borrowed half](#the-cow-parameter-is-the-borrowed-half) |
| Write `impl Borrow<..>`, or debug a `HashMap::get` that misses a present key | [references/borrow-and-toowned.md](references/borrow-and-toowned.md) |
| Write `fn with(&self) -> Self` for a version history | [`Cow` is not structural sharing](#cow-is-not-structural-sharing) |
| Choose between `Vec` and a persistent collection | [Persistent collections](#persistent-collections) |
| Read a profile that already names `__rust_alloc` | The `rust-hot-path` skill, when it is installed: capacity, buffer reuse, `SmallVec` |

## Verify the decision

| Claim | Check | A pass does not prove |
| --- | --- | --- |
| The `Cow` shape saves allocations | The counting allocator below, on real input, with the `Borrowed` path in the run | That callers keep the borrow. Read every call site for `.into_owned()` and `.to_string()` |
| No `Cow` names an owned type | `cargo clippy` (`clippy::owned_cow`) plus the grep in [that section](#the-cow-parameter-is-the-borrowed-half) | Anything about custom `ToOwned` types. Anything about public items, unless `clippy.toml` sets `avoid-breaking-exported-api = false`; the grep covers them |
| No `to_mut()` runs before a `&self` method | The grep in [that section](#to_mut-is-for-mut-self-methods-only), then a read of each hit | That each `to_mut()` sits inside the branch that writes |
| A `Borrow<X>` key finds its entries | A test that compares `hash_one` of the key with `hash_one` of its borrowed form on one `RandomState`, for a key in each letter case that `eq` folds. Then a `get` through the borrowed form | A correct contract, from a `get` test alone: it passes about 1 run in 150 with a broken contract. A lookup through the owned key proves nothing |
| The collection crate's resolved tree is clean | `cargo deny --config deny.toml --locked check advisories` with `unsound = "all"` in `deny.toml`, or `cargo audit --deny warnings`, on the lockfile | A clean tree, if you drop the setting: default cargo-deny misses the transitive `sized-chunks` unsound advisory in an `im` tree, and default `cargo audit` exits 0 on every informational advisory. A failure does not prove that your code reaches the flagged API |

## Measure before you decide

Every rule here is a hit-rate rule. A hit rate is a property of your workload, not of the
type. Put this allocator in a bench binary, run your real input through both shapes, and
compare the counts.

```rust,run
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};

pub static ALLOCS: AtomicUsize = AtomicUsize::new(0);
pub static BYTES: AtomicUsize = AtomicUsize::new(0);

pub struct Counting;

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Ordering::Relaxed);
        BYTES.fetch_add(layout.size(), Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCS.fetch_add(1, Ordering::Relaxed);
        BYTES.fetch_add(new_size, Ordering::Relaxed);
        unsafe { System.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static A: Counting = Counting;

fn main() {
    let (a0, b0) = (ALLOCS.load(Ordering::Relaxed), BYTES.load(Ordering::Relaxed));
    let cap = std::hint::black_box(Vec::<u32>::with_capacity(1000)).capacity();
    let allocs = ALLOCS.load(Ordering::Relaxed) - a0;
    let bytes = BYTES.load(Ordering::Relaxed) - b0;
    println!("allocs={allocs} bytes={bytes}");
    assert_eq!((allocs, bytes, cap), (1, 4000, 1000));
}
```

Run it in release. `dhat` gives the same counts with less code; the `rust-performance` skill
covers it, when it is installed.

## `Cow` in return position

`Cow<'_, str>` pays only on the branch that changes the data. Measured over 1000 path strings
where 5% need a rewrite, generated by
`(0..1000).map(|i| if i % 20 == 0 { format!("path\\{i}") } else { format!("path/{i}") })`.
The lengths sum to 7890 bytes:

| Return shape | Allocations | Bytes |
| --- | --- | --- |
| `String` | 1000 | 7890 |
| `Cow<'_, str>` | 50 | 394 |
| `Cow<'_, str>`, and the caller writes `.into_owned()` | 1000 | 7890 |

The third row is the rule. `Cow` in return position wins **only when the caller can hold the
borrow**. The moment a call site writes `.into_owned()` or `.to_string()`, the count returns
to the `String` figure, and the `Cow` is a branch plus a lifetime parameter for nothing.

```rust,run
use std::borrow::Cow;

fn normalize(path: &str) -> Cow<'_, str> {
    if path.contains('\\') {
        Cow::Owned(path.replace('\\', "/"))
    } else {
        Cow::Borrowed(path)
    }
}

fn main() {
    let inputs = ["a/b", "a\\b"];
    // One allocation over two inputs, not two.
    let total: usize = inputs.iter().map(|p| normalize(p).len()).sum();
    assert_eq!(total, 6);
    // .into_owned() at the call site puts the allocation straight back.
    let owned: Vec<String> = inputs.iter().map(|p| normalize(p).into_owned()).collect();
    assert_eq!(owned.len(), 2);
}
```

`into_owned()` costs 0 allocations on a `Cow::Owned` and 1 on a `Cow::Borrowed`. Call it once
at the boundary where the source buffer dies, not inside the loop that produced the `Cow`.

Two checks before you convert a signature:

- **Measure the branch split.** `Cow` allocates exactly (modification rate x N) times, and
  `String` always N: 0 at 0%, 250 at 25%, 600 at 60%, 1000 at 100%. It saves nothing only at
  100%. The 20x above comes from a 5% rate.
- **Read the call sites.** One `.into_owned()` in the only caller cancels the whole change.

`Cow` is free in size. Measured on aarch64: `&str` 16 bytes, `String` 24, `Cow<'_, str>` 24,
`Cow<'_, [u8]>` 24. Enum layout is an unspecified implementation detail, and Rust 1.97 changed
the layout of some enums. If you depend on the size, assert it in a form that holds on every
target: `const _: () = assert!(size_of::<Cow<'_, str>>() == size_of::<String>());`.

## `Cow` in argument position

A single `Cow` return is a small win. `Cow -> Cow` through a chain is a large one, because
each stage passes its input through untouched instead of re-allocating between stages.
Measured over the same 1000 inputs with three chained stages. The `String` row runs the
same three stages with `fn(&str) -> String` signatures:

| Chain | Allocations | Bytes |
| --- | --- | --- |
| `Cow<'a, str> -> Cow<'a, str>`, 3 stages | 50 | 394 |
| `String -> String`, 3 stages | 3000 | 23670 |

Only `to_slashes` allocates on this input set. The other two stages pass their input
through, so the chain costs what one stage costs. The `String` chain pays 7890 bytes per
stage whether the stage changes anything or not.

```rust,run
use std::borrow::Cow;

// Reborrowing out of an Owned value does not compile, so re-own the tail.
fn strip_dot(s: Cow<'_, str>) -> Cow<'_, str> {
    match s.strip_prefix("./") { Some(r) => Cow::Owned(r.to_string()), None => s }
}

fn to_slashes(s: Cow<'_, str>) -> Cow<'_, str> {
    if s.contains('\\') { Cow::Owned(s.replace('\\', "/")) } else { s }
}

fn drop_trailing(s: Cow<'_, str>) -> Cow<'_, str> {
    if s.ends_with('/') { Cow::Owned(s[..s.len() - 1].to_string()) } else { s }
}

fn main() {
    let clean = drop_trailing(to_slashes(strip_dot(Cow::Borrowed("a/b"))));
    assert!(matches!(clean, Cow::Borrowed("a/b")));   // zero allocations
    assert_eq!(drop_trailing(to_slashes(strip_dot(Cow::Borrowed("a\\b/")))), "a/b");
}
```

Take `Cow<'a, str>` by value in a chain stage. A stage that takes `&Cow<'a, str>` must clone
an `Owned` input only to pass it through, which is the cost the chain exists to avoid.

## `to_mut()` is for `&mut self` methods only

`to_mut()` on a `Cow::Borrowed` clones the borrowed data into an owned value, then returns
`&mut`. A `&self` method called on that `&mut` allocates a second time and drops the first.

This form allocates twice:

```rust,run
use std::borrow::Cow;

fn main() {
    let mut cow: Cow<'_, str> = Cow::Borrowed("cow says moo");
    // to_mut() clones into a String, then str::replace builds a second String
    // and the first is dropped: 2 allocations, 24 bytes.
    let shout = cow.to_mut().replace("moo", "MOO");
    assert_eq!(shout, "cow says MOO");
}
```

This form allocates once. `Deref` reaches `str::replace` with no `to_mut()` at all:

```rust,run
use std::borrow::Cow;

fn main() {
    let cow: Cow<'_, str> = Cow::Borrowed("cow says moo");
    let shout = cow.replace("moo", "MOO");      // 1 allocation, 12 bytes
    assert_eq!(shout, "cow says MOO");
    assert!(matches!(cow, Cow::Borrowed(_)));   // still shareable

    // The second effect: to_mut() flips the value to Owned even when nothing
    // is written. Every later consumer has lost the zero-copy property.
    let mut untouched: Cow<'_, str> = Cow::Borrowed("unchanged");
    let _ = untouched.to_mut();
    assert!(matches!(untouched, Cow::Owned(_)));
}
```

Use `to_mut()` only for a method that takes `&mut self`: `push_str`, `Vec::push`, `sort`.
`to_mut().push_str("!")` on a borrowed 13-byte string costs 2 allocations and 39 bytes:
`to_mut()` allocates 13, then `push_str` reallocates to 26. When you know the final length,
`String::with_capacity(s.len() + 1)` followed by `push_str` and `push` costs 1 allocation and
14 bytes. Keep the call inside the branch that writes, not above it.

`to_mut()` on an already-`Owned` value is free, so a benchmark that starts from `Cow::Owned`
shows no difference and hides both defects. Benchmark the `Borrowed` path.

Grep for the misuse. Every hit needs a check that the method takes `&mut self`:

```bash
rg '\.to_mut\(\)\.' --type rust -n
```

## A `Cow` field infects the struct with a lifetime

`struct Header<'a> { name: Cow<'a, str> }` is a borrowing struct. The lifetime spreads to
every signature that mentions it, exactly like a `&'a mut T` field. The `rust-discipline`
skill, when it is installed, covers lifetime infection in general.

Two failures arrive together:

```rust,compile_fail,E0515,E0521
use std::borrow::Cow;

struct Header<'a> {
    name: Cow<'a, str>,
}

// error[E0515]: cannot return value referencing local variable `raw`
fn build() -> Header<'static> {
    let raw = String::from("content-type");
    Header { name: Cow::Borrowed(&raw) }
}

// error[E0521]: borrowed data escapes outside of function
//   argument requires that `'1` must outlive `'static`
fn store(out: &mut Vec<Header<'static>>, raw: &str) {
    out.push(Header { name: Cow::Borrowed(raw) });
}
```

E0521 is the one that stops the design. Any cache, any `Vec` that outlives the parse buffer,
any value sent to another task needs `Header<'static>`, and a borrowing struct cannot supply
it. The only exit is a hand-written conversion, at one allocation per still-borrowed field:

```rust,run
use std::borrow::Cow;

pub struct Header<'a> {
    pub name: Cow<'a, str>,
    pub value: Cow<'a, str>,
}

impl Header<'_> {
    /// One allocation per borrowed field. Call it where the parse buffer dies.
    pub fn into_static(self) -> Header<'static> {
        Header {
            name: Cow::Owned(self.name.into_owned()),
            value: Cow::Owned(self.value.into_owned()),
        }
    }
}

fn main() {
    let raw = String::from("host: example");
    let (n, v) = raw.split_once(": ").expect("the literal holds the separator");
    let owned = Header { name: Cow::Borrowed(n), value: Cow::Borrowed(v) }.into_static();
    let store: Vec<Header<'static>> = vec![owned];
    drop(raw);
    assert_eq!(store[0].name, "host");
}
```

Add a `Cow` field only when both hold: a real zero-copy parse path exists, and the value dies
inside the borrow scope. Otherwise store `String`, or store `Arc<str>` when many owners share
one immutable value. `Arc<str>` is 16 bytes and 1000 clones cost 0 allocations.

When a shared `'static` value must change now and then without a length change, use
`Arc::make_mut`. It accepts `Arc<str>` and `Arc<[T]>` since 1.81, and `Arc<Path>`, `Arc<OsStr>`,
and `Arc<CStr>` since 1.82. Use `Arc<String>` or `Arc<Vec<T>>` when the length changes. A custom
unsized newtype such as `CiStr` gets E0277, because `CloneToUninit` is unstable (an
`impl CloneToUninit` gets E0658). Share its owned form, such as `Arc<CiString>`, and do not add
a nightly feature gate. The `rust-hot-path` skill, when it is installed, has the table of
`make_mut` cases and the `Weak` detach trap.

## The `Cow` parameter is the borrowed half

`Cow<'a, B>` requires `B: ToOwned`. `String: Clone`, and `alloc` ships
`impl<T: Clone> ToOwned for T`, so `Cow<'_, String>` type-checks. It is legal and useless.
`Cow::Borrowed` then holds `&'a String`. No `&str` coerces into that position, and `Cow::from`
on a `&String` resolves to `Cow<'_, str>` instead: `error[E0308]: mismatched types`, "expected
`Cow<'_, String>`, found `Cow<'_, str>`". Every caller that starts from a string slice must
allocate a `String` first. A caller that already holds a `String` can still write
`Cow::Borrowed(&s)`, and that is the case where the `Cow` buys nothing at all.

Write `Cow<'_, str>`, `Cow<'_, [T]>`, `Cow<'_, Path>`. Do not write `Cow<'_, String>`,
`Cow<'_, Vec<T>>`, or `Cow<'_, PathBuf>`.

`clippy::owned_cow` is warn by default and names the borrowed half for `String`, `Vec<_>`,
`CString`, `OsString`, and `PathBuf`. If `clippy.toml` sets
`avoid-breaking-exported-api = false` (the `rust-lints` default for a crate with no external
consumer), the lint also covers public items. Otherwise it skips them, so grep the public API:

```bash
rg 'Cow<[^>]*(String|Vec<|PathBuf|OsString|CString)' --type rust -n
```

A key whose `Hash` or `Eq` disagrees with its `Borrow` target makes `HashMap::get` miss a
present key, with no error. Read [references/borrow-and-toowned.md](references/borrow-and-toowned.md)
when you write `impl Borrow<..>` or `impl ToOwned`, when a `HashMap::get` misses a key the map
holds, or when E0119 or E0283 appears around `ToOwned`, `borrow()`, `eq`, or `hash`.

## `Cow` is not structural sharing

`Cow` shares one value between one borrower and one owner. It never shares interior nodes.
A `fn with(&self) -> Self` built on `Cow` has the signature of a persistent collection and
the cost of a deep copy, because `Clone` on a `Cow::Owned<[String]>` clones the `Vec` and
every `String` in it.

```rust,run
use std::borrow::Cow;

#[derive(Clone)]
struct Log<'a> {
    lines: Cow<'a, [String]>,
}

impl Log<'_> {
    // Looks persistent. Is not: cloning a Cow::Owned deep-clones every String.
    fn with(&self, line: &str) -> Self {
        let mut next = self.clone();
        next.lines.to_mut().push(line.to_string());
        next
    }
}

fn main() {
    let base = Log { lines: Cow::Owned(vec![String::from("a")]) };
    let next = base.with("b");
    assert_eq!(base.lines.len(), 1);
    assert_eq!(next.lines.len(), 2);
}
```

The cost is exactly quadratic: 2000 chained `with` calls cost 2 004 999 allocations, against
2 010 for a `Vec::push` loop. Do not build a version history or an undo stack on `Cow`.
Benchmark with the production element type: for `T: Copy` the clone is one `memcpy`, so a
`Vec<u32>` toy benchmark passes and the production `Vec<String>` workload does not. Read
[references/persistent-collections.md](references/persistent-collections.md) when you need the
full measurement.

## Persistent collections

A persistent collection makes `clone()` free by sharing trie nodes, and charges for it on every
read. Measured at N = 100 000 `i32`: a clone drops from 1 allocation to 0, an indexed read pass
costs 45x to 89x a `Vec` pass, and an iteration pass costs 22x to 45x.

Take one only when both hold: the clone-to-mutation ratio is high, and the collection is read by
iteration rather than by index. Otherwise keep `Vec` and clone it.

Depend on `imbl = "7.0.2"` or later, not on `im`. `im` is archived and carries an unpatched
soundness advisory. `imbl` 7.0.1 still resolved `imbl-sized-chunks` 0.1, which has a
double-free advisory that 7.0.2 removes from the tree.

Read [references/persistent-collections.md](references/persistent-collections.md) before you
add `im`, `imbl`, or `rpds`, and when you review a change that uses one. It holds the full cost
table, the 585x write-cost split between the `&mut self` and the `&self -> Self` APIs, the
`rpds::Vector::new()` `!Send` trap, the resolved-tree advisory check, and the review checklist.

## When to use none of this

| Situation | Use instead |
| --- | --- |
| The value never changes after construction, and many owners read it | `Arc<str>`, `Arc<[T]>`. Clone is 0 allocations, 16 bytes on the stack |
| One owner mutates, others may hold a stale clone | `Arc::make_mut`, also on `Arc<str>` and `Arc<[T]>` when the length stays fixed |
| The modification rate is above 50% | Plain `String` or `Vec<T>`. The `Cow` saves under half the allocations, and costs a branch and a lifetime parameter |
| The value is indexed in a loop | `Vec<T>`, cloned. 45x to 89x cheaper per read |
| The struct must be `'static` and cross a task boundary | Owned fields. A `Cow` field cannot be `'static` and borrowed at once |

## Review checklist

The [verify table](#verify-the-decision) covers the branch split, the call sites, `to_mut()`,
owned `Cow` parameters, `Borrow` keys, and the advisory gate. Also check:

1. Does a new `Cow` field force a lifetime on a struct that a cache or a task must hold?
   Store owned data, add `into_static`, or share through `Arc`.
2. Does a `fn with(&self) -> Self` clone a `Cow` of a non-`Copy` element type? That is
   quadratic. Use a persistent collection.
3. Is `im`, or an `imbl` older than 7.0.2, in the lockfile? Replace it.
4. Does the change use a persistent collection? Run the checklist in
   [references/persistent-collections.md](references/persistent-collections.md#review-checklist).
