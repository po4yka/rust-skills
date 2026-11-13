# Release regression inputs

Run `python3 checks/release_regressions.py` for every suite. `--suite compiler`,
`--suite cargo`, and `--suite loom` are diagnostic subsets, not full acceptance.
The runner reads the current pin from `checks/rust-toolchain.toml` and compares
language behavior with Rust 1.99.1. Missing tools, toolchains, or cached loom
packages fail the run. It does not install them or skip a suite.

## Compiler expectations

| Input | Rust 1.99.1 | Rust 1.100.0 |
| --- | --- | --- |
| `if-let-field.rs` | E0382 | Runs; the untouched field remains available |
| `if-let-send.rs` | E0277 | Compiles at the actual `Send` bound |
| `if-let-drop.rs` | Both fields drop with the closure | The captured field drops first; the untouched field drops at its enclosing scope |
| `never-fallback.rs` | Pre-2024 editions deny the compatibility lint; an explicit lint allow exposes unit fallback. Edition 2024 fails with E0277 | All editions fail with E0277 despite the old lint allow |
| `never-fallback.rs --cfg explicit` | Runs on all four editions | Runs on all four editions |
| `infallible-alias.rs` | E0658 | Runs with the irrefutable `Ok` pattern |
| `infallible-coherence.rs` | Both function-pointer impls compile | E0119 |

These observations describe the pinned transition. They are not a guarantee of
closure destructor order for unrelated patterns, or a recommendation to allow
the never-fallback lint. The explicit type is the application fix.

## Cargo and loom

The runner creates small Cargo packages in a temporary directory. They test
`unused_dependencies`, generated-artifact selection across profiles and features,
minimum publish age, and rustdoc table diagnostics. A loopback sparse registry
serves valid generated `.crate` archives with old, current, and missing `pubtime`
values. No public registry is contacted by these Cargo policy tests. Cargo home,
build output, and environment are isolated from user credentials and flags.

The loom crate uses `cfg(loom)` and contains no Tokio dependency. The runner
copies the harness lockfile, resolves its subset offline, and verifies that every
selected package version is in that lockfile. It executes the Release version
and requires the `broken` Relaxed version to fail with the publication assertion.
A bounded loom model does not prove behavior outside its modeled operations.

## Primary sources

- [Rust 1.100 compatibility notes](https://doc.rust-lang.org/1.100.0/releases.html#version-11000-2026-11-12)
- [Cargo lints](https://doc.rust-lang.org/1.100.0/cargo/reference/lints.html)
- [Cargo JSON messages](https://doc.rust-lang.org/1.100.0/cargo/reference/external-tools.html#json-messages)
- [Cargo publish age](https://doc.rust-lang.org/1.100.0/cargo/reference/resolver.html#publish-age)
- [Registry index and pubtime](https://doc.rust-lang.org/1.100.0/cargo/reference/registry-index.html)
- [Rustdoc table lint](https://doc.rust-lang.org/1.100.0/rustdoc/lints.html#invalid_markdown_table)
