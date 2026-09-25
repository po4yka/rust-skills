# Catalog actualization 2026-09: research record

Date: 2026-09-24. Baseline: commit `8187a17`. Scope: the 44 skills under `skills/`, the compile
harness under `checks/`, and `scripts/validate-skills.py`.

This file records the primary sources and the decisions behind the 2026-09 edits, so that a
reviewer can check each change against its source. The evidence about LLM errors in Rust is in
[rust-pitfalls-and-llm-errors.md](rust-pitfalls-and-llm-errors.md). This file does not repeat it.

## 1. Scope, date, and method

| Step | What was done | Output |
|---|---|---|
| Research partitions | 14 partitions read primary sources on 2026-09-24: Rust releases 1.85 to 1.98.1 and the 1.99 beta; language semantics (two partitions); Cargo, lints, and tests; release and supply chain; unsafe and verification; async; Android and JNI; Apple and UniFFI; performance and observability; Wasm, embedded, CLI, and serde; Anthropic prompting; OpenAI prompting; Agent Skills spec and skills CLI. Each partition checked every catalog claim in its domain against a source or a local probe. | Findings with file and line, new material, conflicts, and an "Unresolved" list per partition |
| Binding decisions | One decision record resolved the conflicts between partitions and gave each cross-skill rule one owner. A decision overrides a partition finding. | Section 5 |
| Per-skill edit | One editor per skill applied the findings and the rubric in section 6. An adversarial reviewer in a separate context then checked the edit against the sources and the compile gate. | Edited `SKILL.md` and `references/` files |
| Cross-skill reconciliation | A catalog-wide pass removed duplicate rules, pointed each copy to its owner by skill name, and settled the conflicts that the per-skill pass exposed. | Section 5, rows E1 to E9 |
| Harness | Toolchain and dependency refresh, new validator rules, skills CLI pin. `bash checks/check.sh` was green on the new harness before the first skill edit. | Section 3 |

Evidence rules:

- A fact comes from a primary source: rust-lang release notes and changelogs, source code at a
  tag, vendor documentation, crate changelogs, or a RustSec advisory. Community summaries were
  not used.
- A probe is a local run on a named toolchain: `1.98.1`, `1.97.1`, `1.97.0`, `1.88.0`, or
  nightly 2026-05-15. A row that rests on a probe says so and names the toolchain.
- A stamp such as "measured on rustc 1.97.0" is provenance. An editor changed a stamp only after
  a re-run on 1.98.1.

Source keys used in the tables:

| Key | Resolves to |
|---|---|
| `R` | https://github.com/rust-lang/rust/blob/stable/RELEASES.md (same text: https://doc.rust-lang.org/stable/releases.html) |
| `rust#N` | https://github.com/rust-lang/rust/pull/N (GitHub redirects to the issue when N is an issue) |
| `cargo#N` | https://github.com/rust-lang/cargo/pull/N (GitHub redirects to the issue when N is an issue) |
| `Cargo CL` | https://doc.rust-lang.org/nightly/cargo/CHANGELOG.html |
| `Clippy CL` | https://github.com/rust-lang/rust-clippy/blob/master/CHANGELOG.md |
| `blog YYYY/MM/DD/slug` | https://blog.rust-lang.org/YYYY/MM/DD/slug/ |

## 2. Toolchain baseline

| Fact | Value | Source |
|---|---|---|
| Current stable | 1.98.1, released 2026-09-03. `rustc -V` shows `48a229cea 2026-09-01`, which is the commit date. | https://static.rust-lang.org/dist/channel-rust-stable.toml ; blog 2026/09/03/Rust-1.98.1 |
| Why not 1.98.0 | 1.98.0 can emit a trait-object vtable with a null function pointer (undefined behavior). 1.98.1 fixes it. The catalog tells readers never to pin 1.98.0. | rust#161441 ; blog 2026/09/03/Rust-1.98.1 |
| Harness diff 1.97.1 to 1.98.1 | Identical counts: 571 blocks (457 compile, 9 run, 61 `compile_fail`, 44 `ignore`), 325 of 457 clean, 0 suspects, 9 behavior probes pass, the CLI discovers 44 skills. Only two diagnostics changed wording: E0277 "expected a `Fn()` closure" became "expected an `Fn()` closure" (quoted in `rust-callback-bounds`, updated), and E0433 "too many leading `super` keywords" gained "within `crate`" (not quoted). | `bash checks/check.sh` on both pins |
| 1.99 | Due 2026-10-01 (1.99.0-beta.7 on 2026-09-19). Not treated as stable. Where 1.99 deprecates an API, the catalog teaches the replacement that is already stable and its MSRV (atomic `try_update`, 1.95). | Cargo CL "Cargo 1.99 (2026-10-01)"; https://static.rust-lang.org/dist/channel-rust-beta.toml |
| 1.100 | Due 2026-11-12, with a new `build-dir` layout. The catalog tells tools to read JSON messages or `cargo metadata`, not `target/` paths. | Cargo CL "Cargo 1.100" |

## 3. Harness and validator changes

| Change | Reason | Source |
|---|---|---|
| `checks/rust-toolchain.toml`: 1.97.1 to 1.98.1 | Current stable; see section 2. | Section 2 |
| Lock refresh: nix 0.31.3, uniffi 0.32.2, tokio 1.53.x, jni 0.22.x | The skills name these release lines. The examples must type-check against the versions a reader installs. | https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md ; https://github.com/jni-rs/jni-rs/blob/master/CHANGELOG.md |
| imbl `=7.0.1` pin removed; `imbl = "7.0.2"` | The pin existed only until imbl dropped `bitmaps`. 7.0.2 does that and moves to `imbl-sized-chunks` 0.2, which fixes RUSTSEC-2026-0292. | https://github.com/jneem/imbl/blob/main/CHANGELOG.md ; https://github.com/rustsec/advisory-db/blob/main/crates/imbl-sized-chunks/RUSTSEC-2026-0292.md |
| criterion stays 0.7 in the harness only | criterion 0.8 depends on `alloca`, whose build script needs a Linux C compiler, so the cross-host `x86_64-unknown-linux-gnu` type check breaks. The benchmark API the examples use is the same in 0.8. The skills name 0.8 as current. | https://github.com/criterion-rs/criterion.rs/blob/master/CHANGELOG.md |
| reqwest 0.13 with `default-features = false, features = ["json"]` | The default TLS stack pulls `aws-lc-rs`, whose C build breaks the same cross-host type check. The builder API is the same. | https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md |
| New: axum 0.8, hyper-util 0.1 (`full`), pin-project 1, syn 3 (`full`), quote 1, proc-macro2 1 | Blocks that use these crates were fragments or `rust,ignore`. They are now type-checked, and editors removed tags that existed only because a crate was missing. A non-proc-macro crate needs `extern crate proc_macro;` to name `proc_macro::TokenStream`. | https://github.com/dtolnay/syn/releases/tag/3.0.0 |
| Validator: `SKILL.md` over 500 lines fails | The Agent Skills spec recommends under 500 lines and about 5,000 tokens. Claude Code keeps only the first 5,000 tokens of a skill after compaction. Eight skills started above 500 lines; on 2026-09-24 all are at or below it. | https://agentskills.io/specification ; https://code.claude.com/docs/en/context-window |
| Validator: a Markdown link resolves from the file that holds it | 20 sibling links inside `references/` were never checked. A rename could break one silently. | https://agentskills.io/specification ("relative paths from the skill root") |
| Validator: a link that leaves the skill directory fails, and a code span that names `skills/<name>/...` fails | An install of one skill carries only its own directory, so a path into another skill is a dead link. Skills name each other by skill name. | https://agentskills.io/specification ; https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/skill-creator/SKILL.md |
| `scripts/test_validate_skills.py`: five new tests | The new rules need tests of their own: line limit, link resolution, missing sibling, cross-skill link, repository path. | This repository |
| skills CLI pin 1.5.23 to 1.7.0 | The gate must match what `npx skills add` gives a consumer as of 2026-09-24. `src/frontmatter.ts` is unchanged between the two versions, and 1.7.0 discovers 44 of 44 skills. | https://github.com/vercel-labs/skills/compare/v1.5.23...v1.7.0 |
| `check.sh` writes `discovered.txt` into its run directory, not `/tmp` | Two checkouts on one host could overwrite each other's file. The lock is per checkout. | This repository |

## 4. Rust and ecosystem changes that changed catalog guidance

Only changes that alter what an agent writes, runs, or recommends are listed. The full release
digest stayed in the session research notes, which are not in the repository.

| Change | Version or date | Primary source | Skills affected |
|---|---|---|---|
| `unsafe_code` fires on every unsafe attribute (`#[unsafe(no_mangle)]`, `export_name`, `link_section`); new message "usage of the unsafe `#[no_mangle]` attribute" | 1.98.0 | rust#157201 (probe 1.98.1) | rust-unsafe, rust-lints, rust-jni |
| Deny-by-default `invalid_runtime_symbol_definitions`; warn-by-default `c_void_returns` | 1.98.0 | rust#155521 ; rust#156379 | rust-unsafe, rust-embedded-no-std, rust-swift-ffi |
| `&mut` unsize coercion can shorten a lifetime in an invariant position | 1.98.0 | rust#149219 (probe 1.97.0 vs 1.98.1) | rust-variance |
| `lib/rustlib/etc/lldb_commands` removed; `command script import lldb_lookup.py` alone registers formatters; CodeLLDB >= 1.12.3 | 1.98.0 | rust#155336 ; https://github.com/vadimcn/codelldb/blob/master/CHANGELOG.md | rust-debugging |
| `{integer}::format_into` with `core::fmt::NumBuffer`; `std::fmt::NumBuffer` arrives only in 1.99 | 1.98.0 | R 1.98.0 ; rust#161430 | rust-hot-path |
| v0 symbol mangling is the default (`_R` prefix); legacy needs `-Z unstable-options` | 1.97.0 | rust#151994 | rust-debugging, rust-native-linking, rust-hot-path, rust-android-build, rust-performance |
| `build.warnings` / `CARGO_BUILD_WARNINGS=deny` denies warnings without a `RUSTFLAGS` cache bust | 1.97.0 | https://doc.rust-lang.org/stable/cargo/reference/config.html#buildwarnings | rust-lints, cargo-workflows, rust-android-build |
| `linker_messages` is warn-by-default and outside the `warnings` group | 1.97.0 | rust#153968 | rust-lints, rust-native-linking |
| Wasm targets no longer pass `--allow-undefined`; an undefined symbol is a link error | 1.96.0 | rust#149868 | rust-wasm |
| `assert_matches!` is stable (import it by path) | 1.96.0 | https://doc.rust-lang.org/stable/std/macro.assert_matches.html | rust-tdd, rust-pattern-semantics |
| `cfg_select!` replaces the `cfg-if` crate when the MSRV allows | 1.95.0 | https://doc.rust-lang.org/stable/std/macro.cfg_select.html | rust-macros, rust-crate-architecture |
| `if let` guards; guard temporaries live to the end of the arm body | 1.95.0 | rust#141295 ; https://doc.rust-lang.org/reference/destructors.html | rust-pattern-semantics |
| Atomic `update` / `try_update`; `fetch_update` is deprecated from 1.99 | 1.95.0; 1.99 | rust#148590 | memory-model, rust-discipline |
| JSON target specs need `-Z unstable-options` (nightly) | 1.95.0 | R 1.95.0 Compatibility Notes ; rust#150151 | rust-embedded-no-std |
| A raw-pointer cast cannot change the lifetime bound of a `dyn` type; `transmute` is not the fix | 1.94.0 | rust#136776 | rust-variance |
| Temporary lifetime extension through tuple struct and tuple variant constructors (`Some(&temp())`) | 1.89.0 | https://doc.rust-lang.org/reference/destructors.html#extending-based-on-expressions (probe 1.88.0 vs 1.98.1) | rust-borrow-semantics |
| `#[bench]` on stable fails with E0658; `#![feature(test)]` then fails with E0554 | 1.88.0 | rust#134273 (probe 1.98.1) | rust-performance |
| libtest `--nocapture` is deprecated for `--no-capture` | 1.88.0 | rust#139224 | rust-tdd, rust-debugging |
| `rust-lld` is the default linker only on `x86_64-unknown-linux-gnu`; lld hides archive-order bugs | 1.90.0 | blog 2025/09/01/rust-lld-on-1.90.0-stable ; https://lld.llvm.org/ELF/warn_backrefs.html | rust-native-linking, rust-performance |
| Trait upcasting to `&dyn Any` replaces `as_any` helpers | 1.86.0 | https://doc.rust-lang.org/reference/type-coercions.html#r-coerce.unsize.trait-upcast | rust-type-erasure |
| `compare_exchange` failure ordering is independent of the success ordering | 1.64.0 | rust#98383 | memory-model |
| Edition 2024 narrows `if let` scrutinee and tail-expression temporaries, so guards drop earlier (the old triage row had the direction backwards) | 1.85.0 | https://doc.rust-lang.org/edition-guide/rust-2024/temporary-if-let-scope.html | rust-borrow-semantics, cargo-workflows |
| Edition 2024 RPIT captures all in-scope lifetimes; the E0502 note points to `+ use<..>` on the callee | 1.85.0 | https://doc.rust-lang.org/edition-guide/rust-2024/rpit-lifetime-capture.html | rust-compiler-errors, rust-borrow-semantics |
| Resolver `"3"` is implied by edition 2024; a virtual workspace sets it itself | 1.85.0 | https://doc.rust-lang.org/cargo/reference/resolver.html#resolver-versions | cargo-workflows |
| Commit `Cargo.lock` for every package, libraries included | Cargo FAQ (current) | https://doc.rust-lang.org/cargo/faq.html#why-have-cargolock-in-version-control | cargo-workflows |
| `default-features = false` on a `workspace = true` entry is ignored when the workspace entry enables defaults (expected behavior, not a resolver bug); member override needs Cargo 1.99 and an edition-2024 member (RFC 3945, cargo#17126); earlier editions still ignore it with a warning | Cargo 1.99 (not stable) | https://github.com/rust-lang/cargo/issues/11779 ; Cargo CL "Cargo 1.99" | cargo-workflows |
| `cargo info` prefers the local workspace package; pass `--registry` even for crates.io | Cargo 1.94 | Cargo CL "Cargo 1.94" (#16358) | rust-crate-release |
| `cargo publish --dry-run -p a -p b` verifies an ordered set before the first upload | Cargo 1.90 | Cargo CL "Cargo 1.90" | rust-crate-release |
| rustdoc lints are enforced only by `cargo doc` | current | https://doc.rust-lang.org/rustdoc/lints.html (probe 1.98.1) | rust-lints, cargo-workflows, rust-crate-release |
| `clippy::string_to_string` was deprecated in Clippy 1.91, not 1.86 | Clippy 1.91 | https://github.com/rust-lang/rust-clippy/blob/master/clippy_lints/src/deprecated_lints.rs | rust-lints |
| Style edition 2024 changes import sort order; `style_edition`, not `rustfmt.toml` `edition`, selects the style | 1.85.0 | https://doc.rust-lang.org/edition-guide/rust-2024/rustfmt-version-sorting.html ; https://github.com/rust-lang/rustfmt/blob/master/Configurations.md#style_edition | rust-code-style, rust-lints, cargo-workflows |
| syn 3 is current; syn-2 code breaks on renamed items (`Type::BareFn`, `Signature::unsafety`, `Arm::guard`) | 3.0.0, 2026-07-18 | https://github.com/dtolnay/syn/releases/tag/3.0.0 | rust-macros |
| Require `imbl >= 7.0.2` | 2026-09-09 | https://github.com/jneem/imbl/blob/main/CHANGELOG.md ; RUSTSEC-2026-0292 | rust-copy-on-write |
| criterion 0.8 is current (MSRV 1.86, randomized stack layout) | 0.8.0, 2025-11-29 | https://github.com/criterion-rs/criterion.rs/blob/master/CHANGELOG.md | rust-performance |
| `cargo flamegraph` has no `--locked`; profile a `profiling` profile with debug info, not a stripped release build | flamegraph 0.6.14 | https://github.com/flamegraph-rs/flamegraph/blob/main/src/bin/cargo-flamegraph.rs ; https://github.com/mstange/samply | rust-performance |
| `opt-level = "s"` disables loop vectorization, like `"z"`; cross-crate auto-inlining applies only to tiny leaf functions | 1.98.1 source | https://github.com/rust-lang/rust/blob/1.98.1/compiler/rustc_codegen_ssa/src/back/write.rs ; rust#116505 | rust-hot-path, rust-performance |
| Android `panic = "abort"` copies the panic message into the tombstone "Abort message" | 1.98.1 source | https://github.com/rust-lang/rust/blob/1.98.1/library/panic_abort/src/android.rs | rust-panic-safety, rust-debugging, rust-observability |
| Miri: Stacked Borrows is the default, Tree Borrows is more experimental; `-Zmiri-symbolic-alignment-check` makes alignment checks seed-independent; `-Zmiri-num-cpus` does not change thread handling | Miri master | https://github.com/rust-lang/miri/blob/master/README.md (probe nightly 2026-05-15) | rust-sanitizers-miri, rust-unsafe |
| loom: library code imports loom under `cfg(loom)`; ordinary tests panic outside a loom model | loom 0.7 | https://github.com/tokio-rs/loom/blob/master/README.md (probe 1.98.1, loom 0.7.2) | rust-test-tools, memory-model |
| Hand-kept tokio version floors were wrong; RUSTSEC-2025-0023 patches several ranges | 2025 | https://rustsec.org/advisories/RUSTSEC-2025-0023.html | rust-async-internals |
| `#[trait_variant::make]` adds a `Send` variant only; it does not make a trait dyn-compatible | trait-variant 0.1.3 | https://docs.rs/trait-variant/latest/trait_variant/attr.make.html ; https://docs.rs/dynosaur/latest/dynosaur/ (probe 1.98.1: E0038) | rust-async-internals |
| reqwest 0.13 defaults to rustls with aws-lc-rs and has no default timeout; hyper `header_read_timeout` needs a `Timer`, and `axum::serve` 0.8.x sets no timer (unreleased main enables hyper's default header-read timeout) | reqwest 0.13; hyper 1; axum 0.8.9 | https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md ; https://docs.rs/hyper/latest/hyper/server/conn/http1/struct.Builder.html#method.header_read_timeout ; https://github.com/tokio-rs/axum/blob/axum-v0.8.9/axum/src/serve/mod.rs | rust-networking |
| sqlx 0.9: `query*` takes `impl SqlSafeStr` (a runtime `String` needs `AssertSqlSafe`); before 0.9 a drop during `BEGIN` could return an open transaction | 0.9.0 | https://github.com/launchbadge/sqlx/blob/v0.9.0/CHANGELOG.md ; https://github.com/launchbadge/sqlx/pull/3980 | rust-database |
| serde_json parses an out-of-range integer into `Value` as a lossy `f64`, with no error | serde_json 1.0.151 | https://github.com/serde-rs/json/blob/master/Cargo.toml (`arbitrary_precision`, `float_roundtrip`; probe 1.98.1, serde_json 1.0.151) | rust-serde |
| Embassy 0.10 renames `arch-*` features to `platform-*`; a task call returns a `Result` | Embassy 0.10 | https://github.com/embassy-rs/embassy/blob/main/embassy-executor/CHANGELOG.md | rust-embedded-no-std |
| OpenTelemetry SDK batch processors run on their own thread and do not enforce export timeouts | opentelemetry_sdk 0.28+ | https://github.com/open-telemetry/opentelemetry-rust/blob/main/opentelemetry-sdk/CHANGELOG.md | rust-observability |
| cargo-deny 0.20: `--config` is a root option, `--offline` replaces `check --disable-fetch`, `skip = [{ crate = "name@1.2.3", reason = "..." }]`; the `unsound` scope key needs 0.19 | 0.20.0, 2026-07-09 | https://github.com/EmbarkStudios/cargo-deny/pull/881 ; https://github.com/EmbarkStudios/cargo-deny/blob/main/CHANGELOG.md | rust-security, cargo-workflows, rust-lints |
| `cargo audit fetch` does not exist | cargo-audit 0.22.2 | https://github.com/rustsec/rustsec/tree/main/cargo-audit | rust-security |
| crates.io publishes a RustSec advisory for every crate it removes for containing malware, and no longer posts a blog entry for each one | 2026-02-13 | blog 2026/02/13/crates.io-malicious-crate-update | rust-security |
| crates.io Trusted Publishing (OIDC token, 30-minute lifetime); `pull_request_target` and `workflow_run` are blocked | 2025-07; 2026-01 | https://crates.io/docs/trusted-publishing ; blog 2026/01/21/crates-io-development-update | rust-crate-release, rust-security |
| docs.rs builds only the default target unless `targets` is set | 2026-05-01 | blog 2026/04/04/docsrs-only-default-targets | rust-crate-release |
| `cargo miri` wrote the environment into `target/`; a job that writes a pull-request-readable cache must hold no secrets | 2026-09-21 | blog 2026/09/21/github-actions-leaking-secrets-when-miri-output-is-cached | cargo-workflows, rust-sanitizers-miri, rust-crate-release |
| Node 20 removed from GitHub Actions runners; use node24 majors pinned to a commit SHA | 2026-09-23 | https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/ | cargo-workflows, rust-test-tools |
| jni 0.22: `JNI_OnLoad` takes `*mut jni::sys::JavaVM`; `#[jni_mangle]` and `native_method!` replace hand-typed `Java_*` names; 0.22.0 and 0.22.1 are yanked | jni 0.22.2+ | https://github.com/jni-rs/jni-rs/blob/master/CHANGELOG.md (probe 1.98.1) | rust-jni, rust-panic-safety, rust-unsafe |
| NDK r30 is the LTS; the 16 KB rule covers 64-bit ABIs of apps that target API 35+; Play blocks updates from 2027-02-01; 16 KB backcompat mode exists | 2026-09-08; page updated 2026-09-16 | https://developer.android.com/guide/practices/page-sizes ; https://developer.android.com/ndk/downloads | rust-android-build |
| App Store uploads need Xcode 26 and the iOS 26 SDK since 2026-04-28; Xcode 27 runs on Apple silicon only | 2026 | https://developer.apple.com/news/upcoming-requirements/ ; https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes | rust-ios-build, uniffi-packaging-versioning, cargo-workflows |
| `cc` falls back to the SDK version when `IPHONEOS_DEPLOYMENT_TARGET` is unset, so C objects in the Rust archive can target a newer iOS | cc current | https://github.com/rust-lang/cc-rs/blob/main/src/lib.rs | rust-ios-build, uniffi-packaging-versioning, cargo-workflows |
| UniFFI: Kotlin needs >= 0.32.1 (checksum fixes on ARM32 and AArch64); `--library` has no effect since 0.31; 0.32 `--config` is global; `&[u8]` maps to a direct `ByteBuffer` | 0.32.1, 2026-09-08 | https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md | uniffi-boundary, uniffi-packaging-versioning, rust-jni |
| Swift 6.2 default actor isolation can make callbacks `@MainActor` | Swift 6.2 / Xcode 26 | https://github.com/swiftlang/swift-evolution/blob/main/proposals/0466-control-default-actor-isolation.md | rust-swift-ffi, ffi-error-progress-cancel, uniffi-boundary, uniffi-packaging-versioning |
| Rust Wasm output uses post-MVP features by default; validate with `wasm-tools validate --features=...` | 1.82; 1.87 | https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html | rust-wasm |
| wasm-bindgen CLI needs the exact crate version; `getrandom` needs `wasm_js`; `wasm32-wasip3` is not a stable target | current | https://github.com/wasm-bindgen/wasm-bindgen/blob/main/crates/cli-support/src/wit/mod.rs ; https://github.com/rust-random/getrandom ; https://doc.rust-lang.org/nightly/rustc/platform-support/wasm32-wasip3.html | rust-wasm |

## 5. Cross-skill ownership decisions

The owner holds the full rule. Every other skill keeps a one-line pointer by skill name.

| # | Topic | Decision | Owner | Primary source |
|---|---|---|---|---|
| C1 | `Cargo.lock` | Commit it for every package; add a scheduled latest-dependencies lane; `--locked` everywhere else | cargo-workflows | https://doc.rust-lang.org/cargo/faq.html#why-have-cargolock-in-version-control |
| C2 | `--all-features` | Only when features are additive; else a feature matrix or `cargo hack --each-feature` | cargo-workflows | https://doc.rust-lang.org/cargo/reference/features.html |
| C3 | cargo-deny policy | Full `deny.toml` lives in one reference; >= 0.20 CLI form; `multiple-versions` target `deny` with reviewed `skip` | rust-security | https://github.com/EmbarkStudios/cargo-deny/pull/881 |
| C4 | Advisory floors | No hand-kept vulnerable-version tables; gate with `cargo deny check advisories` or `cargo audit` | rust-security | https://rustsec.org/advisories/RUSTSEC-2025-0023.html |
| C5 | GitHub Actions | Pin to a full SHA with a version comment; node24 majors | cargo-workflows | https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/ |
| C6 | Warnings as errors | Keep `cargo clippy ... -- -D warnings`; `CARGO_BUILD_WARNINGS=deny` replaces `RUSTFLAGS=-Dwarnings`; `linker_messages` is outside `warnings` | rust-lints | https://doc.rust-lang.org/stable/cargo/reference/config.html#buildwarnings |
| C7 | Lint suppression | `#[expect(lint, reason = "...")]` first; `#[allow]` only where `expect` cannot work, with a reason | rust-lints | blog 2024/09/05/Rust-1.81.0 |
| C8 | `unwrap` / `expect` | `.expect("<invariant>")` allowed in non-test code; state a lock-poisoning policy | rust-discipline | https://doc.rust-lang.org/nightly/std/sync/struct.PoisonError.html |
| C9 | `Iterator::for_each` | A `disallowed-methods` team default with its reason; examples use `for` | rust-code-style | Editorial; https://rust-lang.github.io/rust-clippy/main/index.html#needless_for_each |
| C10 | Visibility, module layout | Private first, `pub(crate)`, `pub(super)` for a parent helper; `name.rs` + `name/` | rust-code-style | Editorial |
| C11 | Miri model policy | Stacked Borrows first; Tree Borrows as extra evidence only; flags by risk; quote a message only when re-measured with its nightly date; FFI stubs must dereference the stored pointer | rust-sanitizers-miri | https://github.com/rust-lang/miri/blob/master/README.md |
| C12 | Loom setup | `[target.'cfg(loom)'.dependencies]`, check-cfg, run only loom targets; no `loom` feature | rust-test-tools | https://github.com/tokio-rs/loom/blob/master/README.md |
| C13 | Panic at a C ABI boundary | Since 1.81 a panic that reaches a non-unwinding ABI aborts; `catch_unwind` when the caller needs an error; foreign unwind into a non-unwind ABI is UB | rust-panic-safety | https://doc.rust-lang.org/std/panic/fn.catch_unwind.html ; blog 2024/09/05/Rust-1.81.0 |
| C14 | `JNI_OnLoad` on jni 0.22 | Raw `*mut jni::sys::JavaVM` plus `JavaVM::from_raw`; keep `improper_ctypes_definitions` at its default | rust-jni | https://github.com/jni-rs/jni-rs/blob/master/CHANGELOG.md |
| C15 | Android packaging | NDK r30 LTS; 16 KB scope and 2027-02-01 block; 32-bit alignment is optional policy; a user `--version-script` does not restrict Rust cdylib exports (probe 1.98.1, NDK r30 lld), so gate the dynsym table | rust-android-build | https://developer.android.com/guide/practices/page-sizes |
| C16 | Apple packaging | XCFramework and SwiftPM mechanics; `x86_64-apple-ios` optional; Xcode 26+ uploads; explicit `IPHONEOS_DEPLOYMENT_TARGET`; check archives with `otool -l` | rust-ios-build | https://developer.apple.com/news/upcoming-requirements/ |
| C17 | UniFFI | 0.32.x line; Kotlin >= 0.32.1; drop `--library`; global `--config`; `&[u8]` to direct `ByteBuffer`; Swift 6.2 isolation | uniffi-boundary (API), uniffi-packaging-versioning (versions) | https://github.com/mozilla/uniffi-rs/blob/main/CHANGELOG.md |
| C18 | Job registry and cancellation | One design: reserve, register, cancel with pre-cancel and TTL; recover poison with `into_inner` on non-throwing exports | ffi-error-progress-cancel | https://mozilla.github.io/uniffi-rs/latest/swift/overview.html |
| C19 | Async callbacks | `F: AsyncFn(&T) -> R` when the future need not be `Send + 'static`; a boxed future across `spawn` or `dyn`; `trait_variant` does not give dyn compatibility | rust-async-internals | blog 2025/02/20/Rust-1.85.0 ; https://docs.rs/dynosaur/latest/dynosaur/ |
| C20 | Noop waker | `std::task::Waker::noop()` (1.85) | rust-async-internals | https://doc.rust-lang.org/stable/std/task/struct.Waker.html#method.noop |
| C21 | Blocking in async | One table | rust-async-internals | Editorial |
| C22 | serde_json facts | Key order and `preserve_order` unification; `float_roundtrip`; `arbitrary_precision`; big integers through `Value` become `f64` | rust-serde | https://github.com/serde-rs/json/blob/master/Cargo.toml |
| C23 | Atomics API | Teach `update` / `try_update` (1.95); `fetch_update` only for MSRV < 1.95; failure ordering independent since 1.64 | memory-model | rust#148590 ; rust#98383 |
| C24 | Symbol mangling | v0 default since 1.97; update `_ZN` greps and demangler advice | rust-debugging | rust#151994 |
| C25 | Edition migration | `cargo fix --edition` workflow; 2024 narrows temporary scopes | cargo-workflows | https://doc.rust-lang.org/edition-guide/rust-2024/temporary-if-let-scope.html |
| C26 | Golden files | Mechanics in one skill; `rust-tdd` keeps blessing rules in brief | rust-test-tools | Editorial |
| C27 | libtest flag | `--no-capture` | rust-tdd | rust#139224 |
| C28 | Resolver | Edition 2024 implies `"3"`; a virtual workspace sets it | cargo-workflows | https://doc.rust-lang.org/cargo/reference/resolver.html#resolver-versions |
| C29 | Cargo-internal paths | Do not parse `target/<profile>/deps`; use `--emit`, JSON messages, or `cargo metadata` | cargo-workflows | https://doc.rust-lang.org/stable/cargo/reference/config.html#buildbuild-dir ; Cargo CL "Cargo 1.100" |
| C30 | Cross-skill references | By skill name only, "when it is installed" | all | https://agentskills.io/specification |
| C31 | Differential testing | A port with a reference implementation gets a differential fuzz or property target, with non-ASCII and invalid UTF-8 input | rust-test-tools | [evidence map](rust-pitfalls-and-llm-errors.md) |
| C32 | Tests exercise the target | A new test calls the changed function and asserts on its result; mutation testing for critical changes | rust-tdd | [evidence map](rust-pitfalls-and-llm-errors.md) |
| C33 | Compile-error repair | No `unwrap()`, nightly `#![feature]`, new crate, or `unsafe` as a fix; for E0432/E0433 check `use std::...` first, then confirm the crate name | rust-compiler-errors | [evidence map](rust-pitfalls-and-llm-errors.md) |
| C34 | Prompt rules vs enforcement | A written rule is not enforcement; use `#![forbid(unsafe_code)]`, a lint level, or CI | rust-unsafe | https://doc.rust-lang.org/rustc/lints/listing/allowed-by-default.html#unsafe-code ; https://code.claude.com/docs/en/hooks-guide |
| C35 | criterion | 0.8 is current; the catalog API is unchanged from 0.7 | rust-performance | https://github.com/criterion-rs/criterion.rs/blob/master/CHANGELOG.md |
| C36 | Profiling builds | `[profile.profiling]` inherits release with debug info and no strip; build with `--locked` first (`cargo flamegraph` has no `--locked`); `RUSTFLAGS` and `CARGO_ENCODED_RUSTFLAGS` both replace config-file rustflags | rust-performance | https://github.com/mstange/samply ; https://github.com/flamegraph-rs/flamegraph |
| C37 | Panic-report block | One privacy-safe block; on Android a panic message reaches the tombstone | rust-panic-safety | https://github.com/rust-lang/rust/blob/1.98.1/library/panic_abort/src/android.rs |
| C38 | Benchmark gating | Harness setup and regression gates in one skill | rust-performance | Editorial |
| C39 | `#[instrument]` | `skip_all` plus explicit `fields(...)` | rust-observability | Editorial (privacy default) |
| C40 | Subscriber in a cdylib | The outermost bootstrap `cdylib` installs the subscriber; one `log` logger per process | rust-observability | Crate source read, no URL recorded: tracing-subscriber 0.3.23 `util.rs` `try_init`; android_logger 0.15.1 `init_once` |
| C41 | LLDB | `command script import .../lldb_lookup.py` alone; CodeLLDB >= 1.12.3 | rust-debugging | rust#155336 |
| C42 | Optimization facts | `"s"` and `"z"` disable loop vectorization; auto-inlining limits; `make_mut` needs `T: CloneToUninit + ?Sized` | rust-hot-path | https://github.com/rust-lang/rust/blob/1.98.1/compiler/rustc_codegen_ssa/src/back/write.rs ; https://doc.rust-lang.org/stable/std/sync/struct.Arc.html#method.make_mut |
| C43 | Android rustflags block | One per-target block; profiling additions live in rust-performance | rust-android-build | Editorial |
| E1 | `#![forbid(unsafe_code)]` | Add it to every crate with no hand-written `unsafe` | rust-unsafe | https://doc.rust-lang.org/rustc/lints/listing/allowed-by-default.html#unsafe-code |
| E2 | Crate-root unsafe lint list | One home; rust-lints keeps the workspace floor and points to it | rust-unsafe | Editorial |
| E3 | Exact `=` requirements | Only for tightly coupled pairs (a crate and its proc-macro companion) | rust-security | https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html |
| E4 | Lock diffs | Commit with the manifest change that caused it; a full `cargo update` is its own change; MSRV repair re-resolves one dependency | cargo-workflows | https://doc.rust-lang.org/cargo/reference/resolver.html#rust-version |
| E5 | FFI paths Miri cannot run | ASan on the host, or HWASan / MTE on a device; `cargo careful` adds std precondition checks only | rust-sanitizers-miri | https://developer.android.com/ndk/guides/hwasan ; https://github.com/RalfJung/cargo-careful#readme |
| E6 | rustdoc gate | `cargo doc --no-deps` with `-D warnings`; others point to it | rust-lints | https://doc.rust-lang.org/rustdoc/lints.html |
| E7 | cargo-deny commands | Every command uses `cargo deny --config deny.toml --locked check ...` | rust-security | https://github.com/EmbarkStudios/cargo-deny/pull/881 |
| E8 | JNI entry points | No `pub` on raw-pointer `extern "system"` exports; one `JNI_OnLoad` template; `#[jni_mangle]` or `native_method!` on 0.22 | rust-jni | https://rust-lang.github.io/rust-clippy/main/index.html#not_unsafe_ptr_arg_deref |
| E9 | Loom dependency kind | Correction of C12: a target dependency, not a dev-dependency | rust-test-tools | https://github.com/tokio-rs/loom/blob/master/README.md |

## 6. Prompting and skill-design rubric

Classes: **O** = official guidance from a vendor or the Agent Skills spec; **G** = general agent
design that the official material supports; **E** = a repository editorial choice.

Source keys:

| Key | Source |
|---|---|
| A1 | Claude Code best practices, https://code.claude.com/docs/en/best-practices |
| A2 | Prompting best practices, https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices |
| A3 | Prompting Claude Opus 5, https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 |
| A4 | Skill authoring best practices, https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices |
| A5 | Claude Code skills, https://code.claude.com/docs/en/skills ; settings reference, https://code.claude.com/docs/en/settings-reference ; context window, https://code.claude.com/docs/en/context-window |
| O1 | Rethinking skills and prompts for GPT-6 Astra, https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra |
| O2 | Latest-model prompting guide, https://developers.openai.com/api/docs/guides/latest-model |
| O3 | Codex build skills, https://learn.chatgpt.com/docs/build-skills ; catalog renderer, https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/render.rs |
| O4 | Codex skill-creator (2026-08-13), https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/skill-creator/SKILL.md |
| O5 | Testing skills with evals, https://developers.openai.com/blog/eval-skills |
| S1 | Agent Skills specification, https://agentskills.io/specification |
| S2 | Agent Skills best practices, https://agentskills.io/skill-creation/best-practices ; optimizing descriptions, https://agentskills.io/skill-creation/optimizing-descriptions |

| Principle as encoded in the catalog | Class | Anthropic / spec | OpenAI |
|---|---|---|---|
| Put the task and the strongest triggers in the first ~150 characters of the description | O | A5 "Put the key use case first" | O3 "Front-load the key use case and trigger words" |
| One clause of scope; intent categories over keyword lists; keep exact paste tokens (error codes, lint, tool, crate names) | O | S2 (no keywords from failed queries) | O1 "as short as possible"; O4 no capability lists or catch-alls |
| A "not for X; use Y" boundary only where a sibling misroute is likely | O | S2 (state what the skill does not do) | O4 "only when they prevent likely misrouting" |
| Description length 300-600 characters; over 700 needs a reason | E | S1 hard limit 1,024 | - |
| "Use when" plus a gerund; no "you" | E | A4 third person; S2 imperative | - |
| No keyword added only to pass a routing case | O | S2 "that's overfitting" | - |
| No body "When to use" section | O | A4: routing reads the description only | O4 "Keep information in one place" |
| `SKILL.md` under 500 lines (enforced) and near 5,000 tokens; gotchas, verifiers, escalation first | O | S1; A5 (compaction keeps the first 5,000 tokens) | O4 "A large upper bound is not a target" |
| Each reference linked from `SKILL.md` with a "Read ... when" condition; one level deep; contents list over 100 lines | O | A4; S2 | O4 "explain when it should be read" |
| Name another skill by name only | O | S1 relative paths | O4 only when available in the target environment |
| No "before every task" reading or command mandates | O | A1 scope investigations narrowly | O1 docs before every edit are excessive |
| Absolute language only for a correctness, safety, ABI, data-loss, or release hazard, with a reason | O | A2 dial back aggressive language; A1 emphasis dilution | O4 absolute language only when correctness or safety requires it |
| Uniform severity labels removed | G | A1 "If you emphasize many lines, none of them stands out"; A2 dial back aggressive language; no measurement | No vendor measurement |
| Mark a team preference as a default with its reason | O | S2 pick a default | O4 no personal preference as a universal requirement |
| No claims about how a model behaves | O | A2 model-specific advice is measured on that model | O1 guidance for one model can overconstrain another |
| Harness features (subagents, nightly, nextest, devices) are conditional with a fallback | O | A5 Claude Code-only features | O4 delegation only when available and authorized |
| Remove generic advice unless it targets a documented LLM failure class | O | A4 "Claude is already very smart"; S2 | O4 "Assume Codex is already capable" |
| One home per rule; no internal contradictions | O | A5 recurring token cost | O2 conflicting guidance can block work |
| One-clause reason next to a non-obvious rule | O | A2 context and motivation | S2 explain why |
| Name the objective verifier, when it runs, and what green does not prove; proportional scope | O | A1 give a check it can run; A3 remove "double-check" | O2 calibrate testing to the change |
| Plans only where the domain needs them | O | A1 skip the plan for a one-sentence diff | O2; O4 process only when the process matters |
| Approval gates only before irreversible or external actions | O | A2 confirm hard-to-reverse actions | O1, O2 approval as the final step |
| Fixed step sequence where the process is the product (TDD, release gate) | G | A4 checklists for complex workflows | O4 |
| Enforce a zero-exception rule with a lint or CI, not prose | G | A1 hooks are deterministic | - |
| ASD-STE100 Simplified Technical English | E | - | - |

Where the vendors differ, the catalog encodes the shared intent, not a vendor interface:

- Truncation: Claude Code drops whole descriptions of the least-used skills when the listing
  exceeds its budget (A5). Codex keeps the first N characters of each description (O3). Both
  reward a front-loaded description. The skills contain no vendor budget constant.
- Point of view: A4 asks for third person; S2 shows an imperative. "Use when adding ..."
  satisfies both.
- Length: S2 says "err on the side of being pushy"; O1 says "as short as possible". The catalog
  keeps descriptions short and front-loaded, and uses the routing evaluation (section 7) to
  check for under-triggering.
- Verification: A2 recommends a final verification step for earlier models; A3 says to remove it
  for Opus 5. The catalog states objective completion criteria once and adds no self-check step.
- Frontmatter: only the three spec keys. No Claude Code `when_to_use` key (A5 says uploads reject
  it), and no Codex `agents/openai.yaml` file.

Deliberately not encoded (model-snapshot advice): "CRITICAL: you MUST" or "if in doubt, use"
triggers; "be thorough, explore everything"; "double-check" or verifier-subagent mandates;
"write out your reasoning"; periodic status reports; damping such as "do not verify" or "do not
delegate"; effort keywords (`ultrathink`); persistence or early-stop nudges tuned to one model;
Codex budget numbers (2 %, 8,000 characters) as instructions.

## 7. Routing evaluation

Measured by this repository on 2026-09-24.

Method:

- 176 prompts: 132 positive (three per skill) and 44 near-miss (one per skill, where the correct
  answer is a sibling skill, or "none" for 2 prompts). 4 prompts accept an alternate skill. The
  prompts were written from the skill bodies at `8187a17`, blind to the descriptions.
- Evaluator: Claude Opus 5.5 (`claude-opus-5-5`) in a prompt that simulates the skill-selection
  step, not the skill tool of a real client. It could answer "none".
- The evaluator saw only the skill names and descriptions. It gave a first and a second choice
  for each prompt. 8 batches of 22 prompts, 2 runs each: 16 evaluator runs per condition, so
  every prompt was scored twice.
- Conditions: HEAD, intermediate (after the per-skill pass), and final descriptions, each complete
  or cut to its first 150 characters.
- Top-1 counts the first choice when it is the expected skill (or an accepted alternate).
  Positive top-2 is 1.000 in all four conditions.

| Descriptions | Length | Positive top-1 | Near-miss top-1 | Near-miss top-2 |
|---|---|---|---|---|
| HEAD | full | 0.985 | 1.000 | 1.000 |
| Intermediate | full | 1.000 | 1.000 | 1.000 |
| Final | full | 1.000 | 0.989 | 1.000 |
| HEAD | first 150 characters | 1.000 | 0.920 | 0.989 |
| Intermediate | first 150 characters | 1.000 | 0.932 | 0.977 |
| Final | first 150 characters | 1.000 | 0.932 | 0.977 |

Description size: HEAD 28,561 characters in total (mean 649, max 1,015); intermediate 22,293
(mean 507, max 704); final 22,253 (mean 506, max 804), 22 % smaller than HEAD. The one final
description over 700 characters is `rust-compiler-errors` (804). Reason: its error codes and quoted
rustc messages are paste tokens, and its "Not for" clause routes four cases to sibling skills.

Misses: at HEAD with full descriptions, one observability prompt went to `rust-debugging` and
one pattern prompt went to `rust-compiler-errors`, in both runs. With the final full
descriptions, one near-miss answer in one run (an event-loop borrow question that also fits
`rust-compiler-errors`) missed. With the 150-character cut, every set missed the same ambiguous
near-misses (an `unsafe impl Send` review that fits both `rust-send-sync` and `rust-unsafe`, and an
async callback bound that fits both `rust-callback-bounds` and `rust-async-internals`).

Result: the shorter descriptions kept routing accuracy and cut the listing by 22 %. This shows no
regression. It does not prove an improvement.

Limits:

- One model family was the evaluator, and the same family wrote the descriptions and the prompts.
  Other clients and models can route differently.
- The selection was an explicit question with a "none" option. It says little about
  under-triggering in a client, where the agent loads a skill only if it decides to while it works.
- Ceiling effect: with full descriptions both sets score at or near 1.0, so the test cannot rank
  them.
- A near-miss label can be ambiguous: the sibling that the evaluator picked is sometimes
  defensible.
- A 150-character cut only approximates runtime truncation. Codex sizes the kept prefix from a
  shared budget; Claude Code drops whole descriptions instead.
- Four prompts per skill and two runs per prompt are a small sample. No with-skill and
  without-skill task evaluation was run.
- The scorer and the raw answers are session artifacts, not repository files.

## 8. Points that primary sources could not settle

- Miri and sanitizer messages were re-measured only on nightly 2026-05-15. A later nightly can
  change the wording.
- Device-only claims were not run on a device: the page-sizes RELRO arithmetic on a 16 KB
  device, the order of ART's thread-exit warning against the jni 0.22 TLS detach, the UniFFI
  AArch64 checksum range, Apple EMTE for a Rust staticlib, and v0-mangled frames in Play Console
  symbolication.
- The cargo-deny >= 0.20 CLI form was not run locally; the installed binary is 0.19.0. The form
  comes from the 0.20.0 changelog and PR 881.
- `SKILL.md` token size: no tokenizer was run, and the count depends on the estimator. After the
  final progressive-disclosure pass, every `SKILL.md` is at most 21,145 bytes (≈5,300 tokens by
  bytes / 4); 15 of 44 are slightly above 20,000 bytes, where the editors stopped rather than move
  a triage row, gotcha, or verifier out of the entrypoint. All `SKILL.md` files together are
  846,210 bytes (HEAD: 890,436). Rust code tokenizes denser than prose, so a real tokenizer can
  count more.
- `style_edition`: the Rust Style Guide says style edition 2024 is nightly-only, rustfmt
  `Configurations.md` marks the key "Stable: No", and the Edition Guide documents it for 2024.
  Stable 1.98.1 `cargo fmt` applies it with no warning (probe).
- docs.rs targets: the 2026-04-04 blog announces default-target-only builds, but the live
  metadata page still lists five default targets. Setting `targets` is correct in both cases.
- Play timeline: the 2025 blog gives 2025-11-01; the page-sizes page gives 2027-02-01 as the
  update block. No Play Console page reconciles them.
- Cargo docs disagree with the changelog on `cargo fix` target selection (1.89) and on
  `min-publish-age` ("Respected as of 1.100+" against "nightly only").
- Node 20 actions after 2026-09-23: GitHub says "Runners now use Node 24 for JavaScript
  actions", so every JavaScript action runs on Node 24. GitHub does not say whether a `node20`
  action with Node 24 incompatibilities fails.
- crates.io provenance: no source says crates.io stores Sigstore attestations for trusted
  publishing.
- Return type notation: the tracking issue is open; no version can be stated.
- `wasm-opt` defaults for post-MVP features, and the stable date of `wasm32-wasip3`, rest on an
  open issue and the nightly rustc book only.
- cargo-semver-checks 0.50.0 against 1.98.1 rustdoc JSON was not confirmed.
- Numeric factors with no primary source: Miri and sanitizer slowdowns, `cargo careful` 2-3x,
  the 80 % mutation-score threshold, attach cost, and the author's own benchmark tables.
- Prompting: no source measures the effect of "you" in a description or of in-body severity
  labels. Dropping "you" is an editorial choice (class E). Removing uniform severity labels is
  general agent design (class G) that rests on A1 and A2, with no measurement.
