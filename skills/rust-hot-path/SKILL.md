---
name: rust-hot-path
description: Use when changing Rust code at a hot spot that a profile or benchmark already names, for example cutting allocations (with_capacity, reserve_exact, clone_from, workhorse buffers, SmallVec, ThinVec, swap_remove), shrinking a type (print-type-sizes, memcpy, large_enum_variant), choosing a hasher (FxHashMap, HashDoS), removing a bounds check, placing inline(always) or cold attributes or a cold path hint, or buffering I/O (BufWriter). Not for choosing or running a profiler; use `rust-performance`. Triggers on "reduce allocations", "too many allocations", "this type is too big", "which hasher".
license: BSD-3-Clause
---

# Rust hot path

What to change in the code after a profile names the hot spot. The `rust-performance` skill
produces the profile and owns benchmark setup; this skill turns the profile into a diff. Apply a
rule here only when a measurement points at it: optimized code is harder to read, so each change
must pay for the readability it spends.

Figures were measured on rustc 1.97.0, aarch64 and x86_64, unless a line names another version.
Std growth policy and layout are unspecified implementation details. Re-measure them on your
toolchain before you depend on an exact figure.

## Route the profile to a section

| The profile shows | Change | Section |
| --- | --- | --- |
| `SipHasher`, `hashbrown` hot | Hasher choice | [Lookups](#lookups) |
| `write`, `read` syscalls dominate | Missing buffering | [I/O](#io) |
| `malloc`, `free`, `__rust_alloc` hot | Allocation rate | [Allocation rate](#allocation-rate) |
| `memcpy` hot with no obvious copy | A type crossed the inline-copy boundary | [type-size-reduction.md](references/type-size-reduction.md#type-size) |
| `memmove` under `Vec::remove` or `Vec::insert` | Each call shifts the tail. Use `swap_remove` when order does not matter, `VecDeque` for a queue, one `retain` for many removals | — |
| `core::panicking::panic_bounds_check` in the disassembly | Bounds checks the compiler could not remove | [inlining-and-codegen.md](references/inlining-and-codegen.md#bounds-checks) |
| A scalar loop where you expected vector code | Bounds checks, or `opt-level` 1, `"s"`, or `"z"` | [inlining-and-codegen.md](references/inlining-and-codegen.md#bounds-checks) |
| Function entry and exit costs, many small calls | Inlining | [inlining-and-codegen.md](references/inlining-and-codegen.md#inlining) |
| Nothing stands out, the work itself is the cost | Algorithm or data structure. Stop here | — |

The last row is the common one. A better algorithm beats every rule below. Reach for this
skill after you accept the algorithm.

## Done when

- The change names a profile, a benchmark delta, or a measured distribution. No number, no merge.
- The metric is stated: allocations per operation, bytes, ns per item, or instructions.
- The measurement came from the shipped profile: non-incremental, at its real `opt-level`, not
  from `dev`.
- A hasher swap states where the keys come from.
- An `unsafe` shortcut such as `get_unchecked` carries a SAFETY comment and a benchmark that
  justifies it.
- A new inline attribute carries a before and after number, because the inliner's budget is
  global and forcing one function in can push a neighbour out. Reject one in review that has none.
- The win has a guard: a `const` size assert, a `dhat` count, or a Criterion baseline.
- Every deliberate special case carries a comment that names its measurement, or the next reader
  simplifies it away. Name the share and the workload, as in
  `// 99% of calls carry 0 or 1 elements (measured 2026-08, ingest benchmark)`.

## Verify and pin the win

Each check proves one claim, and each has a trap that prints a clean result for the wrong reason.

```bash
# A bounds check is gone: the count of checks left in the probe file.
rustc -O --emit asm --crate-type=lib probe.rs -o out.s && grep -c 'panic_bounds_check' out.s

# The layout of a type: discriminant, variants largest first, fields, padding. Nightly only.
# Scoped to one crate; the RUSTFLAGS form dumps every dependency and invalidates the cache.
touch src/lib.rs && cargo +nightly rustc --release -q -- -Zprint-type-sizes

# A dependency function crosses the crate boundary with no attribute: no line names it.
cargo build --release -p dep && nm -g target/release/libdep.rlib | grep '_R'
```

- Mark every probe function `#[inline(never)]`. Without it a small `pub fn` with no caller is
  not emitted at all: the file comes out 54 bytes long, `grep -c` prints 0, and that reads
  exactly like a removed check.
- Keep the `touch`. The dump is a compile-time side effect, not an artifact, so a second run of
  an unchanged crate prints nothing, and that reads exactly like a clean result. Pipe the dump
  through `top-type-sizes` on a real crate to compact it.
- Run the `nm` probe in a non-incremental release build. Incremental and `dev` builds skip the
  inference, so every helper reads as "not inlinable".

An optimization that nothing guards is removed by the next refactor. Pin a type size at compile
time: a mismatch fails the build with E0080. Gate it on one architecture, because sizes differ
per target. `size_of` is in the prelude since Rust 1.80; write `std::mem::size_of` for an older
MSRV.

```rust
pub struct Header { id: u64, flags: u32 }

#[cfg(target_arch = "aarch64")]
const _: () = assert!(std::mem::size_of::<Header>() == 16);
```

Pin an allocation count with a `dhat` test: one heap test per integration test file, each with
its own `#[global_allocator]`, because dhat panics when two profilers run at once and libtest
runs tests in parallel. Read [references/allocation-reduction.md](references/allocation-reduction.md)
when you write the `dhat` test: it holds the test file, the `--test-threads=1` fallback, and
the testing-mode rule. Keep that allocator out of `src/`, because in a library it
replaces the allocator of every binary that links it. Pin a time with a Criterion baseline
through the `rust-performance` skill.

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

On 1M inserts plus lookups, `FxHasher` was 4.7-5.0x faster than SipHash on `u64` keys and
2.2-2.4x on 18-byte string keys. `fnv` is not the middle option its reputation suggests: it
was slower than `FxHasher` on integers and only about 1.2x faster than SipHash on strings.

`FxHashMap` is a type alias for `HashMap` with a different hasher, and std supplies `new` and
`with_capacity` only for `RandomState`, so both fail with E0599. Write `FxHashMap::default()`
or `HashMap::with_capacity_and_hasher(n, FxBuildHasher)`.

Enforce one choice across a workspace with `disallowed-types` in `clippy.toml`. Banning
`std::collections::HashMap` by path does not flag `FxHashMap`, even though the alias is
that type: clippy matches the written path.

Read [references/hashing-and-io.md](references/hashing-and-io.md) when you need the full hasher
measurements, the two-process seeding check, the collision failure mode, the `nohash-hasher`
key rules, or the byte-wise `ByteHash` derives.

## I/O

**File writes are unbuffered.** A `writeln!` to a `File` costs at least one `write` syscall,
and more when the template interpolates. A `BufWriter` took 300,000 lines from about a second
to under ten milliseconds on one local filesystem. The absolute times move with the
filesystem, so re-measure them on yours.

**Locking stdout does not help on its own.** `Stdout` is a `LineWriter`, so it issues one
syscall per newline, lock or no lock. Over 300,000 `println!` calls a `BufWriter` around the
lock cut the time 25x to a terminal and about 50x redirected to a file.

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

Always end a `BufWriter` with an explicit `flush()?`, because a dropped one loses its final
write error and the file ends truncated with nothing in the log. `into_inner()` is not a
substitute: it drains the buffer without flushing the inner writer.

The default buffer is 8 KiB. Use `with_capacity` when one logical record is larger, or a
single record costs several syscalls.

**`BufRead::lines` allocates one `String` per line.** Read with `read_line` into one `String`
that you `clear` each iteration: 201 allocations became 2 on a 200-line file. `read_line` keeps
the line terminator. Remove it with `strip_suffix`, never with `trim_end()`, which also deletes
the trailing spaces and tabs that `lines()` keeps; the loss surfaces later as a parser fault.
Read [references/hashing-and-io.md](references/hashing-and-io.md) when you rewrite a reader: it
holds the byte-exact `strip_eol` helper and the `read_until` trade.

## Allocation rate

**`Vec` does not double from 4.** The first non-zero capacity depends on the element size,
and each growth then doubles. Measured on rustc 1.97.0, it is 8 for 1-byte elements (`Vec<u8>`,
`String`), 4 for 2 to 1024 bytes (`Vec<u32>`, `Vec<u64>`), and 1 above 1024 bytes. Twenty
`push` calls on a `Vec<u32>` therefore cost four allocations and end at capacity 32, with
twelve slots of waste. One `Vec::with_capacity(20)` costs one allocation and no waste.

**`reserve` and `reserve_exact` differ only on a non-empty vector.** `reserve` applies the
amortized policy on top of your request. `reserve_exact` does not.

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
comes from untrusted input; the `rust-panic-safety` skill covers it.

**`clone_from` reuses the destination buffer.** `a = b.clone()` allocates every time.
`a.clone_from(&b)` writes into the buffer `a` already holds.

```rust
let mut dst: Vec<u32> = Vec::with_capacity(99);
let src: Vec<u32> = vec![1, 2, 3];
dst.clone_from(&src);
assert_eq!(dst.capacity(), 99);     // the 99-element buffer survives
```

Copying a three-element `Vec<u32>` onto a reused destination 1000 times cost 1001
allocations through `clone()` and 2 through `clone_from`. The two forms look identical in
review, so the lint is the practical defence: `assigning_clones` is in clippy's `pedantic`
group and is off under a plain `cargo clippy`. `Vec::clone()` also drops the reserve: a
vector of capacity 100 and length 3 clones to capacity 3, so a clone never hands a pre-warmed
buffer to another owner.

**Keep one workhorse buffer.** Declare the buffer outside the loop and `clear` it at the top of
each iteration. `clear` keeps the allocation; assigning a fresh collection throws it away. Do
not call `shrink_to_fit` in such a loop: it reallocates every time, which turns a
zero-allocation loop back into one allocation per iteration. It is a footprint tool, never a
speed tool.

**Make `collect` exact.** A hand-written iterator's default `size_hint` is `(0, None)`, so every
downstream `collect` and `extend` runs the growth ladder: 10,000 items cost 13 allocations
without a hint and 1 with an exact one. The `rust-iterator-impl` skill holds the impl and the
`ExactSizeIterator` contract. An inexact adaptor has the same effect: `(0..1000)` collects at
capacity 1000, and after a `filter` its 500 survivors land at capacity 512 through the whole
ladder. When you know the output length, use `with_capacity` plus `extend`.

**Format into one reused buffer.** `format!` allocates a `String` per call. `write!` into one
cleared buffer. For one integer, call `n.format_into(&mut buf)` on one `core::fmt::NumBuffer`
per integer type (Rust 1.98), declared outside the loop.

Read [references/allocation-reduction.md](references/allocation-reduction.md) when the
allocation is a `HashMap` reserve, a `collect` chain, a zero-filled buffer, an inline-capacity
type such as `SmallVec` or `ArrayVec`, an `Rc`/`Arc` refactor, a formatting loop, or an eager
`ok_or` argument.

## Type size

Read [type-size-reduction.md](references/type-size-reduction.md#type-size) when `memcpy` is hot
with no obvious copy, or a type is instantiated often: it holds the target copy boundaries, the
cache-line threshold, boxing the outsized variant, `ThinVec` and `Box<[T]>`, and the `repr` rule.

## Bounds checks

Read [inlining-and-codegen.md](references/inlining-and-codegen.md#bounds-checks) when the
disassembly shows `panic_bounds_check` or a loop you expected to vectorize stays scalar: it holds
the three safe shapes, `as_chunks`, the `opt-level` rule, and the bar for `get_unchecked`.

## Inlining

Read [inlining-and-codegen.md](references/inlining-and-codegen.md#inlining) when you add, remove,
or review `#[inline]`, `#[inline(always)]`, `#[inline(never)]`, `#[cold]`, or
`core::hint::cold_path()`.

## Related skills

Load these by name when they are installed.

| Skill | For |
| --- | --- |
| `rust-lints` | These rules as lints, and the `clippy.toml` thresholds |
| `rust-discipline` | Signature shape: `&str` and `&[T]` against `&String` and `&Vec<T>`, SemVer hazards |
| `rust-security` | Why a hasher swap is a security decision |
