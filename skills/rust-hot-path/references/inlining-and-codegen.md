# Inlining and codegen inspection

Measured inlining thresholds, the compile-time price of `#[inline]`, the bounds-check probes,
and the commands that show what the compiler did. It serves the Inlining and Bounds checks
sections of `skills/rust-hot-path/SKILL.md`, which give the four attribute forms and the rule
that every attribute needs a number.

All figures come from rustc 1.97.0. The host is `aarch64-apple-darwin` unless the text names
another target.

## Where the inliner actually stops

A crate boundary is the barrier. A codegen-unit boundary inside one crate is not.

| Callee | Build | Symbol left in the caller crate |
| --- | --- | --- |
| 8-statement `pub fn`, no attribute | `lto = false`, `codegen-units = 16` | None. Inlined |
| 60-statement `pub fn`, no attribute | `lto = false`, `codegen-units = 16` | `declare noundef i32 @_RNvCs..._3dep5plain` plus a call |
| 60-statement `pub fn`, `#[inline]` | `lto = false`, `codegen-units = 16` | None. Inlined |
| 60-statement `pub fn`, no attribute | `lto = true` | None. Inlined |
| 60-statement generic `pub fn`, no attribute | `lto = false`, `codegen-units = 16` | None. Inlined |
| 60-statement private `fn` in another module of the same crate | `lto = false`, `codegen-units = 16` | None. Inlined |

Read the table as four rules.

1. A small non-generic `pub fn` crosses a crate boundary with no attribute. The budget is the
   one `-Z cross-crate-inline-threshold` sets, and it defaults to 100 MIR cost units. A
   statement count is not the unit: three measurements of a straight-line `u32` body put the
   boundary anywhere between 15 and 99 statements, because the cost of a statement depends on
   what the statement does. Probe your own function instead of counting its lines.
2. `#[inline]` is the switch that ships the MIR of a large non-generic function to downstream
   crates. Nothing else does, short of LTO.
3. `#[inline]` on a generic function is redundant for this purpose. The downstream crate
   monomorphizes the body itself, so it already holds the MIR.
4. `lto = true` inlines everything the budget allows, regardless of the attribute. Do not add
   `#[inline]` to a crate that only ever builds under fat LTO.

The last row matters when a fix looks like a no-op. Splitting a hot function into two modules of
the same crate does not add a barrier. Moving it into its own crate does.

### Probe one function

A body that fits the budget is instantiated per caller, so it leaves no symbol in its own rlib.
That makes the defining crate alone enough to answer the question:

```bash
cargo build --release -p dep
nm -g target/release/libdep.rlib | grep '_R'
```

No line for the function: the body crosses the boundary already, and `#[inline]` buys nothing.
A line for the function: the body is over the budget, and only `#[inline]` or LTO gets it
across. Run the probe again after each edit to the body.

## The compile-time price of `#[inline]`

`#[inline]` makes every downstream crate compile the body again. It does not make the defining
crate slower: the attribute switches the function to per-caller instantiation, so the defining
crate stops emitting it. A 60-statement `#[inline] pub fn` left no symbol in its own rlib at
all.

Measured on a dependency with 40 `pub fn` of 60 statements each, and one downstream crate that
calls all 40. rustc invoked directly, minimum of 9 runs, `aarch64-apple-darwin`:

| Build | Defining crate | Downstream rebuild |
| --- | --- | --- |
| No attribute | 0.12 s | 0.14 s |
| `#[inline]` on all 40 | 0.10 s | 0.16 s |

That is roughly 1.1x downstream at 40 functions, and 1.6x at 200 functions, where the same
rebuild moved from 0.16 s to 0.26 s. Every downstream crate pays again, so a `#[inline]` in a
utility crate is billed to the whole workspace. Add the attribute to the functions a profile
names, and to nothing else.

## What each attribute becomes

| Rust | LLVM effect | Notes |
| --- | --- | --- |
| `#[inline]` | `inlinehint` on the definition | Raises the budget. Not a command |
| `#[inline(always)]` | Forced inlining | The function usually leaves no symbol |
| `#[inline(never)]` | `noinline` on the definition | Survives as its own symbol |
| `#[cold]` | `cold` on the definition | Also produces call-site branch weights |

**No attribute is transitive.** A caller's attribute never reaches its callees. Verified with
`#[inline(always)] fn f()` that calls `#[inline(never)] fn g()`: `f` disappeared into `main` and
`g` stayed as `_RNvCs..._5trans1g`. If a measurement shows an `#[inline(always)]` changed
nothing, look at the callees first.

## `#[cold]` and the branch weight

`#[cold]` is stable on 1.97.0. It lowers to a function attribute on the definition, not to a
call-site attribute:

```text
attributes #1 = { cold mustprogress nofree norecurse nosync nounwind willreturn memory(none) ... }
```

Note what is not in that set: `#[cold]` does not imply `noinline`. A small cold callee is still
inlined into its caller, so `#[cold]` on its own does not shrink the hot function. Pair it with
`#[inline(never)]` when the point is to get the body out of the caller.

What `#[cold]` does buy is the call-site weight. LLVM derives it at each call site and lays the
cold edge out of line:

```text
!2 = !{!"branch_weights", !"expected", i32 1, i32 2000}
```

So one attribute on the definition biases every caller.

## Show what the compiler did

### LLVM IR is the cheapest check

```bash
# Writes one .ll per codegen unit under target/release/deps/.
touch src/main.rs
cargo rustc --release -p app -- --emit=llvm-ir

# Did the dependency's code survive as a call?
grep -nE '^(declare|define).*_3dep' target/release/deps/app*.ll
```

Read the result with three rules:

| In the caller's IR | Meaning |
| --- | --- |
| No mention of the symbol | The body was inlined |
| `declare ... @<symbol>` plus a `call` | Not inlined. The call crosses the boundary |
| `define internal` or `define hidden ... @<symbol>` | The body was imported or monomorphized here, and a call may still remain. Run `nm` on the linked binary to see whether it survived |

The `touch` is not optional. `cargo rustc` runs the compiler only when the crate is stale. A
second run on an unchanged crate prints `Finished` in 0.00 s and writes no `.ll` at all, which
reads exactly like a clean result.

### Symbols in the linked binary

Faster than IR when you only need a yes or no answer.

```bash
cargo build --release
nm target/release/app | grep '_R'
```

A function that was inlined everywhere leaves no symbol. In the 60-statement test above, `nm`
printed exactly one line for the dependency, and it was the function with no attribute.

**Expect `_R`, not `_ZN`.** rustc 1.97.0 uses the v0 mangling scheme by default. Passing
`-C symbol-mangling-version=v0` is a no-op, and asking for the old scheme now fails:

```text
error: `-C symbol-mangling-version=legacy` requires `-Z unstable-options`
```

Mach-O adds one more leading underscore, so the same symbol reads `__RNv...` from `nm` on macOS
and `_RNv...` on ELF. Grep for `_R` to match both. Any script or profile filter written against
`_ZN` finds nothing.

### Assembly for one function

```bash
cargo install cargo-show-asm
cargo asm --release --lib bounds::sum_sliced      # a function in the library target
cargo asm --release --bin my_bin some::function   # a function in a binary target
```

The crate is `cargo-show-asm`, and the subcommand is `cargo asm`. The names differ, which is the
usual mistake. The older `cargo-asm` crate is a separate unmaintained project.

The target is a flag, never a positional. The two positionals are a name filter and an index, so
`cargo asm --release my_bin bounds::sum_sliced` aborts with `Error: Multiple targets found` in
any crate that has both a library and a binary. Run the command with no function path first; it
lists the matching symbols and you copy one back.

Use Compiler Explorer (godbolt.org) for an isolated snippet. Use `cargo asm` when the answer
depends on the real crate graph and the real profile, which is every cross-crate question.

### Cachegrind tells you the same thing from a run

Linux only. Valgrind has no aarch64-macOS target, so this rule is documented and not measured
here.

```bash
valgrind --tool=cachegrind --cache-sim=no --branch-sim=no ./target/release/app
cg_annotate --auto=yes cachegrind.out.<pid> > annotated.txt
```

In the annotated source, a function was inlined into its callers if and only if its first and
last lines carry no event counts. Body lines carry counts either way, so read the braces, not
the body.

## Prove the change is a win

### Criterion baselines

`--save-baseline` and `--baseline` are Criterion flags, not libtest flags. The default bench
harness parses the argument first and rejects it:

```text
error: Unrecognized option: 'save-baseline'
```

The working setup needs an explicit bench target with the default harness off:

```toml
[[bench]]
name = "hot_path"
harness = false
```

```bash
cargo bench --bench hot_path -- --save-baseline before
# apply the inline attribute
cargo bench --bench hot_path -- --baseline before
```

Name the bench target on the command line. Without `--bench hot_path`, cargo also builds the
libtest bench targets and the same error returns.

### Wall clock is the worst metric available

A small change in memory layout moves wall-clock time by an amount unrelated to the change. The
shift is systematic inside one build, so it repeats on every run: reproducible and wrong.
Criterion reports it as significant at p < 0.05.

Instruction counts and cycle counts have far lower variance. `gungraun` 0.19.4 wires
Valgrind-grade measurement into `cargo bench`. It is the rename of `iai-callgrind`, which is
still published separately at 0.16.1, so pin one name on purpose.

Keep wall clock as the final check that the change helps the product. Gate the pull request on
instruction counts.

## Outlining is the other half of inlining

Inlining pulls a callee in. Outlining pushes a rare path out, so the hot function gets small
enough for the inliner to accept it.

```rust
pub struct Cache {
    entries: Vec<(u32, u32)>,
}

impl Cache {
    // Rare: a miss also re-sorts the table. Out of line, and out of the
    // hot function's inlining budget.
    #[cold]
    #[inline(never)]
    fn insert_slow(&mut self, key: u32) -> u32 {
        let value = key.wrapping_mul(2654435761);
        self.entries.push((key, value));
        self.entries.sort_unstable_by_key(|e| e.0);
        value
    }

    pub fn get(&mut self, key: u32) -> u32 {
        match self.entries.binary_search_by_key(&key, |e| e.0) {
            Ok(i) => self.entries[i].1,
            Err(_) => self.insert_slow(key),
        }
    }
}
```

## Special-case the sizes that dominate

When small inputs dominate, handle 0, 1 and 2 elements ahead of the general loop. The general
loop then never pays for its own setup on the common call.

Measure the distribution first. Guessing it is how a special case ends up slower than the loop
it replaced. Count the arms in a debug build or behind a feature:

```rust
#[cfg(debug_assertions)]
use std::sync::atomic::{AtomicU64, Ordering};

#[cfg(debug_assertions)]
static ARMS: [AtomicU64; 4] = [
    AtomicU64::new(0),
    AtomicU64::new(0),
    AtomicU64::new(0),
    AtomicU64::new(0),
];

pub fn total(values: &[u32]) -> u32 {
    #[cfg(debug_assertions)]
    ARMS[values.len().min(3)].fetch_add(1, Ordering::Relaxed);
    values.iter().sum()
}
```

The gate is the point. Without it the `atomicrmw` survives `-O`, and the counter costs one
atomic read-modify-write on every call in release.

Run the real workload, print the four counts, and keep the special case only for the arms that
carry the traffic. Write the measured share into a comment next to the match, as SKILL.md
requires.

## When inlining is not the answer

A loop that the compiler will not vectorize does not get faster from an attribute. Reach for
`core::arch`, which is stable and works in `no_std`. Baseline features of the target need no
nightly and no `#[target_feature]`. Verified on stable 1.97.0, aarch64:

```rust
#[cfg(target_arch = "aarch64")]
pub fn splat_seven() -> [u8; 16] {
    let mut out = [0u8; 16];
    // SAFETY: both intrinsics are baseline NEON on every aarch64 target,
    // and out holds the 16 bytes vst1q_u8 writes.
    unsafe {
        let v = core::arch::aarch64::vdupq_n_u8(7);
        core::arch::aarch64::vst1q_u8(out.as_mut_ptr(), v);
    }
    out
}
```

Two traps sit on the path past that point.

**A non-baseline feature needs the attribute at every level.** Enabling the feature in the build
configuration does not remove the requirement. The compiler says so:

```rust,compile_fail
#[target_feature(enable = "dotprod")]
pub fn dot(a: u32) -> u32 {
    a
}

// error[E0133]: call to function `dot` with `#[target_feature]` is unsafe
//   = note: the dotprod target feature being enabled in the build
//     configuration does not remove the requirement to list it in
//     `#[target_feature]`
pub fn caller(a: u32) -> u32 {
    dot(a)
}
```

Mark the caller with the same `#[target_feature]`, or call it from an `unsafe` block that a
runtime `is_aarch64_feature_detected!` guard protects.

**Portable SIMD is still nightly.** `std::simd` needs a feature gate, and the gate fails on
stable with E0554:

```rust,ignore
#![feature(portable_simd)]      // error[E0554]: `#![feature]` may not be used
                                // on the stable release channel
use std::simd::u8x16;
```

Write the intrinsics per architecture behind `#[cfg(target_arch = ...)]`, and keep a plain scalar
fallback for every other target.

## Bounds checks: probe the assembly, do not guess

An index expression is checked unless the compiler can prove the index is in range. The check
is cheap; the branch it adds is what blocks vectorization. Compile one file to assembly and
count the panic call:

```bash
rustc -O --emit asm --crate-type=lib probe.rs -o out.s
grep -c 'panic_bounds_check' out.s
```

Mark every probe function `#[inline(never)]`. A small non-generic `pub fn` with no caller is
never emitted at `-O`, because it fits the cross-crate-inline budget above and is instantiated
per caller instead. The naive probe below then produces a 54-byte file that holds two
directives, and `grep -c` prints 0. That reads exactly like a removed bounds check. With
`#[inline(never)]` the same source emits the body and `grep -c` prints 1.

Measured on 1.97.0, aarch64-apple-darwin, each function compiled alone with
`#[inline(never)]`: `naive` printed 1, and the three shapes below printed 0.

```rust
// Keeps the check: the loop bound and the length are unrelated values.
#[inline(never)]
pub fn naive(v: &[u32], n: usize) -> u32 {
    let mut t = 0;
    for i in 0..n { t += v[i]; }
    t
}

// 1. Reslice first, so the length and the loop bound are the same value.
#[inline(never)]
pub fn resliced(v: &[u32], n: usize) -> u32 {
    let s = &v[..n];
    let mut t = 0;
    for i in 0..n { t += s[i]; }
    t
}

// 2. Assert the range once, ahead of the loop.
#[inline(never)]
pub fn asserted(v: &[u32], n: usize) -> u32 {
    assert!(n <= v.len());
    let mut t = 0;
    for i in 0..n { t += v[i]; }
    t
}

// 3. Iterate. Preferred: no index exists to check.
#[inline(never)]
pub fn iterated(v: &[u32]) -> u32 {
    v.iter().copied().sum()
}
```

Reach for `get_unchecked` only when all three shapes fail and a benchmark justifies it. It is
`unsafe` and it needs a SAFETY comment that proves the bound; see `rust-unsafe`. Clippy's
`missing_asserts_for_indexing` finds the sites mechanically. It is in the `restriction` group,
so it is off under every default.

## Triage

| Symptom | Cause | Fix |
| --- | --- | --- |
| A bounds-check probe finds nothing, and the function is small | The `pub fn` was never emitted | Add `#[inline(never)]` to the probe |
| `#[inline(always)]` measured as no change | The attribute is not transitive; the callee still stands | Mark the callee too, and confirm with `nm` |
| A dependency function shows in a profile after a refactor | The code moved into its own crate, and the body is over the threshold | Add `#[inline]`, or turn on LTO |
| Adding `#[inline]` made no difference at all | The build already uses `lto = true` | Remove the attribute and keep the compile time |
| `cargo rustc -- --emit=llvm-ir` writes no `.ll` | The crate was fresh, so rustc never ran | `touch` a source file and repeat |
| A grep for `_ZN` in a profile finds nothing | v0 mangling is the default on 1.97.0 | Grep `_R`, and allow the extra Mach-O underscore |
| `cargo bench -- --save-baseline x` fails with `Unrecognized option` | The libtest harness parsed the flag | Add `[[bench]] harness = false` and pass `--bench <name>` |
| A benchmark shows a large, repeatable, unexplainable win | Wall clock moved with the code layout | Re-measure with instruction counts |
| `cargo asm` is not a command | The installed crate is `cargo-asm`, not `cargo-show-asm` | `cargo install cargo-show-asm` |
