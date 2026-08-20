---
name: cargo-workflows
description: Use when you manage a Rust workspace - add or remove crates, edit workspace dependencies and lints, pin the toolchain, run cargo nextest/audit/deny, configure Cargo profiles and rustflags for cross-compilation to Android or iOS, build cdylib or staticlib FFI artifacts, wire a host build system to cargo, debug Cargo.lock churn or feature-unification surprises, or migrate the crate edition.
license: BSD-3-Clause
---

# Cargo Workflows

This skill covers the workspace-level mechanics of Cargo: layout, dependency
inheritance, profiles, cross-compilation, test runners, supply-chain policy, and
edition migration. Run every command from the directory that holds the workspace
`Cargo.toml`.

## Workspace layout

A multi-crate project uses a virtual manifest at the workspace root. Keep the
control files next to it.

```text
<workspace-root>/
  Cargo.toml              # Virtual workspace manifest: members, deps, lints, profiles
  Cargo.lock              # Checked in for an application workspace
  rust-toolchain.toml     # Pinned toolchain + components (rustfmt, clippy)
  rustfmt.toml            # Formatter config
  clippy.toml             # Clippy thresholds (msrv, allowed-duplicate-crates, ...)
  deny.toml               # cargo-deny policy
  .cargo/config.toml      # Per-target rustflags
  .config/nextest.toml    # nextest profiles
  crates/
    <leaf-crates>/        # Pure logic, no internal dependents
    <mid-layer-crates>/
    <ffi-crate>/          # cdylib / staticlib boundary, depends on everything
    <cli-crate>/          # Host-only binary
    <bench-crate>/        # Criterion benchmarks
```

Rules:

- Do not hardcode the member count in documentation. Derive it with
  `cargo metadata --locked --no-deps --format-version 1`.
- Order the `members` list from leaf crates to the FFI crate. The order records
  the dependency direction and drives migration order.
- Keep helper scripts and fixture generators outside `crates/`. They are not
  cargo packages, so they must not appear in `members`.

## The `--locked` discipline

Pass `--locked` on every cargo invocation that a build system, CI job, or agent
runs. `--locked` fails the command if `Cargo.lock` would change. Without it, a
build silently resolves new versions and the build stops being reproducible.

Drop `--locked` only when you deliberately update dependencies with
`cargo update`.

## Toolchain pinning

Pin the toolchain in `rust-toolchain.toml` so every machine and CI runner uses
one compiler:

```toml
[toolchain]
channel = "1.88.0"
components = ["rustfmt", "clippy"]
```

Set `rust-version` in `[workspace.package]` to declare the MSRV, and mirror it
in `clippy.toml` as `msrv = "..."` so clippy does not suggest APIs that are
newer than the MSRV. This declaration is not proof that the resolved dependency
graph supports the MSRV. Resolver 3 prefers compatible versions but can select
an incompatible version when no compatible version satisfies the requirement.
Run the real build and tests with the minimum toolchain.

## Cross-compilation

The same pattern applies to Android, iOS, and any other non-host target: install
the target, put rustflags in `.cargo/config.toml`, and let the host build system
supply the linker.

Target rustflags, the manual NDK linker setup that replaces `cargo-ndk`,
XCFramework packaging, and the rules for driving cargo from Gradle or Xcode are
in [references/cross-compilation.md](references/cross-compilation.md).

### Install the targets

```bash
# Android, full four-ABI shipping set
rustup target add aarch64-linux-android armv7-linux-androideabi \
    x86_64-linux-android i686-linux-android

# iOS device and simulator
rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
```

### Android ABIs and Rust triples

| Android ABI | Rust target             | Clang target prefix     |
|-------------|-------------------------|-------------------------|
| arm64-v8a   | aarch64-linux-android   | aarch64-linux-android   |
| armeabi-v7a | armv7-linux-androideabi | armv7a-linux-androideabi|
| x86_64      | x86_64-linux-android    | x86_64-linux-android    |
| x86         | i686-linux-android      | i686-linux-android      |

The `armeabi-v7a` clang prefix is `armv7a-`, but the Rust triple is `armv7-`.
This mismatch breaks naive string substitution. Map the two names explicitly.

The clang driver name also carries the API level: `<clang-prefix><minSdk>-clang`.
Read `minSdk` from one place and pass it into the toolchain lookup.

### iOS targets

| Target                | Use                       |
|-----------------------|---------------------------|
| aarch64-apple-ios     | Device                    |
| aarch64-apple-ios-sim | Simulator (Apple Silicon) |
| x86_64-apple-ios      | Simulator (Intel, legacy) |

### Cargo profiles for cross-compiled artifacts

Two valid strategies exist. Choose one and write it down.

**Stock profiles.** Use `dev` for local debug variants and `release` for shipping
variants. This is the simplest option and it keeps profile behaviour identical to
host builds.

**Custom inherited profiles.** Use them when the shipped library needs different
codegen from the host build - for example a size-optimized mobile artifact:

```toml
# Workspace Cargo.toml
[profile.mobile-release]
inherits = "release"
opt-level = "z"        # Optimize for size
panic = "unwind"       # Required: see below

[profile.mobile-dev]
inherits = "dev"
opt-level = 1
panic = "unwind"
```

Measure `opt-level = "z"` against `"s"` and `3` on the real artifact before you ship it: `"z"` is
not automatically the smallest, and a compute-bound path can prefer `3`. See
`skills/rust-performance/references/build-configuration.md`.

Select the profile from the host build system with a property, and give local
development a separate default so a debug loop does not pay for a release build.

**Keep `panic = "unwind"` on any profile that builds an FFI artifact.** This is
only a prerequisite for panic containment. With `panic = "abort"`,
`catch_unwind` cannot catch a panic. With `panic = "unwind"`, a panic still must
not cross a raw `extern "C"` or `extern "system"` boundary. Catch it inside each
entry point and map it to an ABI-safe status, sentinel, or host exception.
Verify the generated binding runtime before you rely on it to do this work.

### Build only the artifact the platform consumes

`cargo rustc` overrides the crate type for one invocation. The manifest can then
keep `crate-type = ["lib"]`, so a plain `cargo build --workspace` does not pay
for the linking work:

```bash
# Android shared library
cargo rustc --locked --profile <profile> --target <triple> \
    --crate-type cdylib -p <ffi-crate> --lib

# iOS static library
cargo rustc --locked --release --target aarch64-apple-ios \
    --crate-type staticlib -p <ffi-crate> --lib
```

## FFI crate rules

Prefer exactly one FFI crate. It is then the only crate that crosses the
language boundary. Add a second FFI crate only when the platform loads the
libraries independently - for example one `.so` per background service. Every
extra boundary duplicates the error mapping, the panic guard, and the lifetime
rules, so pay that cost on purpose.

Two valid ways exist to declare the library target. Choose one and write it
down.

```toml
# crates/<ffi-crate>/Cargo.toml

# A. Plain Rust lib. Request cdylib or staticlib per invocation with
#    `cargo rustc --crate-type ...`. A plain `cargo build --workspace`
#    then does no linking work.
[lib]
crate-type = ["lib"]

# B. Always produce the shared library. Simpler build scripts, but every
#    workspace build links the artifact.
[lib]
crate-type = ["cdylib", "lib"]
```

Keep `lib` in the list under option B. Without it, no other crate in the
workspace can use the FFI crate, and doc-tests cannot compile.

### Both bindings styles

| Rule | Reason |
|------|--------|
| `panic = "unwind"` plus a boundary panic guard | The profile permits `catch_unwind`; the guard prevents a Rust unwind from reaching the host ABI. |
| One FFI crate where possible | A second boundary duplicates error mapping and lifetime rules. |
| No business logic in the FFI crate | Keep it a thin translation layer over the pure-logic crates. |
| Build `cdylib` or `staticlib` on demand with `cargo rustc` | Workspace builds stay fast. |

### Raw JNI crates

- The JVM loads a `.so`, so the crate must produce a `cdylib` - through option B
  above, or through `cargo rustc --crate-type cdylib`.
- Export `pub extern "system" fn Java_...` entry points. Edition 2024 spells the
  attribute `#[unsafe(no_mangle)]`; earlier editions spell it `#[no_mangle]`.
- The `jni` crate supplies the `JNIEnv`, `JClass`, and `JString` wrappers.
- A raw JNI surface usually needs `missing_safety_doc` and
  `not_unsafe_ptr_arg_deref` allowed, because the JNI entry points take raw
  pointers from the JVM. Scope the allowance to the FFI crate if you can. See
  `rust-jni`.

Apply the same guard to every raw C, JNI, and callback entry point. Convert a
normal Rust error and a panic to explicit ABI values:

```rust
use std::panic::{catch_unwind, AssertUnwindSafe};

#[repr(C)]
pub enum Status {
    Ok = 0,
    InvalidArgument = 1,
    Failed = 2,
    Panicked = 3,
}

fn calculate() -> Result<u32, ()> {
    todo!()
}

/// # Safety
/// `out` must be null or valid for one aligned `u32` write.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn calculate_for_host(out: *mut u32) -> Status {
    if out.is_null() {
        return Status::InvalidArgument;
    }

    match catch_unwind(AssertUnwindSafe(calculate)) {
        Ok(Ok(value)) => {
            // SAFETY: The caller contract and the null check make this write valid.
            unsafe { out.write(value) };
            Status::Ok
        }
        Ok(Err(())) => Status::Failed,
        Err(_) => Status::Panicked,
    }
}
```

Do not use `catch_unwind` as a general recovery boundary. It catches only
unwinding Rust panics. It does not catch aborts, foreign exceptions, or memory
unsafety.

### UniFFI crates

- Prefer the proc-macro path: `#[uniffi::export]`, `#[derive(uniffi::...)]`, and
  `uniffi::setup_scaffolding!()`. No `.udl` files are needed.
- UniFFI generates the entry points. Do not write `#[no_mangle]` functions.
- Keep the unsafe-doc lints **denied**. UniFFI hides the raw pointers, so the FFI
  crate has no reason to relax them.
- Gate the bindgen CLI behind a feature so a default workspace build never
  compiles it:

```toml
[features]
cli = ["uniffi/cli"]

[[bin]]
name = "uniffi-bindgen"
required-features = ["cli"]
```

- Generate bindings by introspecting a **host** library, not a cross-compiled
  artifact. Build the host `cdylib` first, then run the bindgen binary:

```bash
cargo rustc --locked -p <ffi-crate> --lib --crate-type cdylib

cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
    generate --library target/debug/lib<ffi_crate>.dylib \
    --language kotlin --out-dir <kotlin-out>

cargo run --locked -p <ffi-crate> --features cli --bin uniffi-bindgen -- \
    generate --library target/debug/lib<ffi_crate>.dylib \
    --language swift --out-dir <swift-out>
```

The library extension is `.dylib` on macOS and `.so` on Linux. The `--`
separates the cargo arguments from the bindgen subcommand. Write the output to a
temporary directory first, then sync it into the generated-binding modules, so a
failed run does not leave a half-written module.

See `uniffi-boundary`, `uniffi-packaging-versioning`, and
`ffi-error-progress-cancel` for the boundary design itself.

## Feature flags

```toml
[features]
cli = ["uniffi/cli"]     # Optional tooling, off by default
loom = ["dep:loom"]      # Concurrency model checking, off by default
```

Rules:

- Features are additive. Once any crate in the graph enables a feature, it stays
  on for every consumer. Never use a feature to *remove* behaviour.
- Set `resolver = "2"` (or newer) in the workspace manifest. It stops
  dev-dependency features from leaking into normal dependencies.
- Use the `dep:<name>` syntax in a feature list. A bare optional dependency name
  creates an implicit feature with the same name that you did not intend to
  publish.
- Add `required-features` to a `[[bin]]` that needs an optional dependency.
  Otherwise `cargo build --workspace` tries to build it and fails.
- If a dependency's default features change the output bit-for-bit, pin the
  feature set and write down why. Enabling a GPU or SIMD backend on a crate that
  must produce byte-identical output breaks reproducibility.
- Test the project-owned matrix: default features, `--no-default-features`, and
  each supported feature family. Run `--all-features` only when that combination
  is a supported product; additive features do not make exclusive backends
  compatible.

## Testing

Use `cargo nextest` as the primary runner. It runs each test in its own process,
which isolates crashes and gives per-test timeouts.

```bash
cargo nextest run --locked                       # All workspace tests
cargo nextest run --locked --profile ci          # CI profile
cargo nextest run --locked -p <crate>            # One crate
cargo nextest run --locked -p <crate> --test <integration-test>
cargo test --locked --doc                        # Doc-tests: nextest skips these
```

`cargo nextest` does not run doc-tests. Always run `cargo test --locked --doc`
as a separate step, or the doc examples rot.

Example `.config/nextest.toml`:

```toml
[profile.default]
fail-fast = true
slow-timeout = { period = "60s" }
# Keep the opt-in tests out of the default lane.
default-filter = 'not test(/^network_integration_/)'

[profile.ci]
fail-fast = false
retries = 2
slow-timeout = { period = "60s", terminate-after = 3 }

# Opt-in profile for tests that touch the network.
[profile.network-integration]
default-filter = 'test(/^network_integration_/)'

[test-groups]
network = { max-threads = 1 }

[[profile.network-integration.overrides]]
filter = 'test(/^network_integration_/)'
test-group = 'network'
```

Rules:

- Keep network-dependent or otherwise flaky tests behind an opt-in profile and a
  single-threaded test group. Do not let them run in the default lane.
- Set `retries` only on the CI profile. A retry on a developer machine hides a
  real race.
- Keep the deterministic end-to-end test - the golden or snapshot test - in the
  crate that owns the orchestration, not in a leaf backend crate. Name the
  integration test file so the `--test <name>` selector is obvious.

See `rust-test-tools` and `rust-tdd` for test design.

## Dependency auditing

```bash
cargo audit                     # RustSec advisories only
cargo deny --locked check       # Licenses, bans, advisories, sources
```

### deny.toml policy

Write the policy so a new problem fails the build instead of adding to warning
noise.

**Licenses.** Allow only the licenses the current graph actually uses. A typical
permissive set is MIT, Apache-2.0, Apache-2.0 WITH LLVM-exception, BSD-2-Clause,
BSD-3-Clause, ISC, 0BSD, Zlib, Unicode-3.0, and CDLA-Permissive-2.0. Add MPL-2.0
only if you must - it is file-level copyleft, and the UniFFI crate family
requires it. Adding a license to the allowlist is a deliberate legal decision,
not a build fix.

**Advisories.** Set `yanked = "deny"`. Every `ignore` entry needs a written
reason and a review date. An ignore without a reason becomes permanent.

**Bans.** Deny wildcard dependencies. Deny new duplicate versions, and pin each
unavoidable transitive version split individually in `skip` with its cause. A
blanket `multiple-versions = "warn"` lets new version skew hide in the noise.

**Sources.** Deny unknown registries. Warn on unknown git sources at minimum.

See `rust-security` for advisory triage and supply-chain review.

## CI caching

```yaml
# Pin actions to an exact commit SHA, not a floating tag.
- uses: Swatinem/rust-cache@<exact-pinned-sha>   # v2 line
  with:
    cache-on-failure: true
    workspaces: "<workspace-dir> -> target"

# Manual cache, when you need control over the key
- uses: actions/cache@<exact-pinned-sha>          # v4 line
  with:
    path: |
      ~/.cargo/registry/index/
      ~/.cargo/registry/cache/
      ~/.cargo/git/db/
      <workspace-dir>/target/
    key: ${{ runner.os }}-cargo-${{ hashFiles('<workspace-dir>/Cargo.lock') }}
```

Set `cache-on-failure: true`. A failed job still produced compiled dependencies,
and the next run should reuse them.

## Workspace commands cheat sheet

```bash
cargo check --locked --workspace                  # Type-check everything
cargo build --locked --workspace                  # Codegen and link; check is not enough
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --check                                 # Format check
cargo build --locked -p <crate>                   # Build one crate
cargo build --locked --workspace --exclude <crate>
cargo bench --locked -p <bench-crate>             # Criterion benchmarks, host only
cargo tree --locked --duplicates                  # Find duplicate versions
cargo tree --locked -i <dep>                      # Who depends on <dep>?
cargo tree --locked -f '{p}: {f}' -i <dep>        # Which features are active
cargo update -p <dep> --precise <version>         # Pin one dependency
cargo update --dry-run                            # Preview a lock update
cargo generate-lockfile                           # Rebuild Cargo.lock
cargo metadata --locked --no-deps --format-version 1   # Member list, JSON
cargo deny --locked check                         # Full policy check
cargo audit                                       # Advisories only
```

Pass `--all-targets` to clippy. Without it, clippy skips tests, benches, and
examples, and those files then fail in CI on a lint you never saw locally.

## Rust edition

Edition 2024 stabilized in Rust 1.85.0 (February 2025).

- Keep the steady state at one edition in `[workspace.package]`, inherited with
  `edition.workspace = true`.
- During a staged migration, give the crate being migrated an explicit edition.
  Crates on different editions interoperate. Remove the overrides when the last
  crate migrates.
- Treat an edition bump as a workspace-wide contract change. Do it in a
  dedicated change with `cargo fix --edition`, formatting, clippy, and test
  evidence.
- Bump `rustfmt.toml:edition` only **after** every crate is on the new edition
  and the workspace builds clean. An early bump produces spurious diffs in the
  crates that have not migrated yet.

The per-crate migration workflow, the breaking changes that bite, and the
migration order are in
[references/workspace-patterns.md](references/workspace-patterns.md).

## Feature resolution pitfalls

Two resolver behaviours silently change what a workspace crate compiles. Both
are WARNING-severity.

| Pitfall | Symptom | First check |
|---------|---------|-------------|
| Feature unification across the workspace | A `no_std` crate gains `std`, heap allocation, or panicking infrastructure it must not contain. | `cargo tree --locked -f '{p}: {f}' -i <shared-dep>` |
| Workspace inheritance and target-specific features | A cross-compiled build pulls in Linux-only or Windows-only code and the link step fails with missing symbols. | `cargo tree --locked --target <triple> -f '{p}: {f}' -i <dep>` |

The full mechanism, the detection commands, and the fixes are in
[references/feature-resolution.md](references/feature-resolution.md).

## References

- [references/workspace-patterns.md](references/workspace-patterns.md) -
  workspace dependency inheritance, workspace lints, selective build commands,
  `Cargo.lock` review, native artifact mapping, and edition migration.
- [references/cross-compilation.md](references/cross-compilation.md) - target
  rustflags, the manual NDK linker setup, XCFramework packaging, and host build
  system integration rules.
- [references/feature-resolution.md](references/feature-resolution.md) - feature
  unification across the workspace, and workspace inheritance versus
  target-specific features.

## Related skills

- `rust-lints` - clippy configuration and lint policy
- `rust-crate-architecture` - crate boundaries and dependency direction
- `rust-security` - cargo-audit, cargo-deny, supply-chain review
- `rust-test-tools` - test runners, fixtures, and coverage
- `rust-performance` - runtime profiling and build-time tuning
- `rust-debugging` - GDB/LLDB, async debugging, backtraces
- `rust-unsafe` - unsafe code review
- `rust-jni` - raw JNI entry points and JVM interop
- `rust-android-build` - Android packaging and Gradle integration
- `uniffi-boundary` - UniFFI type and API design
- `uniffi-packaging-versioning` - binding packaging and version skew
- `ffi-error-progress-cancel` - error, progress, and cancellation across the boundary
