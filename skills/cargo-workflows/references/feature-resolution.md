# Feature Resolution Pitfalls

Deep material for `cargo-workflows`: resolver and feature behaviours that
silently change what a workspace crate compiles.

## Test supported feature products

Features are additive and unify for each package in the resolved graph. They
are not exclusive runtime switches. Define the combinations the project
supports, then test those combinations directly:

```bash
cargo test --locked --workspace
cargo test --locked -p <crate> --no-default-features
cargo test --locked -p <crate> --no-default-features --features <feature>
# Run only when the complete combination is supported.
cargo test --locked -p <crate> --all-features
```

Do not use `--all-features` as a universal quality gate when two backends are
intentionally exclusive. Either make the features additive, or test each
supported backend as a separate lane and reject the invalid combination with a
clear `compile_error!`.

`[target.'cfg(feature = "...")'.dependencies]` does not select dependencies by
feature. Cargo resolves features after it selects target dependency tables.
Use optional dependencies plus `[features]`, then put target selection in a
real target table.

Reference: [Cargo features](https://doc.rust-lang.org/cargo/reference/features.html#feature-unification),
[platform-specific dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#platform-specific-dependencies).

## Pitfall: feature unification silently enables features in `no_std` crates

**Severity: WARNING**

Cargo resolves features per package, not per dependency edge. Resolver v2
isolates dev-dependency features from normal dependencies, but normal-dependency
features are still unified across the whole workspace. If any crate enables `std`
on a shared dependency, every other workspace crate that uses that dependency
gets `std` too - including a crate that declares itself `no_std`.

The concrete hazard: a bench or test binary adds `serde` with the `derive`
feature, and `derive` turns on for every `serde` consumer. Worse, a pure-logic
crate that was designed `no_std` for portability silently gains heap allocation,
`println!`, or panicking infrastructure that should be absent from the shipped
artifact.

Detection:

```bash
# Show which packages activate which features on a shared dependency
cargo tree --locked -f '{p}: {f}' -i serde | grep -v '^$'
cargo tree --locked -f '{p}: {f}' -i <shared-dep> | grep -v '^$'

# Check a pure-logic crate for an unexpected std/alloc pull-in
cargo check --locked -p <no-std-crate> --no-default-features 2>&1 | grep 'std\|alloc'
```

Fix: declare `default-features = false` on every dependency of a `no_std` crate,
and verify with `cargo check --locked --no-default-features`. If a workspace test
binary needs a `std` feature, gate it behind a dev-dependency instead of a normal
dependency.

Reference: [Cargo feature resolution](https://doc.rust-lang.org/cargo/reference/resolver.html#features).

## Pitfall: workspace inheritance breaks target-specific features

**Severity: WARNING**

When you define a dependency in `[workspace.dependencies]` and reference it as
`foo = { workspace = true }` in a member crate, resolver v2 sometimes fails to
limit features to the current compilation target. The same dependency declared
directly in the member crate resolves correctly.

The symptom: a platform-specific feature turns on for all platforms. A
cross-compiled Android or iOS build then pulls in Linux-only or Windows-only code
that the NDK or SDK does not provide, and the link step fails with missing
symbols. A `#![forbid(unsafe_code)]` or `no_std` crate can break the same way.

Detection:

```bash
cargo tree --locked --target aarch64-linux-android -f '{p}: {f}' -i <dep>
cargo tree --locked --target aarch64-apple-ios     -f '{p}: {f}' -i <dep>
```

Compare the output with the host resolution. A feature that appears only on the
cross target - or that appears on the cross target and should not - confirms the
problem.

Workaround: for a dependency whose target-specific features matter, declare it
directly in the member crate under `[target.'cfg(...)'.dependencies]` instead of
inheriting it from the workspace.

Reference: Cargo issue #11779.
