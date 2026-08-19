# Borrow checker fix catalogue

Worked fixes for the errors in [SKILL.md](../SKILL.md). Every fix compiles on rustc 1.97.
Each entry states the fix and what it costs, because several of these trade a build error for a
run-time cost.

## Disjoint access to one collection

The compiler tracks borrows per place, not per element. It cannot prove `v[0]` and `v[1]` are
different places, so two `&mut` into one `Vec` are rejected even when the indices differ.

```rust
// Split at an index. The two halves are disjoint by construction.
pub fn add_first_to_second(v: &mut [i32]) {
    let (left, right) = v.split_at_mut(1);
    left[0] += right[0];
}

// Several disjoint indices at once. Returns Err(GetDisjointMutError) on a
// duplicate or out-of-range index.
pub fn swap_three(v: &mut [i32]) -> Option<()> {
    let [a, b, c] = v.get_disjoint_mut([0, 2, 4]).ok()?;
    *a += *b + *c;
    Some(())
}

// Iterate and mutate every element. No index, no bounds check.
pub fn double_all(v: &mut [i32]) {
    for slot in v.iter_mut() {
        *slot *= 2;
    }
}

// Two named fields of one struct. Field borrows are already disjoint.
pub struct Pair {
    pub left: Vec<i32>,
    pub right: Vec<i32>,
}

pub fn drain_into(pair: &mut Pair) {
    // Borrowing two distinct fields of the same struct is allowed.
    pair.left.append(&mut pair.right);
}
```

`get_disjoint_mut` is stable since Rust 1.86. Before that the same job needed `split_at_mut`
twice, or an index-and-copy pass.

## A read borrow that blocks a write

```rust
// Rejected: `first` is live across the push.
// let first = &v[0];
// v.push(1);
// println!("{first}");

// Fix 1: copy the value out. The borrow ends at the semicolon.
pub fn copy_out(v: &mut Vec<i32>) {
    let first = v[0];
    v.push(first);
}

// Fix 2: scope the borrow, when the value is not Copy.
pub fn scoped(v: &mut Vec<String>) {
    let first = {
        let borrowed = &v[0];
        borrowed.len()
    };
    v.push(first.to_string());
}

// Fix 3: collect the decisions first, then apply them.
pub fn retain_matching(v: &mut Vec<String>, needle: &str) {
    let keep: Vec<bool> = v.iter().map(|s| s.contains(needle)).collect();
    let mut index = 0;
    v.retain(|_| {
        let decision = keep[index];
        index += 1;
        decision
    });
}
```

Fix 3 has a name: compute the plan under a shared borrow, then execute it under an exclusive
borrow. It is the general answer whenever the read informs the write. `retain` alone is shorter
when the predicate needs no outside state.

## A method that needs `&mut self` while reading `&self`

This is the most common E0499 in application code:

```rust
pub struct Cache {
    entries: Vec<String>,
    hits: usize,
}

impl Cache {
    // Rejected: `self.lookup(..)` borrows all of `self`, and `self.hits += 1`
    // needs it exclusively at the same time.
    //
    // pub fn get(&mut self, key: &str) -> Option<&String> {
    //     let found = self.lookup(key)?;
    //     self.hits += 1;
    //     Some(found)
    // }

    // Fix: work on the fields, not on `self`. Field borrows are disjoint.
    pub fn get(&mut self, key: &str) -> Option<&String> {
        let found = self.entries.iter().position(|e| e == key)?;
        self.hits += 1;
        Some(&self.entries[found])
    }

    fn lookup(&self, key: &str) -> Option<&String> {
        self.entries.iter().find(|e| *e == key)
    }
}
```

A private helper that takes `&self` forces a whole-struct borrow. Free functions that take the
fields, or code written against the fields directly, keep the borrows apart. This is why a large
struct with many `&mut self` methods eventually fights the borrow checker: every method borrows
everything.

## Getting an owned value out of a `&mut`

```rust
#[derive(Default)]
pub struct Job {
    pub name: String,
    pub payload: Option<Vec<u8>>,
}

// Leaves an empty String behind. No allocation, no clone.
pub fn take_name(job: &mut Job) -> String {
    std::mem::take(&mut job.name)
}

// Leaves a chosen value behind, and returns the old one.
pub fn rename(job: &mut Job, next: String) -> String {
    std::mem::replace(&mut job.name, next)
}

// The Option case. Leaves None behind.
pub fn take_payload(job: &mut Job) -> Option<Vec<u8>> {
    job.payload.take()
}

// Swap two places without a temporary owner.
pub fn swap(a: &mut Job, b: &mut Job) {
    std::mem::swap(a, b);
}
```

`mem::take` requires `Default`. `mem::replace` does not, which is why it works for a type with no
sensible empty value.

## A borrow that must cross a thread

`thread::spawn` requires `'static`, so no borrow of a local can enter it.

```rust
use std::sync::Arc;

// Rejected: the closure outlives the borrow.
// pub fn f(data: &Vec<i32>) {
//     std::thread::spawn(move || println!("{data:?}"));
// }

// Fix 1: share ownership. One allocation, cheap clones.
pub fn shared(data: Arc<Vec<i32>>) {
    let handle = Arc::clone(&data);
    std::thread::spawn(move || println!("{handle:?}"));
}

// Fix 2: a scoped thread. The borrow is allowed because the scope joins
// every thread before it returns.
pub fn scoped(data: &Vec<i32>) {
    std::thread::scope(|s| {
        s.spawn(|| println!("{data:?}"));
    });
}
```

`thread::scope` is stable since Rust 1.63. Prefer it when the work is bounded and the caller can
wait. Use `Arc` when the thread must outlive the calling frame.

Never answer E0521 with `Box::leak`. It compiles and the allocation is never reclaimed; the
process grows once per call.

## Interior mutability, and its cost

Reach for these only after the splits above fail.

| Type | Check | Failure mode | Use when |
| --- | --- | --- | --- |
| `Cell<T>` | none, `T: Copy` | none | A small `Copy` field, single thread |
| `RefCell<T>` | run time | panics on conflict | A graph shape the compiler cannot verify, single thread |
| `Mutex<T>` | run time | blocks, or deadlocks | Shared write access across threads |
| `RwLock<T>` | run time | writer starvation | Many readers, rare writers |
| `AtomicUsize` and friends | none | none | A counter or a flag |

```rust
use std::cell::RefCell;

pub struct Graph {
    nodes: Vec<RefCell<Node>>,
}

pub struct Node {
    pub visited: bool,
}

impl Graph {
    // The borrow lives only inside this call, so the panic window is small.
    pub fn mark(&self, index: usize) {
        self.nodes[index].borrow_mut().visited = true;
    }
}
```

Keep every `borrow_mut` short and never hold one across a call that might re-enter. A `RefCell`
panic reports `RefCell already borrowed` from `borrow_mut`, or `RefCell already mutably borrowed`
from `borrow`. Neither text names the other live borrow, so it is expensive to debug in
production. See the `rust-debugging` skill.

For the thread-safe types, see the `memory-model` skill for ordering and the
`rust-async-internals` skill for holding a guard across an `.await`.

## Lifetime annotation shapes

```rust
// One input, one output. The lifetime is inferred; do not write it.
pub fn first_word(s: &str) -> &str {
    s.split_whitespace().next().unwrap_or("")
}

// Two inputs, one output. The compiler cannot guess, so state the source.
pub fn longer<'a>(a: &'a str, b: &'a str) -> &'a str {
    if a.len() >= b.len() { a } else { b }
}

// The output borrows from one input only. Say which, and free the other.
pub fn prefix_of<'a>(text: &'a str, _sep: &str) -> &'a str {
    text.split('=').next().unwrap_or(text)
}

// A struct that borrows. It cannot outlive `source`.
pub struct View<'a> {
    pub source: &'a [u8],
}

impl<'a> View<'a> {
    pub fn head(&self) -> &'a [u8] {
        &self.source[..self.source.len().min(4)]
    }
}
```

The third shape matters: tying the output to both inputs when only one is the source forces the
caller to keep the other alive for no reason. Write the narrowest lifetime that is true.

## Drop and the borrow checker

Adding `impl Drop` to a type is a change to its borrow rules. Four errors follow, and no error
title names `Drop`.

### E0597: dropck extends the borrow to the drop point

Without a `Drop` impl the compiler knows destruction cannot read `'a`. With one, `drop(&mut self)`
could read the reference, so the borrow must last until the value is dropped. Locals drop in
reverse declaration order, so a guard declared before its source now fails.

```rust,compile_fail
struct NoDrop<'a>(&'a i32);
struct WithDrop<'a>(&'a i32);
impl Drop for WithDrop<'_> {
    fn drop(&mut self) {}
}

fn ok() {
    let d;
    let x = 5;
    d = NoDrop(&x);      // compiles
    let _ = d.0;
}

fn bad() {
    let d;
    let x = 5;
    d = WithDrop(&x);    // E0597: `x` does not live long enough
    let _ = d.0;
}
```

The note reads "borrow might be used here, when `d` is dropped and runs the `Drop` code for type
`WithDrop`", followed by "values in a scope are dropped in the opposite order they are defined".
Declare the borrowed local before the guard, or keep the type `Drop`-free.

### E0507: `drop` holds `&mut self`, so a field pattern moves

`if let Some(h) = self.0` inside `drop` fails with "cannot move out of `self` as enum variant
`Some` which is behind a mutable reference" for every payload that is not `Copy`. rustc suggests
`&self.0`, which gives a `&Handle` when you usually want `&mut`. Match on `self` instead: `self`
is already a reference, so default binding modes make every binding a reference.

```rust
pub struct Handle;
impl Handle {
    pub fn report(&self, _reason: &str) {}
}

pub struct Guard(Option<Handle>);

impl Drop for Guard {
    fn drop(&mut self) {
        // `if let Some(h) = self.0` is E0507. Match on `self`; `h` binds as `&mut Handle`.
        let Self(Some(h)) = self else { return };
        h.report("unused");
    }
}
```

Take ownership with `self.0.take()` or `std::mem::replace` when the cleanup must consume the
payload.

### E0509: a `Drop` impl blocks every partial move

```rust,compile_fail
struct Inner(String);
struct Outer {
    inner: Inner,
}
impl Drop for Outer {
    fn drop(&mut self) {}
}

// E0509: cannot move out of type `Outer`, which implements the `Drop` trait
fn take(o: Outer) -> Inner {
    o.inner
}
```

Drop glue runs on the whole value, so it cannot run on a value with a hole in it. Make the field
an `Option<Inner>` and call `.take()` in both `take` and `drop`, or wrap the field in
`std::mem::ManuallyDrop` and read it out with `unsafe { ManuallyDrop::take(..) }`.

### E0184 and E0367: the two `Drop` impl rules

`#[derive(Copy)]` plus `impl Drop` reports "the trait `Copy` cannot be implemented for this type;
the type has a destructor". A bitwise copy plus a destructor is a double free by construction, so
a resource handle is never `Copy`. Remove the derive.

`impl<T: Clone> Drop for Foo<T>` where the struct is `struct Foo<T>(T)` reports E0367, "`Drop` impl
requires `T: Clone` but the struct it is implemented for does not", with "note: the implementor
must specify the same requirement". Drop glue must exist for every instantiation, so the impl may
not apply to only some of them. Move the bound onto the struct definition:

```rust
pub struct Bar<T: Clone>(pub T);
impl<T: Clone> Drop for Bar<T> {
    fn drop(&mut self) {}
}
```

## E0631: a function item is not a coercion site

```text
error[E0631]: type mismatch in function arguments
    = note: expected function signature `fn(&String) -> _`
               found function signature `fn(&str) -> _`
help: consider wrapping the function in a closure
```

Deref coercion runs at an expression, not at a trait bound. With `v: Vec<String>` and `fn
count_words(s: &str)`, the call `count_words(&v[0])` compiles because `&String` coerces to `&str`
at that call. `v.iter().map(count_words)` fails, because `Iterator::map` demands
`F: FnMut(&String) -> B` and rustc matches the function item's signature against that bound
exactly.

```rust
fn count_words(s: &str) -> usize {
    s.split_whitespace().count()
}

pub fn totals(v: &[String]) -> (usize, usize) {
    let closure: usize = v.iter().map(|s| count_words(s)).sum();
    let adapter: usize = v.iter().map(String::as_str).map(count_words).sum();
    (closure, adapter)
}
```

Inside a closure body the call is an expression again, so the coercion applies. The rule holds for
`Option::map`, `Result::map_err`, and every other higher-order call.

## Adding lifetimes to a callback bound is a dead end

A `Fn(&T) -> K` parameter that fails to compile produces three errors in sequence. Each `help:` is
locally correct, and the third wall cannot be climbed.

| Step | Error | The `help:` rustc prints |
| --- | --- | --- |
| 1 | E0309: the parameter type `T` may not live long enough | consider adding an explicit lifetime bound: `T: 'a` |
| 2 | E0621: explicit lifetime required in the type of `arr` | add explicit lifetime `'a` to the type of `arr` |
| 3 | E0502: cannot borrow `*arr` as mutable because it is also borrowed as immutable | none |

```rust,compile_fail
// Terminal state of the "just add lifetimes" path.
fn sort_by_key<'a, T: 'a, K: Ord>(arr: &'a mut [T], mut key: impl FnMut(&'a T) -> K) {
    for i in 0..arr.len() {
        for j in (i + 1)..arr.len() {
            if key(&arr[j]) < key(&arr[i]) {
                arr.swap(i, j);   // E0502
            }
        }
    }
}
```

The E0502 note reads "argument requires that `arr[_]` is borrowed for `'a`". A fixed `'a` in
`impl FnMut(&'a T) -> K` makes every call hand the callback a borrow that lives for the whole
`'a`, which outlives the loop body, so the body can never mutate the slice. Delete every `'a`.
The elided lifetime in `impl FnMut(&T) -> K` is higher-ranked, and that is the form that compiles:

```rust
pub fn sort_by_key<T, K: Ord>(arr: &mut [T], mut key: impl FnMut(&T) -> K) {
    for i in 0..arr.len() {
        for j in (i + 1)..arr.len() {
            if key(&arr[j]) < key(&arr[i]) {
                arr.swap(i, j);
            }
        }
    }
}
```

`impl FnMut(&T) -> impl Ord` is not an escape either: it reports E0562, "`impl Trait` is not
allowed in the return type of `Fn` trait bounds". Name the generic parameter, as `K` above. See
the `rust-callback-bounds` skill for the case where `K` must borrow from `T`.

## Related

- [SKILL.md](../SKILL.md) — the triage table and the escalation rule
