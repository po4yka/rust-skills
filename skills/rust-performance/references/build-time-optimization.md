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

High IR volume in a crate costs both compile time and binary size. Fix it with the thin-wrapper pattern described in SKILL.md.

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

```toml
# lld, LLVM's linker. Faster than GNU ld.
[target.x86_64-unknown-linux-gnu]
rustflags = ["-C", "link-arg=-fuse-ld=lld"]

# mold, the fastest option. Linux ELF only.
[target.x86_64-unknown-linux-gnu]
linker = "clang"
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

Rough link speed on a large project: GNU ld, then lld at about 2x, then mold at about 5-10x. mold is Linux ELF only.

### Platform rules

- **macOS**: the default Apple linker is adequate. Do not use `mold`.
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
