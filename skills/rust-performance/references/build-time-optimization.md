# Build-Time Optimization

Reference for cutting Rust compile time in a multi-crate workspace, especially one that cross-compiles to several mobile targets.

## 1. Diagnose first with cargo --timings

```bash
cargo build --locked --timings
cargo build --locked --release --timings
# Writes target/cargo-timings/cargo-timing.html
```

Read the timeline for:

- Long sequential chains, which mean no parallelism is available.
- Individual crates over 10 s, which are the candidates worth attacking.
- Proc-macro crates, which block every downstream crate until they finish.

For LLVM IR volume rather than wall time, use `cargo llvm-lines`:

```bash
cargo install cargo-llvm-lines
cargo llvm-lines --locked --release | head -20
cargo llvm-lines --locked --release -p my-crate | head -30
```

High IR volume in a crate costs both compile time and binary size. Fix it with the thin-wrapper pattern described in SKILL.md, then check the signature shape in section 7.

---

## 2. sccache

sccache caches `rustc` output. It matters most when the same crate is compiled many times, which is exactly what a multi-target mobile matrix does.

```bash
# Install
cargo install sccache   # or: brew install sccache

# Enable for Rust builds, in .cargo/config.toml or in the environment
export RUSTC_WRAPPER=sccache

# Check the hit rate. Expect over 80% on a rebuild.
sccache --show-stats
```

In GitHub Actions:

```yaml
- uses: mozilla-actions/sccache-action@v0.0.9
  env:
    RUSTC_WRAPPER: sccache
```

Most crate compilations across mobile targets differ only by target triple, and sccache deduplicates them well for pure-Rust crates. Set `RUSTC_WRAPPER=sccache` for every target build, not only the host one.

---

## 3. Cross-compilation target matrix

A full Android matrix is four targets:

```text
aarch64-linux-android
armv7-linux-androideabi
i686-linux-android
x86_64-linux-android
```

That 4x multiplier is usually the single biggest build-time factor in a mobile Rust project.

### Build only what you need during development

```bash
# Local iteration: arm64 only, which covers most devices and ARM emulators
cargo build --locked --target aarch64-linux-android

# Release: the whole matrix
for target in aarch64-linux-android armv7-linux-androideabi \
              i686-linux-android x86_64-linux-android; do
  cargo build --locked --release --target "$target"
done
```

### Parallelize the matrix in CI

```yaml
strategy:
  matrix:
    target:
      - aarch64-linux-android
      - armv7-linux-androideabi
      - i686-linux-android
      - x86_64-linux-android
# Each job builds one target, so wall-clock time is one target build.
```

### iOS targets

```bash
# Device
cargo build --locked --release --target aarch64-apple-ios

# Simulator on an Apple Silicon host
cargo build --locked --release --target aarch64-apple-ios-sim

# Simulator on an Intel host
cargo build --locked --release --target x86_64-apple-ios
```

Combine the device and simulator slices into an XCFramework. Pass one library per platform. If you build more than one simulator architecture, merge those slices into one static library with `lipo` first:

```bash
xcodebuild -create-xcframework \
  -library target/aarch64-apple-ios/release/libmycrate.a \
  -library target/aarch64-apple-ios-sim/release/libmycrate.a \
  -output MyCrate.xcframework
```

Binding generation for an FFI layer runs once per target and costs almost nothing next to compilation. See `uniffi-packaging-versioning` and `rust-android-build`.

---

## 4. Workspace splitting for parallelism

```bash
cargo tree --locked | head -30
cargo tree --locked --depth 1
cargo tree --locked --prefix depth

cargo build --locked --timings   # the timeline shows how much parallelism you get
```

Rules that actually help:

- Break circular dependencies first. Nothing else parallelizes until they are gone.
- Put proc-macros in their own crate. A proc-macro crate blocks every dependent crate.
- Keep frequently-changed code isolated, so a small edit invalidates a small part of the cache.
- Keep leaf crates such as shared error types and domain types small and stable. Everything depends on them, so every edit to them rebuilds everything.

See `rust-crate-architecture` for the layering rules behind this.

---

## 5. Linkers

### Host builds

`rust-lld` is the default linker for `x86_64-unknown-linux-gnu` since Rust 1.90. Do not configure `-C link-arg=-fuse-ld=lld` there. It is dead config on 1.97.0. Verified in a `rust:1.97-slim` container with no flags and no `.cargo/config.toml`: `readelf -p .comment` on the built binary reports `Linker: LLD 22.1.6`, and adding the flag changes nothing.

mold is the remaining upgrade on Linux:

```toml
# mold, the fastest option. Linux ELF only.
[target.x86_64-unknown-linux-gnu]
linker = "clang"
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

Rough link speed on a large project: GNU ld, then lld at about 2x, then mold at about 5-10x. mold is Linux ELF only.

`wild-linker` 0.10.0 is a newer incremental Linux linker. It is less mature than mold, so treat it as an experiment. Note the name: the crates.io crate called `wild` is an unrelated Windows glob-expansion library.

### Platform rules

- **macOS**: the default Apple linker needs no alternative. `mold` is Linux ELF only.
- **Android**: the NDK ships its own `lld`. Do not override the linker for `*-linux-android*` targets.
- **iOS**: use the Xcode-provided Apple linker through the standard Cargo iOS target configuration. Do not override.

---

## 6. Other quick wins

```toml
[profile.dev]
debug = "line-tables-only"     # much faster than full debug info, still gives backtraces
split-debuginfo = "unpacked"   # reduces linker input on macOS
```

```bash
# Sometimes faster for full rebuilds and for CI, where the incremental cache is cold
CARGO_INCREMENTAL=0 cargo build --locked
```

Pin the versions of heavy proc-macro dependencies. An unpinned bump recompiles the proc-macro crate and everything downstream of it.

Prefer `--locked` in every scripted build. It stops a background dependency resolution from silently changing what you measured.

---

## 7. Generic signature shape

An `impl Trait` parameter taken **by value** is the most expensive generic signature in a build. The callee owns the argument, so it must forward `&mut arg` to the next generic call. With a delegating `impl<T: Trait + ?Sized> Trait for &mut T` in scope that forwarding type-checks, and each call level instantiates the callee one `&mut` deeper. Behind `&mut impl Trait` the callee already holds a reference and forwards it unchanged, so every level instantiates at the root type.

```rust
trait Sink { fn put(&mut self, b: u8); }
impl<T: Sink + ?Sized> Sink for &mut T { fn put(&mut self, b: u8) { (**self).put(b) } }

// By value: `leaf` is instantiated once per call depth.
#[inline(never)] fn leaf(mut x: impl Sink) { x.put(1); }
#[inline(never)] fn mid(mut x: impl Sink) { leaf(&mut x); }
#[inline(never)] fn top(mut x: impl Sink) { leaf(&mut x); mid(&mut x); }

// Behind `&mut`: every level is instantiated at the root type.
#[inline(never)] fn leaf_ref(x: &mut impl Sink) { x.put(1); }
#[inline(never)] fn mid_ref(x: &mut impl Sink) { leaf_ref(x); }
#[inline(never)] fn top_ref(x: &mut impl Sink) { leaf_ref(x); mid_ref(x); }
```

Measured on rustc 1.97.0, aarch64-apple-darwin, `-C opt-level=0`, with one root type `Buf`:

| Form | Monomorphized symbols for the three functions |
| --- | --- |
| by value | 4: `top::<&mut Buf>`, `mid::<&mut &mut Buf>`, `leaf::<&mut &mut Buf>`, `leaf::<&mut &mut &mut Buf>` |
| behind `&mut` | 3: `top_ref::<Buf>`, `mid_ref::<Buf>`, `leaf_ref::<Buf>` |

`leaf` appears twice in the by-value column because two call paths reach it at two different depths. Count the copies with `nm target/release/libmycrate.rlib | rustfilt | grep '::leaf'`, after `cargo install rustfilt`.

### Measured build cost of the three shapes

One generated crate in three copies that differ only in one trait method signature. Each copy has 50 nested struct levels, where `T<i>` holds a `Vec<T<i+1>>` and a `Vec<T<i+2>>`, so many distinct paths reach the same level at different depths. Each copy has one `Ser` impl per level and 300 `pub` entry functions, 603 lines in total.

```text
fn ser(&self, out: impl io::Write)      -> io::Result<()>;   // by value
fn ser(&self, out: &mut impl io::Write) -> io::Result<()>;   // behind &mut
fn ser(&self, out: &mut dyn io::Write)  -> io::Result<()>;   // behind &mut dyn
```

```bash
# One timed run. Repeat it three times per variant and take the median.
rm -rf "$TARGET"
RUSTC_WRAPPER= CARGO_INCREMENTAL=0 CARGO_TARGET_DIR="$TARGET" cargo build --release -q
```

| Signature | `cargo check` | `cargo build` | `cargo build --release` | `ser` symbols in the rlib | rlib bytes |
| --- | --- | --- | --- | --- | --- |
| `out: impl io::Write` | 0.18 s | 0.58 s | 10.7 s | 381 | 1200168 |
| `out: &mut impl io::Write` | 0.18 s | 0.24 s | 0.71 s | 28 | 539080 |
| `out: &mut dyn io::Write` | 0.18 s | 0.25 s | 0.67 s | 51 | 222376 |

Release figures are the median of three runs, each from a removed target directory, with `sccache` and incremental compilation off. The by-value form costs 15x the release build time of `&mut impl io::Write`, 2.2x its rlib size, and 5.4x the rlib size of the `&mut dyn io::Write` form.

Three rules follow:

- Take a generic writer, reader or sink parameter by `&mut impl Trait`. `&mut dyn Trait` saves almost nothing more on this shape and it costs a virtual call per write.
- `cargo check` is identical for all three, to the hundredth of a second. Type-checking is depth-independent, so a check-only CI gate reports none of this. Gate build time on `cargo build --release`.
- Confirm the mechanism from the deepest symbol. In the by-value rlib it is `<T48 as Ser>::ser::<&mut &mut ... &mut Vec<u8>>`, with 48 `&mut` levels.
