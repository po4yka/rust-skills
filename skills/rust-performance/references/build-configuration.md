# Build configuration for runtime speed

Reference for `skills/rust-performance/SKILL.md`. It holds the build knobs that change how fast the
shipped binary runs: where Cargo reads settings from, `opt-level`, `target-cpu`, profile-guided
optimization, and the global allocator. Profile tables and the LTO trade-off are in SKILL.md section 8.
Compile-time tuning is in [build-time-optimization.md](build-time-optimization.md).

Every figure below was measured on rustc 1.97.0, host `aarch64-apple-darwin` (`apple-m4`), unless the
text names another target.

---

## 1. Where the settings are read

Get this wrong and every later measurement is noise.

### `[profile.*]` is read only from the workspace root

A profile table in a workspace member, or in a dependency, is discarded. For a workspace member, Cargo
prints one warning and builds anyway. For a dependency, Cargo prints nothing at all. A path dependency
that asks for `opt-level = 1` still received `-C opt-level=3`, with no diagnostic on the build output.
The workspace-member warning reads:

```text
warning: profiles for the non root package will be ignored, specify profiles at the workspace root:
package:   /path/to/workspace/member/Cargo.toml
workspace: /path/to/workspace/Cargo.toml
```

A library crate cannot ship optimization settings to its consumers. Put the settings in the workspace
root manifest and document them for downstream users.

### `RUSTFLAGS` in the environment replaces the config file

Cargo does not merge across rustflags levels. One level wins and the others are dropped whole. Verified
with `cargo build --release -v` against this `.cargo/config.toml`:

```toml
[build]
rustflags = ["-C", "target-cpu=native"]
```

| Command | Flags rustc received |
| --- | --- |
| `cargo build --release` | `-C target-cpu=native` |
| `RUSTFLAGS="-C force-frame-pointers=yes" cargo build --release` | `-C force-frame-pointers=yes` only |

`[target.<triple>] rustflags` replaces `[build] rustflags` the same way. With both tables present, a
build received only the `[target.aarch64-apple-darwin]` entry, with and without an explicit `--target`.

Precedence, highest first: the `RUSTFLAGS` environment variable, then the `[target.*]` tables, then
`[build] rustflags`.

Inside the `[target.*]` level, entries do join. Cargo concatenates the matching `[target.<triple>]`
table and every matching `[target.'cfg(...)']` table. With the three tables below, rustc received
`-C target-cpu=native` and `-C force-frame-pointers=yes` together, and lost `-C debug-assertions=yes`:

```toml
[build]
rustflags = ["-C", "debug-assertions=yes"]

[target.aarch64-apple-darwin]
rustflags = ["-C", "target-cpu=native"]

[target.'cfg(target_os = "macos")']
rustflags = ["-C", "force-frame-pointers=yes"]
```

Setting `RUSTFLAGS` on that same config dropped both target tables.

This bites the profiling workflow. SKILL.md section 2 asks for `-C force-frame-pointers=yes`. Put it in
`[build] rustflags`, then add a `target-cpu` entry in any `[target.*]` table, and the frame-pointer
flag disappears. The flamegraph goes back to truncated stacks with no error. Keep all rustflags at one
level.

### `lto = false` is not `lto = "off"`

Thin-local LTO is the implicit default for any build with `opt-level > 0`. `lto = false` stops only the
cross-crate part. Verified with `cargo build --release -v`:

| `Cargo.toml` | Flags rustc received |
| --- | --- |
| `lto = false` | `-C embed-bitcode=no` |
| `lto = "off"` | `-C embed-bitcode=no -C lto=off` |

Anyone who benchmarks "LTO on against LTO off" by flipping `false` and `"thin"` compares thin-local LTO
against thin LTO. Use `lto = "off"` for the true baseline.

---

## 2. opt-level

`rustc -C help` states the range: `optimization level (0-3, s, or z; default: 0)`.

Cargo requires bare integers for the numeric levels; only `s` and `z` are quoted. `opt-level = 3` is
accepted. `opt-level = "3"` fails the manifest parse:

```text
error: must be `0`, `1`, `2`, `3`, `s` or `z`, but found the string: "3"
```

### Measure size on `__text`, not on the file

A Mach-O binary is page-padded, so whole-file byte counts move in steps and can invert the answer.

Measured on one program (`HashMap` plus sort plus `format!`), built with `panic = "abort"`,
`strip = true`, `codegen-units = 1`, an isolated target directory, `aarch64-apple-darwin`:

| opt-level | `__text` bytes | File bytes |
| --- | --- | --- |
| 3 | 224,292 | 358,336 |
| 2 | 223,512 | 358,336 |
| 1 | 223,424 | 358,400 |
| `"s"` | 223,136 | 358,400 |
| `"z"` | 222,364 | 358,432 |

The two columns disagree. Here `"z"` holds the smallest code section and the largest file. The file
column moves 96 bytes of padding across the five levels; `__text` moves 1,928 bytes of real code. Read
`__text` with `size -m <binary>` on macOS, or use `cargo bloat`.

The whole spread is under 1 percent of the code section, and a size level can still cost throughput.
Build the ship profile at `3`, at `"s"` and at `"z"`, then pick from your own numbers.

### `s` and `z` turn off loop vectorization

Count the vector operations in the emitted assembly. On aarch64 the vector operand suffixes are `.4s`,
`.2d`, `.16b` and `.8h`:

```bash
rustc -C opt-level=3 -C codegen-units=1 --edition 2024 \
  --emit asm --crate-type=lib src/lib.rs -o out.s
grep -cE '\.4s|\.2d|\.16b|\.8h' out.s
```

A plain accumulate loop over `&[u32]`, `aarch64-apple-darwin`:

| opt-level | Vector ops |
| --- | --- |
| 0 | 0 |
| 1 | 0 |
| 2 | 15 |
| 3 | 15 |
| `s` | 0 |
| `z` | 0 |

`"s"` gave the same result as `"z"` here, so re-measure any claim that `"s"` keeps the vectorizer. This
is the mechanism behind the warning in SKILL.md section 8: size levels can cost throughput outright.

### The assembly check needs `#[inline(never)]`

At `opt-level >= 2` a small non-generic `pub fn` in a `--crate-type=lib` is not emitted into the
assembly at all. It is left as an inline candidate. The output file came out at 54 bytes holding only
`.build_version` and `.subsections_via_symbols`, which reads exactly like "the loop disappeared".
`-C codegen-units=1` does not change it.

Mark the function under test before you read its assembly:

```rust
#[inline(never)]
pub fn accumulate(v: &[u32]) -> u32 {
    let mut t = 0u32;
    for x in v {
        t = t.wrapping_add(*x);
    }
    t
}
```

The same trap hits the `panic_bounds_check` grep in `rust-hot-path`.

---

## 3. target-cpu

`-C target-cpu` raises the instruction-set baseline the compiler may use.

```bash
RUSTFLAGS="-C target-cpu=native" cargo build --release
```

`native` resolves to the host processor. `rustc --print target-cpus` names it on the first line: on
this machine, `native - Select the CPU of the current host (currently apple-m4).`

### Prove that it did something

Diff the cfg set. The flagged run must gain `target_feature` lines:

```bash
diff <(rustc --print cfg) <(rustc --print cfg -C target-cpu=native)
```

On this host the flagged run gained `target_feature="bf16"`, `target_feature="bti"` and
`target_feature="i8mm"`. An empty diff means the flag did nothing; name the features explicitly with
`-C target-feature=+<name>` instead.

### It is not a harmless no-op under `--target`

Two measured failure modes, both silent:

| Command | Result |
| --- | --- |
| `rustc --print cfg --target aarch64-linux-android -C target-cpu=native` | 31 `target_feature` lines, against 1 without the flag. The host's `apple-m4` features are applied to the Android build. |
| `rustc --print cfg --target x86_64-unknown-linux-gnu -C target-cpu=native` | `'apple-m4' is not a recognized processor for this target (ignoring processor)`, and `target_feature="fxsr"` drops out of the baseline set |

The first row is the dangerous one. Cross-compiling to Android from an Apple Silicon host with
`target-cpu=native` produces a library that assumes CPU features the phone does not have. It compiles,
it links, it ships, and it faults with an illegal instruction on the device.

Rules:

- Use `target-cpu=native` only for a binary that runs on the machine that built it: local benchmarks,
  or a service on fixed self-hosted hardware.
- Never put `target-cpu=native` under `[build] rustflags` in a repository that cross-compiles.
- For a distributed artifact, name a baseline instead. On x86_64 the levels are `x86-64` (the default),
  `x86-64-v2`, `x86-64-v3` and `x86-64-v4`. List the choices with
  `rustc --print target-cpus --target <triple>`.
- Re-run the cfg diff after any container or toolchain change. It is a two-second check.

---

## 4. Profile-guided optimization

`-C profile-generate` and `-C profile-use` are stable. Both appear in `rustc -C help` on 1.97.0.

The model is two passes: build instrumented, run on representative input, rebuild with the merged
profile.

```bash
# 1. Instrumented build. --target keeps build scripts out of the profile; see below.
RUSTFLAGS="-Cprofile-generate=$PWD/pgo-data" \
  cargo build --release --target aarch64-apple-darwin

# 2. Run the representative workload. Each process writes one .profraw file.
./target/aarch64-apple-darwin/release/myapp --input real-workload.bin

# 3. Merge. llvm-profdata comes from `rustup component add llvm-tools-preview`,
#    or from `xcrun llvm-profdata` on macOS.
xcrun llvm-profdata merge -o merged.profdata pgo-data

# 4. Optimized build.
RUSTFLAGS="-Cprofile-use=$PWD/merged.profdata" \
  cargo build --release --target aarch64-apple-darwin
```

### Two silent traps

**A `.profraw` passed to `-C profile-use` is a warning, not an error.** The build succeeds and applies
no PGO at all:

```text
warning: pgo-data/default_14157245456489944735_0.profraw: invalid instrumentation profile data (bad magic)
```

A missing file is a hard error, so only the un-merged case is silent. Grep the build output for
`bad magic` before you believe a PGO number.

**Without `--target`, the instrumented build also instruments build scripts.** Cargo passes `RUSTFLAGS`
to host artifacts when no target triple is given. Measured on a crate with a trivial `build.rs`: one
`.profraw` file appeared in the profile directory after the build and before the program ran at all,
and a second after the run. With `--target <host triple>` the count after the build was zero. Build
script data in the merge distorts the profile. Always pass `--target`.

### Where PGO does not reach

`cargo install` exposes no two-pass mechanism. `cargo install --help` offers only `--debug` and
`--profile <PROFILE-NAME>`. A binary distributed through crates.io and installed with `cargo install`
therefore cannot be PGO-optimized by its author. Ship a pre-built artifact if PGO matters.

`cargo-pgo` 0.3.0 wraps the sequence above and adds BOLT. It hides the two traps rather than removing
them, so reach for it only once the manual four steps work.

---

## 5. The global allocator

Rust uses the system allocator by default. Swapping it is one static item.

```rust,ignore
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
```

```rust,ignore
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;
```

Current versions: `tikv-jemallocator` 0.7.0 (over `tikv-jemalloc-sys` 0.7.1, jemalloc 5.3.1) and
`mimalloc` 0.1.52 (over mimalloc 3.3.2). The older `jemallocator` crate is stale at 0.5.4; do not start
there. jemalloc covers Linux and macOS. mimalloc is portable.

The speed effect is platform-dependent, because it is a comparison against whatever system allocator
the platform ships. Measure it on each target. The cost is fixed and measurable up front.

Measured on the same `fn main` with `strip = true`, `panic = "abort"`, `codegen-units = 1`,
`aarch64-apple-darwin`. Build time is a cold release build with a fresh target directory:

| Allocator | Binary bytes | Delta | Cold build |
| --- | --- | --- | --- |
| System (default) | 341,344 | — | 0.3 s |
| `mimalloc` 0.1.52 | 443,840 | +102,496 | 3.1 s |
| `tikv-jemallocator` 0.7.0 | 605,104 | +263,760 | 40.5 s |

jemalloc builds a C library from source, which is where the 40 s goes. On a mobile target the binary
delta lands in the app bundle; check it with `cargo bloat --crates` against the ship profile.

### Confirm the allocator is actually linked

Both allocators announce themselves at run time, which is faster than reading a symbol table:

```bash
_RJEM_MALLOC_CONF=stats_print:true ./myapp    # jemalloc prints its statistics at exit
MIMALLOC_VERBOSE=1 ./myapp                    # mimalloc prints its options at startup
```

### jemalloc tuning: two different variables

`tikv-jemallocator` prefixes the jemalloc symbols, so the plain `MALLOC_CONF` name does not reach it.
The build-time and run-time knobs are separate variables, and mixing them up is the usual reason a
tuning attempt measures as no change.

| When | Variable | Verified behaviour |
| --- | --- | --- |
| Run time | `_RJEM_MALLOC_CONF` | `_RJEM_MALLOC_CONF=bogus:1 ./myapp` prints `<jemalloc>: Invalid conf pair: bogus:1` |
| Run time | `MALLOC_CONF` | Silently ignored |
| Build time | `JEMALLOC_SYS_WITH_MALLOC_CONF` | Forwarded by `build.rs` as jemalloc's `--with-malloc-conf=`. A binary built with `JEMALLOC_SYS_WITH_MALLOC_CONF=bogus:1` prints `<jemalloc>: Invalid conf pair: bogus:1` with no environment variable set at run time |
| Build time | `MALLOC_CONF` | Does nothing. The same build with `MALLOC_CONF=bogus:1` printed no jemalloc line |

The prefix is a crate feature. `tikv-jemallocator` 0.7.0 offers
`unprefixed_malloc_on_supported_platforms`, which moves the run-time name back to `MALLOC_CONF`. On
some platforms the feature does nothing. `tikv-jemalloc-sys` 0.7.1 lists `android`, `dragonfly` and
`apple` in `NO_UNPREFIXED_MALLOC_TARGETS` and turns the prefix back on for them, so on macOS and
Android the run-time name stays `_RJEM_MALLOC_CONF`. The build script reports this, but the message
comes from a registry dependency and Cargo does not display it. Read it from the build directory:

```bash
grep -rh cargo:warning target/release/build/*/output
```

With the feature enabled, an `aarch64-apple-darwin` build printed:

```text
cargo:warning="Unprefixed `malloc` requested on unsupported platform `aarch64-apple-darwin` => using prefixed `malloc`"
```

Transparent huge pages (`thp:always`) are Linux-only. On macOS the binary reports
`<jemalloc>: No THP support: thp:always` and continues. Do not carry a THP measurement from a Linux
server to a macOS or Android result.

---

## 6. Order of work

Each row costs more than the one above it. Stop when the metric is met.

| Step | Cost | Portability cost | Check that it worked |
| --- | --- | --- | --- |
| Confirm the settings reach rustc | Minutes | None | `cargo build --release -v`, read the rustc command line |
| `opt-level`, `lto`, `codegen-units` | Build time only | None | `cargo bloat`, Criterion baseline |
| `target-cpu` baseline (`x86-64-v3` and similar) | None at run time | Drops old CPUs | `diff` of `rustc --print cfg` |
| Swap the allocator | Binary size, build time | jemalloc: Linux and macOS only; mimalloc: none | `MIMALLOC_VERBOSE=1`, or jemalloc `stats_print` |
| PGO | A representative workload, plus CI plumbing | None | Build log has no `bad magic` warning |
| `target-cpu=native` | None | Binary runs on one machine class | `diff` of `rustc --print cfg` |

Every row needs a Criterion baseline before and after, per SKILL.md rule 4. A build-configuration
change is invisible in review, so an unmeasured one becomes a permanent unexplained setting.
