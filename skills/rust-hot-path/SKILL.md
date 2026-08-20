---
name: rust-hot-path
description: Use when a profiler names a hotspot and you must decide what to change in the code rather than which tool to run. Covers allocation rate (Vec growth, with_capacity, reserve_exact, clone_from, workhorse buffers, format! in a loop), type size (print-type-sizes, the memcpy boundary, boxing a large enum variant, Box<[T]> and ThinVec, repr(C) padding), hasher choice with the HashDoS gate, iterators and size_hint, bounds check removal, inline attributes and cold paths, and buffered I/O. Also covers pinning the win with a const size assert and a dhat allocation test. Triggers on "reduce allocations", "too many allocations", "this type is too big", "large_enum_variant", "which hasher", "FxHashMap", "bounds check", "inline always", "cold path", "BufWriter", "clone_from", "SmallVec", "swap_remove", or any question about what to change once a hot path is known.
license: BSD-3-Clause
---

# Rust hot path

## Purpose

What to change in the code after a profile names the hot spot. The `rust-performance` skill
produces the profile; this skill turns it into a diff.

Every rule here has a cost. Apply one when a measurement points at it, and never as a
style preference. Optimized code is harder to read, so each change must pay for the
readability it spends.

The numbers in this skill were measured on rustc 1.97.0, aarch64 and x86_64. Std growth
policy and layout are unspecified implementation details. Re-measure them on your toolchain
before you depend on an exact figure.

## Route the profile to a section

| The profile shows | Change | Section |
| --- | --- | --- |
| `malloc`, `free`, `__rust_alloc` hot | Allocation rate | [Allocation rate](#allocation-rate) |
| `memcpy` hot with no obvious copy | A type crossed the inline-copy boundary | [Type size](#type-size) |
| `SipHasher`, `hashbrown` hot | Hasher choice | [Lookups](#lookups) |
| `core::panicking::panic_bounds_check` in the disassembly | Bounds checks the compiler could not remove | [Bounds checks](#bounds-checks) |
| `write`, `read` syscalls dominate | Missing buffering | [I/O](#io) |
| Function entry and exit costs, many small calls | Inlining | [Inlining](#inlining) |
| Nothing stands out, the work itself is the cost | Algorithm or data structure. Stop here | — |

The last row is the common one. A better algorithm beats every rule below. Reach for this
skill after you accept the algorithm.

## Allocation rate

### Know the growth ladder

`Vec` does not double from 4. The first non-zero capacity depends on the element size.
Measured on rustc 1.97.0:

| Element size | Capacity ladder |
| --- | --- |
| 1 byte (`Vec<u8>`, `String`) | 0, 8, 16, 32, 64, 128 |
| 2 to 1024 bytes (`Vec<u32>`, `Vec<u64>`) | 0, 4, 8, 16, 32, 64, 128 |
| Over 1024 bytes | 0, 1, 2, 4, 8, 16 |

Twenty `push` calls on a `Vec<u32>` therefore cost four allocations and end at capacity 32,
with twelve slots of waste. One `Vec::with_capacity(20)` costs one allocation and no waste.

### `reserve` and `reserve_exact` differ only on a non-empty vector

`reserve` applies the amortized policy on top of your request. `reserve_exact` does not.

```rust
let mut a: Vec<u32> = vec![1, 2, 3];
a.reserve(1);
assert_eq!(a.capacity(), 6);        // max(requested, 2 * capacity)

let mut b: Vec<u32> = vec![1, 2, 3];
b.reserve_exact(1);
assert_eq!(b.capacity(), 4);        // exactly len + additional
```

On an empty vector both give the exact request, so a test that starts from `Vec::new()`
shows them as identical and hides a 50% overshoot in the real path. Use `reserve_exact`
when you know the final length and you are memory-bound. Use `try_reserve` when the size
comes from untrusted input; see `rust-panic-safety`.

### `clone_from` reuses the destination buffer

`a = b.clone()` allocates every time. `a.clone_from(&b)` writes into the buffer `a`
already holds.

```rust
let mut dst: Vec<u32> = Vec::with_capacity(99);
let src: Vec<u32> = vec![1, 2, 3];
dst.clone_from(&src);
assert_eq!(dst.capacity(), 99);     // the 99-element buffer survives
```

Copying a three-element `Vec<u32>` onto a reused destination 1000 times cost 1001
allocations through `clone()` and 2 through `clone_from`. The two forms look identical in
review, so the lint is the practical defence: `assigning_clones` is in clippy's `pedantic`
group and is off under a plain `cargo clippy`. See `rust-lints`.

`Vec::clone()` also drops the reserve: cloning a vector of capacity 100 and length 3 gives
capacity 3. A clone is never a way to hand a pre-warmed buffer to another owner.

### Keep one workhorse buffer

Declare the collection outside the loop and `clear` it at the end of each iteration.
`clear` keeps the allocation; assigning a fresh collection throws it away.

```rust
fn render_all(items: &[u32]) -> usize {
    let mut buf: Vec<u8> = Vec::with_capacity(256);
    let mut total = 0;
    for item in items {
        buf.clear();                // keeps the 256-byte allocation
        buf.extend_from_slice(&item.to_le_bytes());
        total += buf.len();
    }
    total
}
```

Do not call `shrink_to_fit` in such a loop. It reallocates every time, which converts a
zero-allocation loop back into one allocation per iteration. Whether the buffer also moves
is the allocator's choice. `shrink_to_fit` is a footprint tool, never a speed tool.

### `format!` in a loop allocates per call

`format!` returns a `String`, so each call allocates. `write!` into one reused buffer
instead, and `clear` it each iteration. The macro needs `std::fmt::Write` in scope; without
the import it fails with E0599. To pass a formatted value along without materializing it,
use `format_args!`, which allocates nothing. The loop is in
[references/allocation-reduction.md](references/allocation-reduction.md).

### `BufRead::lines` allocates one `String` per line

Read with `read_line` into one `String` that you `clear` each iteration. A 200-line file
cost 201 allocations through `lines()` and 2 through the loop. `read_line` keeps the line
terminator, so remove it with `strip_suffix`, never with `trim_end()`: `trim_end()` also
deletes the trailing spaces and tabs that `lines()` keeps, and the loss surfaces later as a
parser fault. The loop and the byte-exact `strip_eol` helper are in
[references/hashing-and-io.md](references/hashing-and-io.md).

More allocation patterns, including `HashMap` capacity, `collect` exactness, and the
inline-capacity crates, are in
[references/allocation-reduction.md](references/allocation-reduction.md).

## Type size

A type that is instantiated often is worth shrinking. Two thresholds matter.

**The inline-copy boundary.** Above it, a move or copy becomes a `memcpy` call. It is
target-dependent, and the widely quoted 128 bytes is the x86_64 number only.

| Target | Copies inline up to | First size that calls `memcpy` |
| --- | --- | --- |
| `x86_64-unknown-linux-gnu` | 128 bytes | 129 bytes |
| `aarch64-apple-darwin` | 256 bytes | 257 bytes |

Measure at `-O`. At `opt-level = 0` the boundary drops to 32 bytes on both targets, so a
debug build tells you nothing about the shipped one.

**Cache lines.** A type scanned in a loop wants to fit one 64-byte line. This threshold is
far below the copy boundary and is the one that usually decides a scan-heavy workload.

### Measure the layout, not just the size

`size_of` gives one number. `-Zprint-type-sizes` gives the reason: the discriminant, every
variant sorted largest first, each field in layout order, and every padding run.

```bash
# Nightly only. Scope it to the current crate; the RUSTFLAGS form dumps every
# dependency and invalidates the whole build cache.
touch src/lib.rs && cargo +nightly rustc --release -q -- -Zprint-type-sizes
```

The `touch` matters. The dump is a compile-time side effect, not an artifact, so a second run
of an unchanged crate prints nothing, and that reads exactly like a clean result. Pipe the
output through `top-type-sizes` on a real crate to compact it.

### Box the outsized variant

An enum is as large as its largest variant. Boxing that variant shrinks every value,
including the small ones.

```rust
type Payload = [u8; 100];

enum Message {
    Ping,
    Seq(i32),
    Body(i32, Payload),
}
const _: () = assert!(size_of::<Message>() == 108);
```

```rust
type Payload = [u8; 100];

enum Message {
    Ping,
    Seq(i32),
    Body(Box<(i32, Payload)>),
}
const _: () = assert!(size_of::<Message>() == 16);
```

The trade is one heap allocation whenever the boxed variant is built. It wins when that
variant is rare. Boxing a hot variant trades a size win for an allocation on the common
path and loses. Clippy's `large_enum_variant` suggests this fix, but only when the largest
and second-largest variants differ by more than 200 bytes — it never looks at the total.

### The three-two-one word ladder

| Type | Words | Bytes on 64-bit | Use when |
| --- | --- | --- | --- |
| `Vec<T>` | 3 (ptr, len, cap) | 24 | The collection still grows |
| `Box<[T]>` | 2 (ptr, len) | 16 | The length is final |
| `ThinVec<T>` (`thin-vec` crate) | 1 (ptr) | 8 | The vector is often empty and sits in a hot type |

Build a boxed slice straight from an iterator. Collecting to `Vec` and converting can
reallocate, because `into_boxed_slice` shrinks to fit whenever capacity exceeds length.

```rust
let direct: Box<[u32]> = (0..3u32).collect();       // one exact allocation
assert_eq!(direct.len(), 3);
```

The reverse, `into_vec`, never reallocates.

### `#[repr(C)]` costs you the field reordering

Rust reorders fields to minimize size. `#[repr(C)]` turns that off, which is the point when
a C header defines the layout, and a pure loss when the attribute was added out of habit.

```rust
struct Native { a: u8, b: u64, c: u8 }
#[repr(C)]
struct Abi { a: u8, b: u64, c: u8 }

const _: () = assert!(size_of::<Native>() == 16);
const _: () = assert!(size_of::<Abi>() == 24);      // 50% larger
```

Apply `#[repr(C)]` to types that cross an FFI boundary and to nothing else. See
`rust-unsafe`.

More on measuring and shrinking types, including wrapper sizes and the clippy thresholds,
is in [references/type-size-reduction.md](references/type-size-reduction.md).

## Lookups

The default hasher is SipHash 1-3. It resists collision flooding and it is slow for short
keys. Replacing it is the largest single win available on a hash-heavy workload, and it
removes a security property.

| Keys come from | Hasher | Why |
| --- | --- | --- |
| Anything a caller outside the process controls: headers, query strings, JSON keys, archive entry names | Keep std `RandomState` | The random per-process seed is the HashDoS defence |
| Untrusted keys, and hashing is measured hot | `ahash::RandomState` | Fast and still randomly seeded per process |
| Internal keys: interned symbols, node indices, enum tags | `rustc_hash::FxHashMap` | Fastest measured, unseeded |
| Counters and dense integer ids | `nohash_hasher::IntMap` | Identity hash. Wrong for ids with constant low bits |

Measured on 1M insert plus lookup, rustc 1.97.0 aarch64: `u64` keys took 70-73 ms with
SipHash and 14.8-14.9 ms with `FxHasher`. Eighteen-byte string keys took 143-149 ms against
62-65 ms. `fnv` was slower than `FxHasher` on integers and only level with SipHash on
strings, so it is not the middle option its reputation suggests.

Verify the seeding claim rather than trusting it: `FxHasher` and `FnvHasher` produce
byte-identical output across two processes, while SipHash and `ahash` do not.

`FxHashMap` is a type alias for `HashMap` with a different hasher, and std supplies `new`
and `with_capacity` only for `RandomState`. Both constructors fail with E0599.

```rust
use rustc_hash::{FxBuildHasher, FxHashMap};
use std::collections::HashMap;

let mut empty: FxHashMap<u32, u32> = FxHashMap::default();
let mut sized: HashMap<u32, u32, FxBuildHasher> =
    HashMap::with_capacity_and_hasher(64, FxBuildHasher);
empty.insert(1, 1);
sized.insert(2, 2);
```

Enforce one choice across a workspace with `disallowed-types` in `clippy.toml`. Banning
`std::collections::HashMap` by path does not flag `FxHashMap`, even though the alias is
that type: clippy matches the written path. See `rust-lints`.

The hasher decision, the byte-wise `ByteHash` derives, and the I/O measurements are in
[references/hashing-and-io.md](references/hashing-and-io.md).

## Iterators

**Give a hand-written iterator an exact `size_hint`.** The default is `(0, None)`, so every
downstream `collect` and `extend` falls back to the growth ladder. Collecting 10,000 items
cost 13 allocations without a hint and 1 with an exact one. `rust-iterator-impl` holds the
impl and the `ExactSizeIterator` contract.

**`collect` is exact only when the source length is exact.** `(0..1000).collect::<Vec<_>>()`
lands on capacity 1000. Insert a `filter` and the same chain yields 500 elements at
capacity 512, through the whole ladder. When you know the output length, use
`with_capacity` plus `extend`. The per-adaptor table is in
[references/allocation-reduction.md](references/allocation-reduction.md).

**Do not `collect` to iterate again.** Return `impl Iterator<Item = T>` from the function
instead of `Vec<T>`. On edition 2024 this needs no lifetime bound; RPIT captures in-scope
lifetimes by default. The lint is `needless_collect`, which sits in clippy's `nursery`
group.

**Use `chunks_exact` when the chunk size divides the length.** It hands the compiler a
constant chunk length. The leftover is reached through asymmetric names: `remainder()` on
the shared iterators, `into_remainder()` on the `_mut` ones.

## Bounds checks

An index expression is checked unless the compiler can prove the index is in range. The
check is cheap, and the branch it adds is what blocks vectorization.

Three safe shapes remove it, in order of preference:

1. Iterate. `v.iter().copied().sum()` has no index to check.
2. Reslice first: `let s = &v[..n];`, then index `s` with `0..n`. The length and the loop
   bound are now the same value.
3. `assert!(n <= v.len())` once, ahead of the loop.

Measured on 1.97.0 aarch64 at `-O`, all three removed the check. The naive
`for i in 0..n { t += v[i]; }` kept it. Verify rather than guess:

```bash
rustc -O --emit asm --crate-type=lib probe.rs -o out.s
grep -c 'panic_bounds_check' out.s
```

Mark every probe function `#[inline(never)]`. Without it a small `pub fn` with no caller is
not emitted at all: the file comes out 54 bytes long, `grep -c` prints 0, and that reads
exactly like a removed check.

Reach for `get_unchecked` only when all three shapes fail and a benchmark justifies it. It
is `unsafe` and it needs a SAFETY comment that proves the bound; see `rust-unsafe`. Clippy's
`missing_asserts_for_indexing` finds the sites mechanically, from the `restriction` group.

The four probe functions are in
[references/inlining-and-codegen.md](references/inlining-and-codegen.md).

## Inlining

Four forms, and they are not a strength dial:

| Form | Meaning | Reach for it |
| --- | --- | --- |
| none | The compiler decides | Almost always |
| `#[inline]` | Raises willingness, and permits cross-crate inlining | A large function a profile shows called across a crate boundary |
| `#[inline(always)]` | Effectively a command | One hot call site, after a measurement |
| `#[inline(never)]` | Suppresses it | The cold half of the split below |

**Do not sprinkle `#[inline]` on small public helpers.** On rustc 1.97.0 a non-generic
`pub fn` is inlined into a downstream crate with no attribute and no LTO, as long as it fits
the budget that `-Z cross-crate-inline-threshold` sets, which defaults to 100 MIR cost units.
That budget is not a line count: four independent measurements of a straight-line `u32` body
put the boundary at 15, 49, 50 and 99 statements, because what each statement does decides
its cost. A call or an overflow check costs several units. Measure your own function rather than
counting its lines, and add the attribute only when the profile names it. It is not free:
every downstream crate compiles the body again.

**Inlining is not transitive across a crate boundary.** Inside one crate, an unmarked `g`
is inlined along with the `f` that calls it. Across a boundary a downstream crate receives
only the bodies that are cross-crate-inlinable, so a call to `g` survives inside an inlined
`f` unless `g` carries its own attribute or the build uses LTO. That is the usual reason an
`#[inline(always)]` on a dependency function measures as no change.

**Split when one call site of a large function is hot.** Keep the body in an
`#[inline(always)]` function, and give the cold call sites an `#[inline(never)]` wrapper
around it. They then pay no code bloat. `references/inlining-and-codegen.md` has the
outlining form, which pushes the rare half out instead.

**Mark the rare path `#[cold]`, and pair it with `#[inline(never)]`.** `#[cold]` lowers to
the LLVM `cold` function attribute, which biases branch layout and register allocation away
from that edge. It does not imply `noinline`: measured on 1.97.0, a small `#[cold]` callee
was inlined into its caller whole, and no `cold` attribute survived in the IR at all. The
second attribute is what gets the body out of the hot function.

```rust
#[cold]
#[inline(never)]
fn report_corrupt(offset: usize) -> std::io::Error {
    std::io::Error::other(format!("corrupt record at {offset}"))
}
```

Every inline attribute is a benchmarked change. The inliner's budget is global, so forcing
one function in can push a neighbour out. Reject one in review that arrives with no number.

The cross-crate threshold, the compile-time cost, and the tools that confirm what the
compiler did are in
[references/inlining-and-codegen.md](references/inlining-and-codegen.md).

## I/O

**File writes are unbuffered.** A `writeln!` to a `File` costs at least one `write`
syscall, and more when the template interpolates. Wrapping 300,000 lines in a `BufWriter`
took the loop from roughly a second to under ten milliseconds, two orders of magnitude. The
endpoints move with the filesystem, so re-measure instead of quoting them.

**Locking stdout does not help on its own.** `Stdout` is a `LineWriter`, so it issues one
syscall per newline whether or not you hold the lock. Measured over 300,000 `println!`
calls: 128 ms plain, 133 ms with the lock held, 5.1 ms with a `BufWriter` around the lock.
Block buffering is the whole effect.

```rust
use std::io::{BufWriter, Write};

fn dump(lines: &[&str]) -> std::io::Result<()> {
    let mut out = BufWriter::new(std::io::stdout().lock());
    for line in lines {
        writeln!(out, "{line}")?;
    }
    out.flush()          // dropping a BufWriter discards this error
}
```

Always end a `BufWriter` with an explicit `flush()?`. Drop flushes too, and throws the
error away. `into_inner()` is not a substitute: it drains the buffer without flushing the
inner writer.

The default buffer is 8 KiB. Use `with_capacity` when one logical record is larger, or a
single record costs several syscalls.

## Pin the win

An optimization that nothing guards is removed by the next refactor.

**A type size, at compile time, with no dependency.** `size_of` has been in the prelude
since Rust 1.80, on every edition, so this needs no import. A mismatch fails the build with
E0080. Gate it on one architecture, because sizes differ per target.

```rust
pub struct Header { id: u64, flags: u32 }

#[cfg(target_arch = "aarch64")]
const _: () = assert!(size_of::<Header>() == 16);
```

**An allocation count, at test time.** The `dhat` crate runs on stable. `dhat::assert_eq!`
is not a no-op outside testing mode — it panics — so reach it only under a testing profiler.

```rust,ignore
#[global_allocator]
static ALLOC: dhat::Alloc = dhat::Alloc;

#[test]
fn parse_allocates_once() {
    let _profiler = dhat::Profiler::builder().testing().build();
    let parsed = parse(INPUT);
    let stats = dhat::HeapStats::get();
    dhat::assert_eq!(stats.total_blocks, 1);
    std::hint::black_box(parsed);
}
```

**A comment that names the measurement.** Optimized code has a non-obvious shape. Write
down why, or the next reader simplifies it away. Name the share and the workload, as in
`// 99% of calls carry 0 or 1 elements (measured 2026-08, ingest benchmark), so those two
// cases skip the general path entirely.`

## Review checklist

- The change names a profile, a benchmark delta, or a measured distribution. No number, no merge.
- The metric is stated: allocations per operation, bytes, ns per item, or instructions.
- The measurement came from a release profile, not from `dev`.
- A hasher swap states where the keys come from.
- An `unsafe` shortcut such as `get_unchecked` carries a SAFETY comment and a benchmark that justifies it.
- A new inline attribute carries a before and after number.
- The win has a guard: a `const` size assert, a `dhat` count, or a Criterion baseline.
- Every deliberate special case carries the comment that explains its measurement.

## Related skills

| Skill | For |
| --- | --- |
| `rust-performance` | Producing the profile: flamegraphs, DHAT, Criterion, on-device tooling |
| `rust-iterator-impl` | Writing the `Iterator` impl: `size_hint`, `ExactSizeIterator`, `IntoIterator` |
| `rust-lints` | Turning these rules into lints, and the `clippy.toml` thresholds |
| `rust-discipline` | Allocation and concurrency rules at API-design time |
| `rust-security` | Why a hasher swap is a security decision |
| `rust-unsafe` | `get_unchecked`, SIMD intrinsics, and the `#[repr(C)]` contract |
| `rust-panic-safety` | `try_reserve` for input-driven sizes |
| `rust-test-tools` | Benchmarks and regression gates in CI |
