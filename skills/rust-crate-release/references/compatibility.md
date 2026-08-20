# Release Compatibility Review

Use this reference when you classify a public crate release.
Compare the previous published source with the candidate.
Apply the repository's published compatibility policy before this default table.

## Version classification

| Candidate change | Default classification for `1.0.0` and later |
|---|---|
| Compatible bug fix, performance fix, or documentation fix | Patch |
| New compatible public item or opt-in feature | Minor |
| Remove, rename, or move a public item | Major |
| Add a variant to an exhaustive public enum | Major |
| Add a field to an exhaustive public struct or enum variant | Major |
| Add a required trait item or change a trait item signature | Major |
| Make a public trait no longer object safe | Major |
| Tighten a public generic bound | Major |
| Change a stable layout or ABI guarantee | Major |
| Require `std` after supporting `no_std` | Major |
| Remove a feature or move existing public API behind a feature | Major |
| Raise MSRV or remove a supported platform | Possibly breaking; follow the published policy |
| Add a defaulted trait item or an inherent method | Possibly breaking; inspect downstream overlap |

Cargo uses the left-most non-zero version component as its compatibility boundary.
For `0.y.z`, treat a change in `y` as the breaking-release position.
Treat each `0.0.z` release as incompatible with the other `0.0` releases.
Do not hide a breaking change in a patch release because the crate is below `1.0.0`.

## Public API checklist

Check these failure-prone changes explicitly:

- field visibility, field order, and layout guarantees;
- exhaustive structs, enums, and downstream matches;
- trait object safety and new required items;
- generic defaults, bounds, inferred types, and return-position `impl Trait` captures;
- blanket, foreign, inherent, and auto-trait implementations;
- function arity, safety, ABI, and panic contract;
- macro syntax, expansion paths, and exported helper names;
- re-export paths and feature-gated items;
- types from dependencies in public signatures;
- behavior, errors, and panics that the documentation promises.

A public item is not the complete public API.
Review public trait implementations and types that appear through re-exports.
Review generated macro output from a downstream crate context.
Review whether new inherent methods can collide with downstream trait methods.
Review whether a new impl changes method or type inference.

Run the repository's existing API compatibility tool when one is configured.
Do not add a release dependency only to replace this review.
Treat tool output as evidence, not as proof that behavior and macros are compatible.

## Feature compatibility

Treat feature names as public API.
A compatible release can usually add an opt-in feature.
Do not remove a feature in a compatible release.
Do not remove a feature from `default` when users can depend on its behavior.
Do not move an existing public item behind a feature in a compatible release.
Do not let enabling a feature break code that works without it.

An optional dependency creates an implicit feature with the same name by default.
Use `dep:<name>` under a stable user-facing feature when the dependency name is an internal
detail.

## MSRV and platform compatibility

Treat an MSRV increase as possibly breaking.
Apply the project's documented MSRV policy and announce the increase.
Verify all package targets and supported features on the declared MSRV.

Treat a new operating-system, linker, native-library, CPU-feature, or runtime requirement as a
compatibility change.
Do not infer cross-target support from a host build.

## Official references

- [Cargo SemVer Compatibility](https://doc.rust-lang.org/cargo/reference/semver.html)
- [Cargo Rust Version](https://doc.rust-lang.org/cargo/reference/rust-version.html)
- [Cargo Features](https://doc.rust-lang.org/cargo/reference/features.html)
