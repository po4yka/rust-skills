# rust-skills

Twenty-one agent skills for production Rust work: unsafe code review, atomics, FFI boundaries,
sanitizers, profiling, lint policy, and supply-chain auditing. Each skill is a reference sheet
for a coding agent, not a tutorial. The skills are generalized from two private production
codebases — an Android application with a Rust networking core, and a cross-platform Rust map
engine — so each one carries concrete commands, flags, thresholds, and triage tables instead of
general advice.

[![skills.sh](https://skills.sh/b/po4yka/rust-skills)](https://skills.sh/po4yka/rust-skills)

## Install

Install the full catalog into the current project:

```bash
npx skills add po4yka/rust-skills
```

Install one skill:

```bash
npx skills add po4yka/rust-skills --skill rust-unsafe
```

List the catalog without installing anything:

```bash
npx skills add po4yka/rust-skills --list
```

Read one skill as a prompt, without installing it:

```bash
npx skills use po4yka/rust-skills@rust-unsafe
```

### Install options

| Goal | Command |
| --- | --- |
| Install for every project, not just this one | `npx skills add po4yka/rust-skills --global` |
| Target one agent | `npx skills add po4yka/rust-skills --agent claude-code` |
| Target every detected agent, no prompts | `npx skills add po4yka/rust-skills --all` |
| Copy files instead of symlinking | `npx skills add po4yka/rust-skills --copy` |
| Update after a new release | `npx skills update` |
| Remove one skill | `npx skills remove --skill rust-unsafe` |

The `skills` CLI installs into Claude Code, Codex, Cursor, OpenCode, and more than seventy other
agents. Run `npx skills --help` for the full flag list. The CLI is open source at
[vercel-labs/skills](https://github.com/vercel-labs/skills).

## How the skills activate

Each `SKILL.md` carries a `description` that states what the skill covers and when to reach for
it. The agent reads those descriptions and loads the body only when the task matches, so the
catalog costs little context until a skill is needed. The descriptions in this repository list
their trigger terms explicitly, for example `unsafe`, `transmute`, `RUSTSEC`, `cargo deny`,
`stacked borrows`, `tokio::select!`, or `uniffi::export`.

You can also read any skill directly. Every `SKILL.md` is plain Markdown.

## Catalog

Twenty-three skills. Deep material sits in `references/*.md` next to the skill that owns it.

### Language and code discipline

| Skill | What it covers |
| --- | --- |
| [rust-compiler-errors](skills/rust-compiler-errors/SKILL.md) | A triage table from error code to cause, the reflexive fixes that hide the bug, split-borrow patterns, `Send` across `.await`, and when a repeated error means the ownership design is wrong. |
| [rust-discipline](skills/rust-discipline/SKILL.md) | API design, panic policy, allocation in hot paths, concurrency primitive choice, unsafe encapsulation, and FFI review gates with a checklist. |
| [rust-code-style](skills/rust-code-style/SKILL.md) | Module file layout, `lib.rs` re-export policy, visibility levels, item order, import groups, and the `thiserror` versus `anyhow` choice. |
| [rust-crate-architecture](skills/rust-crate-architecture/SKILL.md) | Workspace layering, dependency direction rules, the crate-versus-module decision, and module layout for a crate that grew too large. |
| [rust-lints](skills/rust-lints/SKILL.md) | `workspace.lints`, `clippy.toml`, `rustfmt.toml`, and `deny.toml` policy, safe lint tightening, suppression justification, and red-gate triage. |

### Build, dependencies, and supply chain

| Skill | What it covers |
| --- | --- |
| [cargo-workflows](skills/cargo-workflows/SKILL.md) | Workspace layout, `--locked` discipline, Cargo profiles and rustflags, cross-compilation, nextest, cargo-deny, and edition migration. |
| [rust-serde](skills/rust-serde/SKILL.md) | `deny_unknown_fields` and the `rename_all` migration trap, the four enum representations and their wire forms, `flatten` constraints, boundary validation with `try_from`, and the `default` plus `alias` pair for version compatibility. |
| [rust-security](skills/rust-security/SKILL.md) | cargo-audit, cargo-deny policy, RUSTSEC advisory triage, new-crate vetting against typosquat risk, and untrusted-input parser hardening. |
| [rust-android-build](skills/rust-android-build/SKILL.md) | Android cdylib builds: NDK linkers, per-ABI rustflags, 16 KiB page alignment, the exported ELF symbol allowlist, and `.so` size gates. |

### Correctness and testing

| Skill | What it covers |
| --- | --- |
| [rust-tdd](skills/rust-tdd/SKILL.md) | The red-green-refactor-lint cycle, nextest filters, hand-written fakes, fault-injection queues, and golden contracts with a safe bless procedure. |
| [rust-test-tools](skills/rust-test-tools/SKILL.md) | nextest, cargo-careful, loom, proptest, cargo-fuzz, cargo-mutants survived-mutant triage, and deterministic golden tests. |
| [rust-sanitizers-miri](skills/rust-sanitizers-miri/SKILL.md) | ASan, TSan, and MSan flags, Miri UB detection and FFI stubbing, HWASan and MTE on device, and sanitizer report triage. |
| [rust-panic-safety](skills/rust-panic-safety/SKILL.md) | Unwind versus abort, `catch_unwind` guards at FFI boundaries, unwrap and expect audits, panic hooks, and typed-error mapping. |

### Concurrency and unsafe code

| Skill | What it covers |
| --- | --- |
| [memory-model](skills/memory-model/SKILL.md) | Atomic ordering selection, happens-before reasoning, fence placement, compare-exchange rules, and verification with Miri and loom. |
| [rust-async-internals](skills/rust-async-internals/SKILL.md) | `tokio::select!` and cancel safety, `CancellationToken` shutdown trees, blocking-work routing, and async stall and shutdown-hang triage. |
| [rust-unsafe](skills/rust-unsafe/SKILL.md) | The unsafe lint floor, SAFETY comment discipline, FFI panic guards, unaligned reads from untrusted bytes, and Miri Tree Borrows review. |

### Performance, debugging, and observability

| Skill | What it covers |
| --- | --- |
| [rust-performance](skills/rust-performance/SKILL.md) | Flamegraphs, simpleperf and Instruments, cargo-bloat and cargo-llvm-lines, Criterion baselines, LTO profiles, and build-time tuning. |
| [rust-debugging](skills/rust-debugging/SKILL.md) | Host-first reproduction, logcat and tombstones, symbolication with addr2line and atos, FFI panic hooks, and a panic-to-cause triage table. |
| [rust-observability](skills/rust-observability/SKILL.md) | `tracing` instrumentation, a redacting visitor over a closed field vocabulary, host log sinks, bounded event rings, and telemetry snapshots. |

### FFI and platform boundaries

| Skill | What it covers |
| --- | --- |
| [rust-jni](skills/rust-jni/SKILL.md) | JNI export symbol naming, panic containment, thread attach and detach discipline, local-reference frames, and native crash triage. |
| [uniffi-boundary](skills/uniffi-boundary/SKILL.md) | The Record-versus-Object decision, `Arc` ownership across the boundary, callback interfaces, type mapping, and codegen failure triage. |
| [uniffi-packaging-versioning](skills/uniffi-packaging-versioning/SKILL.md) | Artifact packaging for jniLibs and XCFramework, binding and runtime version pinning, and checksum-mismatch debugging. |
| [ffi-error-progress-cancel](skills/ffi-error-progress-cancel/SKILL.md) | A flat versioned error taxonomy, progress bridges to Kotlin `callbackFlow` and Swift `AsyncThrowingStream`, and cooperative `cancel_job`. |

## Repository layout

```
skills/<skill-name>/
├── SKILL.md              # frontmatter plus instructions
└── references/*.md       # optional deep material, linked from SKILL.md
scripts/validate-skills.py  # catalog structure checks
tests/routing-cases.md      # phrase -> skill, checked against every description
checks/                     # compile-check harness for the rust examples
checks/check.sh             # one command that reproduces CI
```

Only `skills/` is published. The rest is tooling; `npx skills add` never sees it.

`SKILL.md` frontmatter holds only the three keys that the
[Agent Skills specification](https://agentskills.io/specification) allows here: `name`,
`description`, and `license`. The `name` always equals the directory name.

## Scope

The catalog covers Rust. Android and iOS material appears only where it belongs to a Rust
concern, such as an NDK cross-compilation profile, a JNI boundary, or an XCFramework that wraps
a Rust staticlib. The skills assume you already know Rust; they encode review rules, tool
invocations, and failure triage that a codebase learns the hard way.

## Caveats

- Every ` ```rust ` block in the catalog is extracted and type-checked in CI against the
  toolchain `checks/rust-toolchain.toml` pins, currently Rust 1.97 on edition 2024. Blocks that
  cannot compile standalone carry a fence tag saying so. What CI does **not** check is whether a
  command line, a flag, or a version number is still correct — those come from the source
  codebases and from tool documentation. Check a command against your own toolchain before you
  rely on it in a script.
- Pinned versions age. Where a skill names a crate or tool version, treat it as the version the
  rule was written against, and confirm it against your `Cargo.lock`.
- A few thresholds are conventions rather than measured limits, for example the mutation-score
  target and the crate-size tiers. The skills say so at the point of use.

## Contributing

Read [AGENTS.md](AGENTS.md). It states the `SKILL.md` contract, the authoring conventions, how to
add a skill, and how to verify a change locally before you open a pull request.

## Sources

The skills are generalized from production Rust codebases. Two additions have an outside source,
recorded here because the topic inventory is theirs even though the text and the examples are
not:

- The FFI layout and pointer-shape rules in `rust-unsafe/references/ffi-layout-rules.md` follow
  the topic set of the `unsafe-checker` rules in
  [actionbook/rust-skills](https://github.com/actionbook/rust-skills) (MIT), which in turn maps
  the `P.UNS` and `G.UNS` rules of the
  [Rust Coding Guidelines](https://rust-coding-guidelines.github.io/rust-coding-guidelines-zh/).
  The prose, the examples, and the rustc 1.97 verification here are original; several upstream
  rules were dropped as out of date, including one that cites the removed clippy lint
  `unaligned_references` for what is now the hard error `E0793`.
- The idea of a compiler-error index that routes a diagnostic to a skill comes from the same
  repository. The triage table, the fix catalogue, and the escalation rule in
  `rust-compiler-errors` are written here from the compiler's own output.
- The compile-check harness in `checks/` is adapted from
  [leonardomso/rust-skills](https://github.com/leonardomso/rust-skills) (MIT). The design that
  makes it work is theirs: extract each block into a cargo example, bucket the failures so
  illustrative fragments do not drown a real defect, and gate on a signature that carries no
  line number. The extractor and the analyzer here are rewritten for this layout, with a
  `Result<T>` alias for the crate-local alias skills assume, rustdoc fence tags as the opt-out,
  and an empty baseline instead of an accepted-suspect list.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
