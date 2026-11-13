# Rust 1.100 practical workflows

Date: 2026-11-13. This change builds on the Rust 1.100 migration in
`rust-1.100.0-2026-11.md`. It keeps the catalog on Rust 1.100.0, edition 2024.

## Scope and ownership

| Area | Owner | Permanent evidence |
| --- | --- | --- |
| Per-collection allocators | New `rust-allocators` skill | Allocation and resize failure, alignment, zero size, zeroing, retained collection contents, and raw ownership probes |
| Synchronous rollback at cancellation | `rust-async-internals`; general rollback stays in `rust-panic-safety` | A manually polled future: unpolled drop, `Pending` drop, error, success, and unwind |
| Compiler transitions | `checks/release_regressions.py` | Rust 1.99.1 versus 1.100.0: field capture, actual `Send` bound, destructor timing, never fallback on four editions, and `Infallible` coherence |
| Cargo policies | `cargo-workflows`, `rust-security`, `rust-lints` | Dependency lint matrix, JSON artifact selection, isolated sparse-registry publish age, and rustdoc table diagnostics |
| Smart-pointer mapping | `rust-hot-path` | Allocation counters and value, observer, weak-reference, panic, and drop checks for `Box::map`, `Rc::map`, and `Arc::map` |
| Platform workflows | `rust-performance`, `rust-wasm` | Real sample capture and measurement; deterministic profile replay; WASIp3 async clock and file capability acceptance |

The isolated loom fixture exercises `cfg(loom)`. The Release version passes;
the Relaxed version must fail at the publication assertion. This fixture uses
the harness lockfile's package versions and does not add a product crate.
Read `../checks/release-fixtures/README.md` for the transition matrix.

The catalog now has 51 skills. The new skill has one bundle, plugin, router,
catalog, and routing-case entry. Four evaluation prompts were authored from
its body without reading its description. No model routing score is claimed.

## Observations

- A publish-age exception selects the fresh package, and `cargo check --locked`
  preserves that resolution. A subsequent full `cargo update` can select the
  older eligible version. The guidance now distinguishes these operations.
- Smart-pointer allocation counts are measurements, not API guarantees. On
  aarch64 macOS with Rust 1.100.0, debug and optimized probes reported Box
  same/larger 0/1; Rc unique/shared/weak 0/1/1; Arc unique/shared/weak/larger
  0/1/1/1. The portable gate asserts ownership behavior, not those counts.
- Miri passed the allocator contract, raw ownership round trip, mapping lifecycle,
  and cancellation probes on aarch64-apple-darwin with nightly-2026-11-12
  (`rustc 1.102.0-nightly`, `3ef0c22cd`, 2026-11-11).
- Real sample PGO capture, conversion, consumption, and timing completed.
  The noisy shared-host result establishes no speedup or confirmed regression.
  Read [the platform report](rust-1.100-platform-workflows-2026-11.md) for measured
  values, source links, exact commands, and runtime limits.

## Validation and limits

The required command is `bash checks/check.sh`. It includes the catalog, routing
schema, unit tests, two example compilation passes, runnable probes, release
regressions, platform replay, outcome fixtures, and client discovery/install gates.
The CI compile job also installs Rust 1.99.1 for the small historical fixtures.

The catalog validator passes for 51 skills. The routing schema check passes for
204 prompts with three existing wording warnings. The release runner's six unit
tests and the sample-profile runner's seven unit tests pass. No baseline, ignore,
fragment, or size-ceiling exemption is added.

On Linux ARM64, the full invocation passed both x86_64 example type-check passes,
86 native behavior probes, 53 named lint probes, 30 compiler-transition
expectations, all Cargo and loom fixtures, WASIp3, sample-profile replay, and
nine outcome fixtures. Of 384 compile blocks, 382 build and two remain declared
fragments. All 79 expected compile failures match; the 21 ignored blocks remain
unchanged.

The full invocation was stopped during client installation: the client copied
ignored `checks/target` output into each plugin cache. Both client gates now use
the existing tracked-file export. A separate final `bash checks/check.sh --fast`
checks that fix and the complete catalog/client path. No Rust example changed
after the successful Rust gates. A clean-checkout fast run also verified all
eight plugin inventories for the first client.
The final fast run passed: both clients loaded all eight plugin inventories,
and all 343 routing phrases remained visible across the seven bundle installs.
The full-catalog install reports 240 of 343 phrases; that install exceeds the
listing budget by design and is not the recommended install path.

Miri covers the executed paths, not every allocator or foreign caller. The loom
model covers one publication protocol. WASIp3 checks one async clock and file
operation with a pinned runtime. Cross-architecture sample replay checks format
consumption and output only. Model-based routing, plugin evaluation, production
workloads, and a release tag remain separate acceptance steps.

## Primary sources

- [Rust 1.100 release](https://blog.rust-lang.org/2026/11/12/Rust-1.100.0/)
- [Allocator contract](https://doc.rust-lang.org/1.100.0/std/alloc/trait.Allocator.html)
- [DropGuard](https://doc.rust-lang.org/1.100.0/std/mem/struct.DropGuard.html)
- [Compiler and Cargo source links](../checks/release-fixtures/README.md#primary-sources)
- [Sample PGO and WASIp3 sources](rust-1.100-platform-workflows-2026-11.md#primary-sources)
