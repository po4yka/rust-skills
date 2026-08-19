# Workspace Patterns Reference

Deep material for `cargo-workflows`: dependency inheritance, workspace lints,
selective builds, lock-file management, native artifact mapping, and edition
migration.

## Workspace dependency management

Centralize every dependency version in the root `Cargo.toml`. A member crate
must never carry its own version number for a shared dependency.

```toml
[workspace.dependencies]
# Internal crates: path plus an explicit version. The path is what cargo
# resolves; the version stops cargo-deny flagging the entry as a wildcard.
my-domain   = { path = "crates/my-domain",   version = "0.0.0" }
my-error    = { path = "crates/my-error",    version = "0.0.0" }
my-geometry = { path = "crates/my-geometry", version = "0.0.0" }

# External crates: compatible ranges by default.
serde      = { version = "1", features = ["derive"] }
serde_json = { version = "1", features = ["float_roundtrip"] }
tokio      = { version = "1", default-features = false }
rusqlite   = { version = "0.40", default-features = false, features = ["bundled"] }
flate2     = { version = "1", default-features = false, features = ["rust_backend"] }

# Determinism-critical crates: pinned EXACTLY with `=`.
libm       = "=0.2.16"    # Bit-identical transcendentals
```

Members inherit and may add features, but must not weaken them:

```toml
[dependencies]
serde.workspace = true
my-domain.workspace = true
tokio = { workspace = true, features = ["rt", "net"] }
```

### When to pin exactly

Use `=` pinning only where a patch release can change program output:

- Math and float formatting crates, when the output must be bit-identical
  across platforms.
- Text shaping and font parsing crates, when a rendered or measured result is
  compared against a stored snapshot.
- Any crate whose output feeds a golden test.

A `=` pin means routine `cargo update` will not move it. Bump such a crate
deliberately, in its own change, and re-bless the affected snapshots in the same
commit.

Everywhere else, use a compatible range. Over-pinning creates duplicate versions
in the graph and makes security updates slow.

## Workspace-level lints

Configure clippy and rustc lints once at the workspace level.

```toml
[workspace.lints.clippy]
# Group activations. `priority = -1` lets individual lints below override them.
all         = { level = "deny",  priority = -1 }
correctness = { level = "deny",  priority = -1 }
suspicious  = { level = "deny",  priority = -1 }
pedantic    = { level = "warn",  priority = -1 }
nursery     = { level = "warn",  priority = -1 }
cargo       = { level = "warn",  priority = -1 }

# Unsafe documentation. Deny by default.
missing_safety_doc         = "deny"
undocumented_unsafe_blocks = "deny"

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"
unused_must_use        = "deny"
let_underscore_drop    = "deny"

[workspace.lints.rustdoc]
broken_intra_doc_links = "deny"
```

Every member opts in:

```toml
[lints]
workspace = true
```

Rules:

- Keep `missing_safety_doc` and `undocumented_unsafe_blocks` denied for the
  whole workspace. Relax them only for a raw-JNI crate whose generated entry
  points take raw pointers, and scope the allowance to that crate.
- Declare `#![forbid(unsafe_code)]` in the crate root of every pure-logic crate.
  The workspace lint table cannot express this, so it must be per crate.
- Put thresholds in `clippy.toml`, not in `Cargo.toml`:

```toml
msrv = "1.88.0"
allowed-duplicate-crates = ["bitflags"]
```

  Keep `msrv` equal to `rust-version` in `[workspace.package]`. If `msrv` is
  higher, clippy suggests APIs that the declared MSRV cannot compile. If it is
  lower, clippy holds back suggestions you could already use.

  Every entry in `allowed-duplicate-crates` needs a comment naming the
  transitive dependency that forces the split.

See `rust-lints` for the lint catalogue itself.

## Selective build commands

```bash
# Build or check one member
cargo build --locked -p <crate>
cargo check --locked -p <crate>

# Test one member, or one integration test inside it
cargo nextest run --locked -p <crate>
cargo nextest run --locked -p <crate> --test <integration-test>

# Test everything
cargo nextest run --locked --workspace

# Exclude an expensive member from a workspace build
cargo build --locked --workspace --exclude <bench-crate>

# Cross-compile type-check. This needs no NDK or SDK linker, because
# `cargo check` does not link.
cargo check --locked --target aarch64-linux-android -p <crate>
cargo check --locked --target aarch64-apple-ios     -p <crate>
```

`cargo check --target <triple>` is the cheapest guard against a
cross-compilation break. Run it in CI for every shipping target on the pure-logic
crates, even when the full native build runs only on the release lane.

## Cargo.lock management

Check `Cargo.lock` into git for an application workspace. Do not check it in for
a published library.

```bash
cargo update -p <dep> --precise <version>   # Move one dependency, exactly
cargo update --dry-run                      # Preview the whole update
cargo update                                # Update within semver ranges
cargo generate-lockfile                     # Rebuild the lock file from scratch
```

Reviewing a `Cargo.lock` diff:

- Check every version bump on a security-sensitive crate: TLS, HTTP clients,
  compression, image and font parsers, and anything that parses untrusted input.
- Check that an exactly pinned crate did not move. If it did, the change must
  also carry re-blessed snapshots.
- Check for a new duplicate version of a crate already in the graph. Run
  `cargo tree --locked --duplicates` to confirm, and record the cause in
  `deny.toml` under `skip` if the split is unavoidable.
- A large unexplained lock diff usually means somebody ran `cargo update`
  instead of `cargo update -p <dep>`. Ask for the reason.

## Native build system properties

Expose the minimum set of properties, and hardcode the rest so a build cannot
be misconfigured silently.

| Property | Purpose | Typical default |
|----------|---------|-----------------|
| `<ns>.native.enabled` | Turn the whole cargo build off | `true` |
| `<ns>.native.abis` | Override the selected debug ABIs | Host or emulator ABI |
| `<ns>.native.cargoProfile` | Cargo profile for CI and release | `release` or a custom profile |
| `<ns>.local.native.cargoProfile` | Cargo profile for local development | A dev-inherited profile |

Keep these values out of the property surface and fix them in the build logic:

| Setting | Rule |
|---------|------|
| Release ABI set | Always the complete shipping set. A release must not build a subset. |
| `minSdk` | One source of truth. It also forms the clang driver name. |
| NDK and CMake versions | Pinned in the version catalog, resolved under the configured SDK. |
| Output path | A generated directory under `build/`, wired into the variant. |

An ABI override is useful for a debug loop. It must be impossible on the release
path: a release APK or AAB that ships one ABI is a shipping incident.

## Native artifact mapping

Cargo derives the library file name from the package name with hyphens replaced
by underscores. The platform may need a different name. Map the two explicitly
and keep the table next to the build logic.

| Cargo package | Cargo output       | Platform artifact  |
|---------------|--------------------|--------------------|
| `my-ffi`      | `libmy_ffi.so`     | `libmy_ffi.so`     |
| `my-engine`   | `libmy_engine.so`  | `libmyengine.so`   |

The loader name must match: `System.loadLibrary("my_ffi")` loads `libmy_ffi.so`.
UniFFI-generated Kotlin derives this name from the crate, so renaming the
artifact breaks the generated bindings.

A privileged helper executable is not a `System.loadLibrary` target. Build it
with a separate task and package it as an asset, not into `jniLibs`.

### iOS static library mapping

| Cargo package | Static library                                                   | XCFramework slice           |
|---------------|------------------------------------------------------------------|-----------------------------|
| `my-ffi`      | `libmy_ffi.a` (aarch64-apple-ios)                                  | `ios-arm64`                 |
| `my-ffi`      | `libmy_ffi.a` (aarch64-apple-ios-sim + x86_64-apple-ios, `lipo`'d) | `ios-arm64_x86_64-simulator`|

## Edition migration

The workflow below applies to any edition bump. Do it once, workspace-wide, in a
dedicated change.

### Per-crate migration workflow

```bash
# Pick a leaf crate with no internal dependents.
cd crates/<leaf-crate>

# Report the silent behaviour changes FIRST. These lints go quiet once the
# crate is on edition 2024, because the behaviour has already changed.
cargo clippy --all-targets -- -W rust_2024_compatibility

cargo fix --edition

# cargo fix edits .rs files in place. Read the diff before you continue.
git diff

# Replace `edition.workspace = true` in this crate with an explicit override:
#   edition = "2024"
# Keep the override only during the migration. When the last crate is done,
# bump [workspace.package] edition and restore `edition.workspace = true`
# in every crate.

# Verify.
cargo clippy --locked -p <leaf-crate> --all-targets -- -D warnings
cargo nextest run --locked -p <leaf-crate>
```

### Migration order

Work from leaves inward. The FFI crate goes last, because it depends on
everything and stricter `extern` rules hit it hardest.

1. Host-only or pure-logic crates: the CLI crate, the error crate.
2. Core logic crates under `#![forbid(unsafe_code)]`: domain, schema, geometry.
3. Mid-layer crates.
4. Backend and pipeline crates.
5. The FFI crate.

### Edition 2024 breaking changes that bite

- **Stricter `unsafe` in `extern` blocks.** An `extern` block must now be written
  `unsafe extern "C" { ... }` or `unsafe extern "system" { ... }`. Every item
  inside it is unsafe to call by default. Mark an item `safe fn ...` only when
  the callee really has no safety contract. Review the FFI crate and every crate
  with platform C bindings.
- **Unsafe attributes.** `#[no_mangle]`, `#[export_name]`, and
  `#[link_section]` must be wrapped: `#[unsafe(no_mangle)]`. Every raw FFI
  export is affected. `cargo fix --edition` rewrites them.
- **`static mut` references stop the build.** The `static_mut_refs` lint is
  deny-by-default on edition 2024. `&mut COUNTER` fails with
  `error: creating a mutable reference to mutable static`. A plain read fails
  too, because the format machinery takes a reference: `println!("{}", COUNTER)`
  fails with `error: creating a shared reference to mutable static`. Only a
  direct read or write of the value inside `unsafe` still compiles.
  `#[allow(static_mut_refs)]` silences both messages. Do not use it as the
  migration answer. `&raw mut COUNTER` and `&raw const COUNTER` build a raw
  pointer and create no reference. A raw pointer keeps every data race the
  `static mut` had. `cargo fix --edition` prints the `&raw mut` suggestion but
  does not apply it. The `memory-model` skill selects the real replacement.
- **`gen` is a reserved keyword.** Rename any identifier called `gen` before you
  migrate. Find them with `grep -rn '\bgen\b' crates/`.
- **Precise-capturing `impl Trait`.** A function that returns `impl Trait` and
  captures only some of its input lifetimes now needs `use<'a, T>` syntax.
  Iterator adapters are the usual site. `cargo fix --edition` normally handles
  it.
- **`if let` and `while let` chains stabilize.** You can collapse existing nested
  patterns, but do not do it in the migration commit. Keep the migration diff
  surgical so a reviewer can read it.
- **Tail-expression temporaries drop earlier.** A temporary in the tail
  expression of a block is now dropped before the block's local variables.
  Edition 2021 dropped it after them. A body of `let _local = Noisy("local");
  temp().0.len() > 0` prints `drop local / drop temporary` on 2021 and
  `drop temporary / drop local` on 2024. Nothing fails to compile, so
  `cargo fix --edition` cannot repair it. The `tail_expr_drop_order` lint is the
  only mechanical way to find the sites.
- **`if let` releases its scrutinee before the `else` block.** A temporary in the
  `if let` scrutinee is now dropped before the `else` block runs. Edition 2021
  held it to the end of the whole `if let`. A `MutexGuard` left as a temporary
  therefore stops guarding the `else` branch: with a static `M: Mutex<Option<u32>>`,
  `if let Some(v) = *M.lock().unwrap() { .. } else { M.try_lock().is_ok() }`
  yields `false` on 2021 and `true` on 2024. The `if_let_rescope` lint finds the
  sites. Bind the guard to a named local, so the drop point is explicit and
  identical on both editions.

The last two entries change run-time behaviour with a clean build and green
tests. They are the reason the migration workflow above runs
`-W rust_2024_compatibility` before `cargo fix --edition`, not after.

### Do not bump the rustfmt edition early

`rustfmt.toml:edition` controls the formatter rules, and it is independent of the
crate edition. Bump it only after every crate is on the new edition and the
workspace builds clean. An early bump reformats the crates that have not
migrated yet and buries the real diff.
