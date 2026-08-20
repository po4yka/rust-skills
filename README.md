<div align="center">

# rust-skills

**Forty agent skills for production Rust:**
unsafe review · networking · FFI boundaries · native linking · profiling · crate releases · supply chain

[![CI](https://github.com/po4yka/rust-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/po4yka/rust-skills/actions/workflows/ci.yml)
[![Rust 1.97 · edition 2024](https://img.shields.io/badge/rust-1.97%20%C2%B7%20edition%202024-000000?style=flat-square&logo=rust)](checks/rust-toolchain.toml)
[![License BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-0969da?style=flat-square)](LICENSE)

</div>

Each skill is a reference sheet for a coding agent, not a tutorial. Each one carries concrete
commands, flags, thresholds, and triage tables instead of general advice.

Every ` ```rust ` block in the catalog declares what CI must do with it, and CI does it on the
toolchain that `checks/rust-toolchain.toml` pins. An untagged block is extracted and
type-checked; a `rust,compile_fail` block has to fail, and its fence can name the error code it
must produce; `rust,ignore` is the only way a block leaves the gate. Nothing is skipped in
silence: the run prints the split and fails when a block it generated never reached the
compiler.

## Install

```bash
npx skills add po4yka/rust-skills
```

> [!TIP]
> You do not need the whole catalog. `npx skills add po4yka/rust-skills --skill rust-unsafe`
> installs one skill, and `npx skills use po4yka/rust-skills@rust-unsafe` reads it as a prompt
> without installing anything.

<details>
<summary><b>All install options</b></summary>

<br>

| Goal | Command |
| --- | --- |
| List the catalog without installing | `npx skills add po4yka/rust-skills --list` |
| Install one skill | `npx skills add po4yka/rust-skills --skill rust-unsafe` |
| Read one skill as a prompt | `npx skills use po4yka/rust-skills@rust-unsafe` |
| Install for every project, not just this one | `npx skills add po4yka/rust-skills --global` |
| Target one agent | `npx skills add po4yka/rust-skills --agent claude-code` |
| Target every detected agent, no prompts | `npx skills add po4yka/rust-skills --all` |
| Copy files instead of symlinking | `npx skills add po4yka/rust-skills --copy` |
| Update after a new release | `npx skills update` |
| Remove one skill | `npx skills remove --skill rust-unsafe` |

> **Checkout data-loss warning:** Never run `skills remove` from this
> repository's checkout. The CLI can treat the source `skills/` directory as
> an install location and delete the selected source directory. An uncommitted
> skill cannot be recovered from Git. Run removal from the project that owns
> the installation or from a scratch directory outside this checkout.

The `skills` CLI installs into Claude Code, Codex, Cursor, OpenCode, and more than seventy other
agents. Run `npx skills --help` for the full flag list. The CLI is open source at
[vercel-labs/skills](https://github.com/vercel-labs/skills).

</details>

## Which skill do I need?

Enter by the symptom, not by the skill name.

| What you are looking at | Skill |
| --- | --- |
| `E0382`, `E0499`, `does not live long enough`, `missing lifetime specifier` | [rust-compiler-errors](skills/rust-compiler-errors/SKILL.md) |
| `cannot be sent between threads safely` across an `.await` | [rust-async-internals](skills/rust-async-internals/SKILL.md) |
| A `tokio::select!` branch dropped work, or shutdown hangs | [rust-async-internals](skills/rust-async-internals/SKILL.md) |
| `Ordering::Relaxed` versus `SeqCst`, a fence you cannot justify | [memory-model](skills/memory-model/SKILL.md) |
| A global: `static mut`, `OnceLock`, `LazyLock`, `thread_local!` | [memory-model](skills/memory-model/SKILL.md) |
| A macro to write or debug: `macro_rules!`, a derive, `cargo expand` | [rust-macros](skills/rust-macros/SKILL.md) |
| You implement `Iterator` or `IntoIterator` for your own type | [rust-iterator-impl](skills/rust-iterator-impl/SKILL.md) |
| A `SAFETY` comment to review, `repr(packed)`, `mem::zeroed`, `improper_ctypes` | [rust-unsafe](skills/rust-unsafe/SKILL.md) |
| Miri, ThreadSanitizer, HWASan, or MTE reports something | [rust-sanitizers-miri](skills/rust-sanitizers-miri/SKILL.md) |
| You need the profile first: flamegraph, simpleperf, `cargo-bloat` | [rust-performance](skills/rust-performance/SKILL.md) |
| The profile already named the hot spot: allocations, type size, hasher | [rust-hot-path](skills/rust-hot-path/SKILL.md) |
| Borrow or clone at an API boundary: `Cow<str>`, `to_mut`, clone cost | [rust-copy-on-write](skills/rust-copy-on-write/SKILL.md) |
| A tombstone, a stripped backtrace, `addr2line` symbolication | [rust-debugging](skills/rust-debugging/SKILL.md) |
| `UnsatisfiedLinkError`, `AttachCurrentThread`, a native crash from Kotlin | [rust-jni](skills/rust-jni/SKILL.md) |
| UniFFI checksum mismatch, XCFramework or jniLibs packaging | [uniffi-packaging-versioning](skills/uniffi-packaging-versioning/SKILL.md) |
| A `RUSTSEC` advisory, or a new dependency nobody vetted | [rust-security](skills/rust-security/SKILL.md) |
| `deny_unknown_fields` or `rename_all` broke the wire format | [rust-serde](skills/rust-serde/SKILL.md) |
| A lifetime coercion is refused: `is invariant over the parameter`, `borrowed for 'static` | [rust-variance](skills/rust-variance/SKILL.md) |
| A callback bound rejects `|o| &o.field`, or a struct field holds a closure | [rust-callback-bounds](skills/rust-callback-bounds/SKILL.md) |
| `self: Pin<&mut Self>`, `PhantomPinned`, or a `#[pin]` projection | [rust-pin-projection](skills/rust-pin-projection/SKILL.md) |
| `cannot be sent between threads safely`, `MutexGuard` is not `Send` | [rust-send-sync](skills/rust-send-sync/SKILL.md) |
| A `HashMap<TypeId, _>` whose values borrow, `dyn Any`, `downcast_ref` | [rust-type-erasure](skills/rust-type-erasure/SKILL.md) |
| Every handler in an event loop needs `&mut` to one shared state | [rust-event-loop-state](skills/rust-event-loop-state/SKILL.md) |
| 16 KiB page alignment, NDK linkers, per-ABI rustflags, `.so` size gates | [rust-android-build](skills/rust-android-build/SKILL.md) |
| A SemVer bump, `cargo package`, `cargo publish`, or crates.io recovery | [rust-crate-release](skills/rust-crate-release/SKILL.md) |
| `build.rs`, `pkg-config`, an undefined symbol, or a packaged DLL failure | [rust-native-linking](skills/rust-native-linking/SKILL.md) |
| HTTP timeout, safe retries, TLS verification, body limits, or graceful shutdown | [rust-networking](skills/rust-networking/SKILL.md) |
| Pool exhaustion, transaction rollback, migration ordering, or serialization failure | [rust-database](skills/rust-database/SKILL.md) |
| `wasm32-unknown-unknown`, WASI, `wasm-bindgen`, or a WebAssembly size regression | [rust-wasm](skills/rust-wasm/SKILL.md) |
| `no_std`, `memory.x`, an interrupt race, Embassy, RTIC, `probe-rs`, or `defmt` | [rust-embedded-no-std](skills/rust-embedded-no-std/SKILL.md) |
| `clap` arguments, stdout or exit-code compatibility, Ctrl-C, atomic output, or shell completions | [rust-cli](skills/rust-cli/SKILL.md) |

The full phrase-to-skill list lives in [tests/routing-cases.md](tests/routing-cases.md), and CI
checks every row against the skill descriptions.

```mermaid
flowchart LR
    Q(["Where does it hurt?"])

    Q --> A["It does not<br/>compile or lint"]
    Q --> B["It is not<br/>provably correct"]
    Q --> C["It is too slow<br/>or too big"]
    Q --> D["It fails in<br/>the field"]
    Q --> E["It crosses a<br/>language boundary"]
    Q --> F["It is not built<br/>or shipped yet"]
    Q --> G["It is a command-line<br/>interface"]

    A --> A1[rust-compiler-errors]
    A --> A2[rust-discipline]
    A --> A3[rust-code-style]
    A --> A4[rust-crate-architecture]
    A --> A5[rust-lints]
    A --> A6[rust-macros]
    A --> A7[rust-iterator-impl]
    A --> A8[rust-variance]
    A --> A9[rust-callback-bounds]
    A --> A10[rust-type-erasure]
    A --> A11[rust-event-loop-state]

    B --> B1[memory-model]
    B --> B2[rust-unsafe]
    B --> B3[rust-sanitizers-miri]
    B --> B4[rust-tdd]
    B --> B5[rust-test-tools]
    B --> B6[rust-panic-safety]
    B --> B7[rust-pin-projection]
    B --> B8[rust-send-sync]

    C --> C1[rust-performance]
    C --> C2[rust-hot-path]
    C --> C3[rust-async-internals]
    C --> C4[rust-copy-on-write]

    D --> D1[rust-debugging]
    D --> D2[rust-observability]
    D --> D3[rust-networking]
    D --> D4[rust-database]

    E --> E1[rust-jni]
    E --> E2[uniffi-boundary]
    E --> E3[ffi-error-progress-cancel]

    F --> F1[cargo-workflows]
    F --> F2[rust-android-build]
    F --> F3[rust-security]
    F --> F4[rust-serde]
    F --> F5[uniffi-packaging-versioning]
    F --> F6[rust-crate-release]
    F --> F7[rust-native-linking]
    F --> F8[rust-wasm]
    F --> F9[rust-embedded-no-std]

    G --> G1[rust-cli]
```

## Catalog

Forty skills in six groups. Deep material sits in `references/*.md` next to the skill that
owns it.

<details open>
<summary><b>Language, interfaces, and code discipline</b> — eleven skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [rust-compiler-errors](skills/rust-compiler-errors/SKILL.md) | A triage table from error code to cause, the reflexive fixes that hide the bug, split-borrow patterns, `Send` across `.await`, and when a repeated error means the ownership design is wrong. |
| [rust-discipline](skills/rust-discipline/SKILL.md) | API design, panic policy, allocation in hot paths, concurrency primitive choice, unsafe encapsulation, and FFI review gates with a checklist. |
| [rust-code-style](skills/rust-code-style/SKILL.md) | Module file layout, `lib.rs` re-export policy, visibility levels, item order, import groups, and the `thiserror` versus `anyhow` choice. |
| [rust-crate-architecture](skills/rust-crate-architecture/SKILL.md) | Workspace layering, dependency direction rules, the crate-versus-module decision, and module layout for a crate that grew too large. |
| [rust-lints](skills/rust-lints/SKILL.md) | `workspace.lints`, `clippy.toml`, `rustfmt.toml`, and `deny.toml` policy, safe lint tightening, suppression justification, and red-gate triage. |
| [rust-macros](skills/rust-macros/SKILL.md) | `macro_rules!` textual scope and hygiene, fragment follow sets, the recursion limit, proc-macro crate rules, and the facade-and-derive crate split. |
| [rust-iterator-impl](skills/rust-iterator-impl/SKILL.md) | The producing side of iteration: a hand-written `Iterator`, the three `IntoIterator` impls, `FromIterator` and `Extend`, `size_hint`, and the `unconditional_recursion` stack overflow. |
| [rust-variance](skills/rust-variance/SKILL.md) | Variance, subtyping, and lifetime coercion: the two probe functions that settle any case in one `rustc` run, the table for every constructor and `PhantomData` form, why a trait bound matches by equality, and why adding interior mutability is a breaking change. |
| [rust-callback-bounds](skills/rust-callback-bounds/SKILL.md) | Shaping a callable in a public signature: which bound accepts which closure, `for<'a> Fn(&'a T) -> &'a K` for reference projections, HRTB as a no-escape promise, positional closure inference, and the cost of a generic `F` field against `Box<dyn Fn>`. |
| [rust-type-erasure](skills/rust-type-erasure/SKILL.md) | Type-keyed storage when the values are not `'static`: why `Any` is bound to `'static`, the ladder from a lifetime-parameterized enum to a `Box<dyn Any>` map to the GAT owner/element bijection, and where the pattern turns unsound. |
| [rust-cli](skills/rust-cli/SKILL.md) | Stable command-line contracts for arguments, stdout and stderr, exit status, configuration precedence, signals, terminal behavior, atomic file output, and packaged shell completions. |

</details>

<details>
<summary><b>Build, dependencies, and supply chain</b> — eight skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [cargo-workflows](skills/cargo-workflows/SKILL.md) | Workspace layout, `--locked` discipline, Cargo profiles and rustflags, cross-compilation, nextest, cargo-deny, and edition migration. |
| [rust-crate-release](skills/rust-crate-release/SKILL.md) | SemVer and MSRV classification, public API and feature compatibility, package and docs gates, dry-run publishing, tags, owners, and safe yank recovery. |
| [rust-native-linking](skills/rust-native-linking/SKILL.md) | Cargo native integration: deterministic build scripts, one `links`/`*-sys` owner, native build helper selection, bindings, cross-target linking, loader paths, and symbol or ABI triage. |
| [rust-serde](skills/rust-serde/SKILL.md) | `deny_unknown_fields` and the `rename_all` migration trap, the four enum representations and their wire forms, `flatten` constraints, boundary validation with `try_from`, and the `default` plus `alias` pair for version compatibility. |
| [rust-security](skills/rust-security/SKILL.md) | cargo-audit, cargo-deny policy, RUSTSEC advisory triage, new-crate vetting against typosquat risk, and untrusted-input parser hardening. |
| [rust-android-build](skills/rust-android-build/SKILL.md) | Android cdylib builds: NDK linkers, per-ABI rustflags, 16 KiB page alignment, the exported ELF symbol allowlist, and `.so` size gates. |
| [rust-wasm](skills/rust-wasm/SKILL.md) | Exact WebAssembly host and target selection, JavaScript boundary ownership, panic and async behavior, WASI capabilities, runtime tests, feature compatibility, and packaged size gates. |
| [rust-embedded-no-std](skills/rust-embedded-no-std/SKILL.md) | Bare-metal and `no_std` policy for runtime and memory layout, panic and allocation, interrupts and critical sections, task frameworks, finite resource budgets, and real-device diagnostics. |

</details>

<details>
<summary><b>Correctness and testing</b> — four skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [rust-tdd](skills/rust-tdd/SKILL.md) | The red-green-refactor-lint cycle, nextest filters, hand-written fakes, fault-injection queues, and golden contracts with a safe bless procedure. |
| [rust-test-tools](skills/rust-test-tools/SKILL.md) | nextest, cargo-careful, loom, proptest, cargo-fuzz, cargo-mutants survived-mutant triage, and deterministic golden tests. |
| [rust-sanitizers-miri](skills/rust-sanitizers-miri/SKILL.md) | ASan, TSan, and MSan flags, Miri UB detection and FFI stubbing, HWASan and MTE on device, and sanitizer report triage. |
| [rust-panic-safety](skills/rust-panic-safety/SKILL.md) | Unwind versus abort, `catch_unwind` guards at FFI boundaries, unwrap and expect audits, panic hooks, and typed-error mapping. |

</details>

<details>
<summary><b>Concurrency and unsafe code</b> — six skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [memory-model](skills/memory-model/SKILL.md) | Atomic ordering selection, happens-before reasoning, fence placement, compare-exchange rules, and verification with Miri and loom. |
| [rust-async-internals](skills/rust-async-internals/SKILL.md) | `tokio::select!` and cancel safety, `CancellationToken` shutdown trees, blocking-work routing, and async stall and shutdown-hang triage. |
| [rust-unsafe](skills/rust-unsafe/SKILL.md) | The unsafe lint floor, SAFETY comment discipline, FFI panic guards, unaligned reads from untrusted bytes, and Miri Tree Borrows review. |
| [rust-pin-projection](skills/rust-pin-projection/SKILL.md) | `Pin`, `Unpin` and `PhantomPinned`: why a `Pin` on an `Unpin` type enforces nothing, `std::pin::pin!` against `Box::pin` and `Pin::new_unchecked`, the four structural pinning obligations, and `pin-project` against `pin-project-lite`. |
| [rust-send-sync](skills/rust-send-sync/SKILL.md) | The auto traits as a subject: `&T: Send` exactly when `T: Sync`, the reference and smart-pointer table, `Mutex` against `RwLock` payload bounds, `MutexGuard` as `!Send` but `Sync`, and `PhantomData` markers that remove exactly one trait. |
| [rust-event-loop-state](skills/rust-event-loop-state/SKILL.md) | Who owns the handler set and who owns the state in a tick loop, state as a trait parameter with capability bounds, when an ECS-shaped world earns its runtime conflict panic, and why `async fn(&mut State)` cannot suspend over shared state. |

</details>

<details>
<summary><b>Networking, database, performance, debugging, and observability</b> — seven skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [rust-performance](skills/rust-performance/SKILL.md) | Flamegraphs, simpleperf and Instruments, cargo-bloat and cargo-llvm-lines, Criterion baselines, LTO profiles, and build-time tuning. |
| [rust-hot-path](skills/rust-hot-path/SKILL.md) | What to change once a profile names the hot spot: allocation rate, type size, hasher choice, bounds checks, inline attributes, and buffered I/O. |
| [rust-copy-on-write](skills/rust-copy-on-write/SKILL.md) | The decision before the profile: `Cow` in return and argument position, the `to_mut` allocation trap, the lifetime a `Cow` field forces on callers, and measured persistent-collection costs. |
| [rust-debugging](skills/rust-debugging/SKILL.md) | Host-first reproduction, logcat and tombstones, symbolication with addr2line and atos, FFI panic hooks, and a panic-to-cause triage table. |
| [rust-observability](skills/rust-observability/SKILL.md) | `tracing`, production metric contracts, histogram and cardinality budgets, OpenTelemetry context propagation, redaction, bounded exporters, host sinks, and telemetry snapshots. |
| [rust-networking](skills/rust-networking/SKILL.md) | Production client and server policy for deadline budgets, safe retries, TLS, proxy and DNS, connection pools, streaming limits, overload, cancellation, and graceful shutdown. |
| [rust-database](skills/rust-database/SKILL.md) | Production database policy for pool budgets, transaction ownership, cancellation, isolation and bounded retries, compatible migrations, and real-schema integration tests. |

</details>

<details>
<summary><b>FFI and platform boundaries</b> — four skills</summary>

<br>

| Skill | What it covers |
| --- | --- |
| [rust-jni](skills/rust-jni/SKILL.md) | JNI export symbol naming, panic containment, thread attach and detach discipline, local-reference frames, and native crash triage. |
| [uniffi-boundary](skills/uniffi-boundary/SKILL.md) | The Record-versus-Object decision, `Arc` ownership across the boundary, callback interfaces, type mapping, and codegen failure triage. |
| [uniffi-packaging-versioning](skills/uniffi-packaging-versioning/SKILL.md) | Artifact packaging for jniLibs and XCFramework, binding and runtime version pinning, and checksum-mismatch debugging. |
| [ffi-error-progress-cancel](skills/ffi-error-progress-cancel/SKILL.md) | A flat versioned error taxonomy, progress bridges to Kotlin `callbackFlow` and Swift `AsyncThrowingStream`, and cooperative `cancel_job`. |

</details>

## How the skills activate

Each `SKILL.md` carries a `description` that states what the skill covers and when to reach for
it. The agent reads those descriptions and loads the body only when the task matches, so the
catalog costs little context until a skill is needed. The descriptions in this repository list
their trigger terms explicitly, for example `unsafe`, `transmute`, `RUSTSEC`, `cargo deny`,
`stacked borrows`, `tokio::select!`, or `uniffi::export`.

You can also read any skill directly. Every `SKILL.md` is plain Markdown.

The [Agent Skills specification](https://agentskills.io/specification) requires `name` and
`description`, and allows `license`, `compatibility`, `metadata`, and `allowed-tools`. This
repository uses three of them — `name`, `description`, and `license` — and requires all three;
that is a rule of this catalog, not of the specification. The `name` always equals the directory
name. Every value stays a plain YAML scalar, because the skills CLI and the agent runtimes read
the file with a real YAML parser.

## Repository layout

```text
skills/<skill-name>/
├── SKILL.md                  # frontmatter plus instructions
└── references/*.md           # optional deep material, linked from SKILL.md

scripts/validate-skills.py    # catalog structure checks
tests/routing-cases.md        # phrase -> skill, checked against every description
checks/                       # compile-check harness for the rust examples
checks/check.sh               # one command that reproduces CI
```

Only `skills/` is published. The rest is tooling; `npx skills add` never sees it.

## Scope

The catalog covers Rust. Android and iOS material appears only where it belongs to a Rust
concern, such as an NDK cross-compilation profile, a JNI boundary, or an XCFramework that wraps
a Rust staticlib. The skills assume you already know Rust; they encode review rules, tool
invocations, and failure triage that a codebase learns the hard way.

## Caveats

> [!WARNING]
> CI type-checks the Rust examples. It does **not** check whether a command line, a flag, or a
> version number is still correct. Verify a command against your own toolchain before you put it
> in a script.

- Every ` ```rust ` block in the catalog is extracted and type-checked in CI against the
  toolchain `checks/rust-toolchain.toml` pins, currently Rust 1.97 on edition 2024. Blocks that
  cannot compile standalone carry a fence tag saying so.
- Pinned versions age. Where a skill names a crate or tool version, treat it as the version the
  rule was written against, and confirm it against your `Cargo.lock`.
- A few thresholds are conventions rather than measured limits, for example the mutation-score
  target and the crate-size tiers. The skills say so at the point of use.

## Contributing

Read [AGENTS.md](AGENTS.md). It states the `SKILL.md` contract, the authoring conventions, how to
add a skill, and how to verify a change locally before you open a pull request.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
