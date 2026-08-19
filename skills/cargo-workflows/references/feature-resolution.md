# Feature Resolution Pitfalls

Deep material for `cargo-workflows`: the two resolver behaviours that silently
change what a workspace crate compiles. Both are WARNING-severity. Both are
invisible until a shipped artifact grows code it must not contain.

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

Reference: [cargo feature unification pitfall - nickb.dev](https://nickb.dev/blog/cargo-workspace-and-the-feature-unification-pitfall/),
Cargo resolver documentation.

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
