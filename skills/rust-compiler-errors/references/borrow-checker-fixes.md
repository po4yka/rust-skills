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
panic reports `already mutably borrowed: BorrowError` with no indication of which other borrow is
live, so it is expensive to debug in production. See the `rust-debugging` skill.

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

## Related

- [SKILL.md](../SKILL.md) — the triage table and the escalation rule
