# Persistent collections against `Vec`

Deep material for `rust-copy-on-write`. Read it when clone cost drives the choice of a
collection, or before you add `im`, `imbl`, or `rpds` to `Cargo.toml`.

A persistent collection makes `clone()` free by sharing trie nodes. It charges for that on
every read.

## The cost table

Measured at N = 100 000 `i32` on rustc 1.97.0, edition 2024, aarch64-apple-darwin, release
profile, with the counting allocator in `SKILL.md`. Each time cell is the best and the worst of
nine passes in one run. Allocation counts repeat exactly across runs. Times do not.

| Operation | `Vec` | `im` 15.1.0 | `imbl` 7.0.1 | `rpds` 1.2.1 |
| --- | --- | --- | --- | --- |
| Build, allocations | 16 | 1 594 | 1 619 | 932 349 |
| Build, time | 37-80 us | 0.47-0.53 ms | 0.55-0.64 ms | 23-27 ms |
| Clone, allocations | 1 | 0 | 0 | 0 |
| Clone, time | 4.8-28 us | under 42 ns | under 42 ns | under 42 ns |
| Index `[i]`, whole pass | 6.3-6.5 us | 0.84-1.2 ms | 0.84-1.0 ms | 331-494 us |
| Iterate, whole pass | 6.5-8.5 us | 176-219 us | 192-220 us | 241-289 us |

Three ratios decide the choice:

- **Clone costs nothing.** 0 allocations against 1. Clone time stays under 42 ns for all three,
  against 4.8-28 us for the `Vec`.
- **Indexed reads cost 44x to 140x.** Across five runs `rpds` indexes at 44-52x `Vec`, `im` at
  114-140x, and `imbl` at 133-138x. `rpds` is the cheapest indexer of the three; it is not the
  crate this file tells you to depend on.
- **Iteration costs 27x to 37x.** Iteration is four to five times cheaper than indexing on the
  same collection. It is the only read shape a persistent collection serves well.

Take a persistent collection only when both hold: the clone-to-mutation ratio is high, and the
collection is read by iteration rather than by index. Otherwise keep `Vec` and clone it. A `Vec`
clone is one allocation and one `memcpy`, and 4.8-28 us for 100 000 `i32` is cheaper than the
read penalty on almost any workload.

## The API shape decides the write cost

Both crates give the same guarantee behind two different signatures, and the write cost differs
by a factor of 585.

| Crate | `push_back` signature | Cost per push |
| --- | --- | --- |
| `im`, `imbl` | `&mut self` | In place. Sharing starts at the next `clone()` |
| `rpds` | `&self -> Self` | A fresh trie path, kept version or not |

`rpds` allocates 932 349 times to build 100 000 elements. `im` allocates 1 594 times for the
same work. That is not a defect of the data structure; it is the `&self -> Self` API forcing
persistence on every write. If you only ever keep the newest version, the `&mut self` shape
gives the same guarantee at 1/585 of the allocation count.

Do not benchmark one crate and generalise the result to the other.

```rust
// Cargo.toml: imbl = "7"
fn main() {
    // push_back takes &mut self: it mutates in place until someone holds a clone.
    let mut base: imbl::Vector<i32> = imbl::Vector::new();
    for i in 0..1000 {
        base.push_back(i);
    }

    // clone() is where sharing starts. 0 allocations.
    let mut fork = base.clone();
    fork.push_back(1000);   // copies only the nodes on the path it touches

    assert_eq!(base.len(), 1000);
    assert_eq!(fork.len(), 1001);
}
```

## `rpds::Vector::new()` is not `Send`

`rpds::Vector<T>` defaults to the parameter `P = RcK`, an `Rc`-backed archetype. The failure
appears only when the value first crosses a thread, and the error names a dependency's
internals rather than your type:

```text
error[E0277]: `*const ()` cannot be sent between threads safely
   = help: within `archery::shared_pointer::kind::rc::RcK`, the trait `Send`
           is not implemented for `*const ()`
note: required because it appears within the type `rpds::Vector<i32>`
```

Use `rpds::Vector::new_sync()` for anything that reaches a thread pool or an async runtime.
`rpds::VectorSync<T>` is a type alias for the `Arc`-backed form, so `VectorSync::<T>::new()`
does not exist and gives `error[E0599]: no associated function or constant named `new``.
The constructor is `Vector::new_sync()`.

```rust
// Cargo.toml: rpds = "1.2"
fn main() {
    // Vector::new() gives the Rc archetype: fast, single-thread only.
    let local: rpds::Vector<i32> = rpds::Vector::new().push_back(1);

    // Vector::new_sync() gives the Arc archetype: the only Send + Sync one.
    let shared: rpds::VectorSync<i32> = rpds::Vector::new_sync().push_back(1);
    let fork = shared.push_back(2);   // Theta(log n): reuses nodes outside the changed path
    std::thread::spawn(move || assert_eq!(fork.len(), 2)).join().expect("thread joins");

    assert_eq!(local.len(), 1);
    assert_eq!(shared.len(), 1);      // the fork did not touch it
}
```

`rpds::Vector::clone` is O(1). `push_back` is O(log n), because it creates the
changed trie path and shares the untouched nodes. Do not describe the new
version as sharing every node with the old one.

Pin the property with `fn assert_send_sync<T: Send + Sync>() {}` called on your alias in a
test. The bound then fails at build time, not at the first `tokio::spawn`.

## Do not depend on `im`

`im` is `Arc`-backed and `Send + Sync`, and it carries two open advisories with no fixed
release:

| Advisory | Kind | Detail |
| --- | --- | --- |
| RUSTSEC-2026-0248 | `unmaintained` | Repository archived 2026-05-03. `patched = []` |
| RUSTSEC-2023-0126 | `unsound`, `memory-corruption` | Insertion into `im::OrdSet` violates Rust aliasing rules. Undefined behavior, reachable from safe code. `patched = []` |

RUSTSEC-2020-0096 is patched in `>= 15.1.0` and does not apply to a current pin. The other two
apply to every version.

Depend on `imbl` instead. It is the maintained fork named in RUSTSEC-2026-0248, it has the same
API, it is `Send + Sync`, and the advisory database holds no directory for it. It holds none
for `rpds` either.

Query the directory through the contents API, not through `raw.githubusercontent.com`. The raw
host serves files only, so it answers 404 for every directory path, including the `im`
directory that holds three advisories:

```bash
# 200 means the crate has an advisory directory; 404 means it has none.
# im -> 200, imbl -> 404, rpds -> 404.
curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/rustsec/advisory-db/contents/crates/imbl
curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/rustsec/advisory-db/contents/crates/rpds
```

Make the gate mechanical, not a review habit. Run it against a synced database:

```bash
cargo deny check advisories
```

`rust-security` covers the `deny.toml` policy that turns an `unmaintained` advisory into a
failed build.
