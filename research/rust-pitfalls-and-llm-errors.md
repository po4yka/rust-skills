# Rust Pitfalls and LLM Errors: Evidence Map

Status: evidence complete for the stated cut-off; implementation mapping current

Evidence cut-off: 2026-08-20

## Scope and method

This document asks one question: Which errors do large language models make when they generate or repair Rust code?

This first pass uses primary sources only. It includes papers, benchmark repositories, benchmark project pages, and compiler-driven studies. It does not use blog summaries or product claims.

The review includes these task types:

- repair of Rust compiler errors;
- repository-level translation to Rust;
- C-to-safe-Rust translation;
- type migration during C-to-Rust translation;
- security-sensitive Rust generation;
- real issue repair and Rust API evolution benchmarks.

The reported percentages are not directly comparable. Each source uses different models, prompts, tools, task units, Rust versions, and success criteria. A result for C translation does not give a general success rate for native Rust development.

The evidence supports error classes and validation needs. It does not support a single ranking of models.

## Main findings

1. Compiler failure is still the main observed failure mode in repository translation. RustRepoTrans reports that 1,614 of 1,748 unsuccessful samples failed to compile. This is 92.3% of the unsuccessful samples.
2. The most repeated compiler-level classes are missing or invented APIs, unresolved context, type mismatches, missing trait implementations, and borrow or mutability errors.
3. Compiler feedback improves many results. It does not remove incomplete implementations or semantic defects. It can also introduce new type and borrow errors.
4. A successful build is weak evidence of correctness. Tests found semantic regressions in RustAssistant. Tests also separated build success from functional success in CRUST-Bench.
5. Security properties need checks outside the compiler. A cryptographic Rust study found domain-specific vulnerabilities in 32 of 56 samples that compiled.
6. The current evidence is translation-heavy. It gives less direct evidence for macros, build scripts, async Rust, unsafe Rust, FFI, embedded Rust, and large native Rust maintenance tasks.

## Primary source evidence

| Source | Task and data | Quantitative result | Error evidence | Important limits |
|---|---|---|---|---|
| [Fixing Rust Compilation Errors using LLMs](https://www.microsoft.com/en-us/research/publication/fixing-rust-compilation-errors-using-llms/) ([paper PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/08/paper.pdf), [arXiv](https://arxiv.org/abs/2308.05177)) | RustAssistant repairs compiler errors. The evaluation uses 270 compiler-error microbenchmarks, 50 Stack Overflow programs, and 182 real commits from popular crates. | With GPT-4 and five completions per prompt, Table 1 reports 252 of 270 microbenchmarks. The corresponding results are 36 of 50 Stack Overflow programs and 134 of 182 commits. The paper is internally inconsistent because the abstract and nearby prose state 250 of 270 and 92.59%. | Syntax, types, generics, traits, ownership, and lifetimes. Failure cases include partial cross-file repair, fix-and-undo loops, and a required dependency edit outside the allowed edit scope. | The study uses older model snapshots and Rust 1.67.1. It can contain training contamination. It excludes package configuration, build configuration, FFI, and unsafe Rust from the microbenchmarks. Human semantic review is subjective. |
| [CRUST-Bench: A Comprehensive Benchmark for C-to-safe-Rust Transpilation](https://arxiv.org/pdf/2504.15254) ([dataset repository](https://github.com/anirudhkhatry/CRUST-bench), [project page](https://crust-bench.github.io/)) | Repository-level C-to-safe-Rust translation for 100 C repositories. The benchmark supplies manually written safe Rust interfaces and tests. | In one-shot generation, the strongest shown build/test results were 43/22 for Claude Opus 4 and 35/19 for OpenAI o3. After three compiler-repair rounds, these were 78/29 and 68/31. After test repair, o3 reached 48 passing tasks. | Type mismatch, borrowing, missing symbols, incomplete code, trait errors, wrong arguments, and unsafe or unstable code. Incomplete outputs include placeholders and comments such as "similarly" instead of code. | This is C translation, not general Rust work. Results depend on a prompt that forbids unsafe code. Tests are incomplete specifications. Coverage data covers only part of the dataset. |
| [RustRepoTrans: Repository-Level Code Translation Benchmark Targeting Rust](https://mingwei-liu.github.io/assets/pdf/ase2025rustrepotrans.pdf) ([benchmark repository](https://github.com/SYSUSELab/RustRepoTrans)) | 375 incremental repository translation tasks: 122 Java-to-Rust, 145 C-to-Rust, and 108 Python-to-Rust tasks. | Of 1,748 unsuccessful samples, 1,614 failed to compile. Failed samples had 1 to 193 compiler errors, with a mean of 7.7 and a median of 3. Repository context reduced Pass@1 by 16.2 to 30.8 points against the compared function-level benchmark. | The most frequent compiler codes were E0599, E0425, E0308, E0277, E0609, and E0433. The study maps them to target-feature misunderstanding, cross-language differences, dependency resolution, signature mismatch, syntax, and missing context. | The benchmark gives the model selected repository context. It does not fully test global-state migration or all static and dynamic analysis methods. Translation data can be present in model training data. The taxonomy uses manual coding. |
| [Type-migrating C-to-Rust translation using a large language model](https://link.springer.com/article/10.1007/s10664-024-10573-2) | Whole-program C-to-Rust type migration with compiler suggestions and LLM repair. | The full GPT-4o-mini method reduced type errors by 71.5% against its ablation baseline. It still left a mean of 1,155.3 type errors per program. Only 55.9% of functions had no local type errors in the best setting. | Missing explicit casts, incompatible numeric operations, and incorrect target types. Compiler suggestions do not cover all mixed-type operations. | Most full programs did not compile. This prevented full semantic test execution. A manual 41-function sample showed evaluator disagreement about semantic correctness. This is C migration, not native Rust generation. |
| [An Empirical Security Evaluation of LLM-Generated Cryptographic Rust Code](https://arxiv.org/pdf/2604.27001) | 240 single-file AEAD samples from three models, two algorithms, four prompt styles, and ten repetitions. | Only 56 of 240 samples compiled. Of 184 compilation failures, the paper assigns 41.3% to API hallucinations, 28.6% to type errors, 18.5% to trait errors, and 11.6% to unresolved imports. A domain-specific analyzer found findings in 32 of 56 compiling samples. | Invented cryptographic APIs, incorrect types and traits, unresolved imports, panic through `unwrap()`, nonce reuse, and a hard-coded key. | This is a 2026 preprint and a narrow AEAD study. It uses small samples per configuration. Its custom analyzer has limited single-file rules. It can miss indirect and cross-module defects. The result needs replication. |
| [RustEvo benchmark repository](https://github.com/SYSUSELab/RustEvo) | Rust code generation across 588 API changes from the standard library and 15 crates, for Rust 1.71 through 1.84. | The repository reports lower mean Pass@1 for behavioral changes (38.0%) and deprecations (40.4%) than for stabilizations (65.8%) and signature changes (58.2%). | API version drift, behavioral change, deprecation, signature change, and new stable API use. | The repository marks the benchmark as under construction. Treat its current numbers as provisional. It does not yet give a stable, peer-reviewed error taxonomy. |
| [Multi-SWE-bench](https://multi-swe-bench.github.io/) ([repository](https://github.com/multi-swe-bench/multi-swe-bench), [paper](https://arxiv.org/abs/2504.02605)) | Real repository issue repair in seven languages. The dataset includes 239 Rust tasks in a total of 1,632 tasks. | The public aggregate leaderboard does not isolate a Rust error rate. | The benchmark can support future study of real Rust maintenance failures and agent behavior. | Current public summary results combine languages. They do not provide a Rust-specific error taxonomy. Do not use the aggregate rate as a Rust rate. |

## Taxonomies reported by the source authors

### RustAssistant

The RustAssistant microbenchmark groups 270 official compiler error codes into six classes: syntax, type, generics, traits, ownership, and lifetime. It covers 270 of the 506 error codes documented at the time of the study.

The paper also reports a focused set for ownership, lifetime, and trait errors. GPT-4 RustAssistant fixed 90 of 99 errors in that microbenchmark subset. It fixed 31 of 43 Stack Overflow programs in the same subset. It fixed 58 of 60 real commits that contained at least one such error and preserved runtime behavior under the paper's review method.

This result shows that borrow-checker errors are repairable with an iterative compiler loop. It does not show that a one-shot generator handles ownership design well.

### CRUST-Bench

CRUST-Bench uses seven compiler-failure classes: mismatch, borrowing, missing, unimplemented or incomplete, trait, arguments, and unsafe or unstable. Its table reports the percentage of the 100 projects that contain each class.

For o3, compiler repair changed the reported rates as follows:

- mismatch: 13% to 9%;
- borrowing: 21% to 2%;
- missing: 8% to 2%;
- unimplemented or incomplete: 34% to 27%;
- trait: 4% to 4%;
- arguments: 0% to 2%;
- unsafe or unstable: 1% to 0%.

For Claude Opus 4, compiler repair changed the same rates from 28%, 29%, 7%, 13%, 14%, 1%, and 6% to 11%, 3%, 2%, 5%, 1%, 3%, and 0%.

These results show two different effects. Compiler repair removes many borrow and trait failures. It does less for incomplete output. Repair can also introduce an argument error.

### RustRepoTrans

RustRepoTrans uses open coding to classify root causes. Two authors coded the failures and report a Cohen's kappa of 0.885.

At the high level, the taxonomy assigns 73.9% of failures to cross-language differences, 22.4% to misunderstanding of target features, and 3.7% to other causes.

The detailed distribution is:

| Reported cause | Share |
|---|---:|
| Function differences | 38.6% |
| Variable differences | 24.9% |
| Data type misinterpretation | 16.1% |
| Variable state | 5.4% |
| Data type differences | 4.1% |
| Dependency resolution | 4.0% |
| Function signature inconsistency | 2.9% |
| Syntactic differences | 2.3% |
| Missing context | 0.9% |
| Missing punctuation | 0.8% |

This taxonomy is specific to translation. For example, "function differences" includes incorrect assumptions about a direct target-language equivalent. Do not transfer these shares to native Rust coding.

### Cryptographic Rust generation

The cryptographic study classifies all 184 compilation failures. It assigns 41.3% to API hallucinations, 28.6% to type errors, 18.5% to trait errors, and 11.6% to unresolved imports.

The prompt style changed the distribution. Chain-of-thought prompts compiled in 6.7% of cases, while zero-shot prompts compiled in 35.0% of cases. The authors report that 82.1% of chain-of-thought failures used nonexistent cryptographic APIs. This result is specific to the tested prompts and APIs. It does not prove that chain-of-thought prompts are generally harmful.

## Cross-study error taxonomy

This table is a synthesis. The source authors do not use one shared taxonomy.

| Harmonized class | Observable failure | Direct evidence |
|---|---|---|
| API and context hallucination | The model calls a method that does not exist. It names a missing item, field, crate, module, or import. | RustRepoTrans reports E0599, E0425, E0609, E0433, and E0432 among its most frequent codes. The cryptographic study assigns 41.3% of compile failures to API hallucinations and 11.6% to unresolved imports. |
| Type and trait mismatch | The model selects the wrong concrete type. It omits a conversion. It assumes that an operator or trait implementation exists. | RustRepoTrans reports E0308 and E0277 as frequent codes. The type-migration study shows that required numeric casts are often absent. The cryptographic study assigns 28.6% of compile failures to type errors and 18.5% to trait errors. |
| Ownership, borrowing, lifetime, and mutability | The model moves a value too early. It creates conflicting borrows. It applies immutable and mutable borrows inconsistently. It does not propagate a lifetime or ownership change to callers. | RustAssistant directly evaluates ownership, lifetime, and trait failures. CRUST-Bench reports borrowing as a major class. RustRepoTrans gives an example that passes one variable as both `&value` and `&mut value` under an incompatible design. |
| Signature and call mismatch | The model changes a function but not its call sites. It uses the wrong number or order of arguments. | RustRepoTrans reports E0061 and a signature-inconsistency category. RustAssistant reports partial fixes that do not propagate through the call graph. |
| Incomplete implementation | The output ends early. It leaves `unimplemented!()`, a placeholder, or a prose comment in place of code. | CRUST-Bench identifies unimplemented or incomplete output as a large residual class. It links some cases to output truncation and placeholder text. |
| Repair loop and error cascade | A repair removes one error and restores an earlier error. A semantic repair introduces a new borrow or type error. | RustAssistant reports fix-and-undo loops. CRUST-Bench reports that test-based repair can reduce build success by 5 to 20 points because aggressive changes introduce compiler errors. |
| Compiles but changes behavior | The edit satisfies the compiler but changes the required result. | In a RustAssistant microbenchmark, a repair replaced an invalid float shift with multiplication by 2.0. The intended shift by two bits corresponds to multiplication by 4. The code compiled but its test failed. RustAssistant also found 13 test failures in one single-attempt microbenchmark setting. |
| Compiles but violates a security invariant | The code type-checks, but it can panic or misuse a cryptographic primitive. | The cryptographic Rust study reports findings in 32 of 56 compiling samples. It includes `unwrap()` on fallible operations, nonce reuse, and a hard-coded key. |
| Ecosystem and version mismatch | The model uses an API from the wrong crate or Rust version. It misses a deprecation or a behavioral change. | RustEvo is direct but provisional evidence. RustAssistant also reports a case that needed a dependency update in `Cargo.toml`, which its repair scope did not permit. |

## Quantitative details that affect validation design

### Compiler feedback helps, but it has a limit

RustAssistant groups related diagnostics and applies iterative patches. Its full GPT-4 prompt fixed 252 of 270 microbenchmarks in the reported prompt ablation. A minimal prompt fixed 139 of 270. This result shows that diagnostic selection and patch format materially affect repair quality.

CRUST-Bench shows a similar effect at repository scale. Three compiler-repair rounds increased build success from 35 to 68 tasks for o3 and from 43 to 78 tasks for Claude Opus 4. Functional success stayed much lower at 31 and 29 tasks.

Compiler feedback can also reach a plateau. CRUST-Bench reports that borrowing and trait errors fall sharply in early repair rounds, while some type mismatches remain. The paper also reports that test repair can introduce new compiler errors.

Use compiler feedback as a repair input. Do not use a clean build as the completion condition.

### Tests catch semantic regressions after a clean build

RustAssistant runs tests after a repair. Its float-shift example shows why this step is necessary. The generated patch was type-correct but computed the wrong value.

For 134 fixed real commits, the paper classified 55 as semantically unambiguous. Of the remaining commits, 41 matched the developer patch, 29 differed but had the same runtime behavior under review, and 9 had different runtime behavior. These categories depend on human judgment.

CRUST-Bench also separates build and test results. Its best stated test-repair result was 48 passing projects, although several configurations built more than 60 projects. A build gate alone would overstate success.

### Error counts can hide one root cause

RustRepoTrans found up to 193 compiler diagnostics in one failed sample. The median was 3. Rust compiler diagnostics can cascade from one missing type, method, or import.

Group related diagnostics before repair. Re-run the compiler after the smallest coherent patch. Do not treat each emitted diagnostic as an independent defect.

### Safety instructions change the observed taxonomy

CRUST-Bench finds little unsafe code, but its prompt explicitly forbids unsafe Rust. This result does not show that models avoid unsafe code in normal generation.

The RustAssistant microbenchmark also excludes unsafe Rust and FFI. Current evidence cannot establish a general LLM error rate for soundness boundaries.

### Security needs domain checks

The cryptographic study shows that compile success and general static analysis are not sufficient for its AEAD tasks. The compiler cannot prove nonce uniqueness or key provenance. The paper's CodeQL queries also did not give useful positive findings for this narrow setup.

Use domain-specific assertions and review for security invariants. Treat this conclusion as strong for the studied AEAD patterns and unproven for other security domains.

## Concrete failure examples

These examples are paraphrases of source cases. They do not copy source code.

1. A repair sees an invalid bit shift on a floating-point value. It changes the operation to multiplication by 2.0. The program compiles, but a shift count of two requires a factor of 4 for the intended test behavior.
2. A repository translation uses one local value through both immutable and mutable references without a valid ownership plan. The compiler reports a borrow or mutability conflict.
3. A translation assumes that a source-language helper has a direct Rust equivalent. It calls a nonexistent method and produces E0599.
4. A generated implementation changes a callee signature. It does not update all callers. The first local error disappears, but call-site errors remain.
5. A model returns a partial file with a comment that says the remaining functions are similar. The output does not implement the required interface.
6. A cryptographic sample compiles and encrypts data. It reuses a nonce or embeds a key. The compiler does not reject this semantic security defect.

## Study limitations and open evidence risks

- Most detailed studies translate C, Java, or Python to Rust. Translation errors can differ from native Rust design and maintenance errors.
- Model versions change. Prompt behavior and tool behavior can change without a benchmark change.
- Benchmarks can be present in model training data. RustAssistant and RustRepoTrans state this threat.
- A passing test suite proves only the tested behavior. CRUST-Bench interfaces and tests are useful, but they are not full specifications.
- Manual taxonomies and semantic reviews contain judgment. RustRepoTrans reports high inter-rater agreement, but disagreement remains possible. The type-migration study shows different semantic judgments for the same 41 functions.
- Several studies use restricted edit scopes. A model can identify a dependency or manifest change but cannot apply it.
- Unsafe Rust, FFI, procedural macros, build scripts, feature resolution, async cancellation, embedded targets, and platform packaging have weak direct coverage in this evidence set.
- RustEvo is under construction. Its reported values can change.
- The 2026 cryptographic study is a narrow preprint. Its rates must not become a general Rust security rate.

## Language-level findings

The official sources below confirm the language behavior. The "LLM risk" column is an engineering inference unless it links the behavior to an empirical class above. Difficulty alone is not evidence that models fail on a feature.

| Rust behavior | Failure mode and likely LLM error | Official source | Coverage decision at the evidence cut-off |
|---|---|---|---|
| Two-phase mutable borrows apply only to selected implicit borrows. | `v.push(v.len())` can compile while an explicit `&mut v` form does not. A model can apply a false desugaring, predict a borrow error, or add an unnecessary clone. | [rustc dev guide: two-phase borrows](https://rustc-dev-guide.rust-lang.org/borrow_check/two_phase_borrows.html) | Add to a new `rust-borrow-semantics` skill. Include the three eligible implicit borrow forms and negative probes with explicit `&mut`. |
| Temporary lifetime extension depends on syntax. | A temporary usually ends at the statement, but an extending `let` pattern or expression can keep it to the end of the block. A model can apply one rule to `let x = &make()` and `call(&make())`. | [Reference: temporary lifetime extension](https://doc.rust-lang.org/reference/destructors.html#temporary-lifetime-extension) | Correct the absolute E0716 text in `rust-compiler-errors`. Put the full decision table in `rust-borrow-semantics`. |
| A `match` guard borrows before a move and can run more than once for an or-pattern. | A model can mutate a guarded binding, assume that the value moved before the guard, or duplicate a side effect. | [Reference: match guards](https://doc.rust-lang.org/reference/expressions/match-expr.html#match-guards) | Add a new `rust-pattern-semantics` skill with side-effect and move-timing tests. |
| A place scrutinee and a value scrutinee have different temporary behavior. | A model can treat `match x` and `match make_x()` as equivalent and select the wrong drop point or borrow lifetime. | [Reference: match scrutinee behavior](https://doc.rust-lang.org/reference/expressions/match-expr.html#scrutinee-behavior), [temporary scopes](https://doc.rust-lang.org/reference/destructors.html#temporary-scopes) | Add to `rust-pattern-semantics` and cross-link `rust-borrow-semantics`. |
| Method lookup uses an ordered autoderef and autoref candidate list. | A trait `&self` method can win before an inherent `&mut self` method. Lookup does not retry a later candidate after a mutability, lifetime, or unsafe error. A model can apply the false rule "inherent always wins." | [Reference: method calls](https://doc.rust-lang.org/reference/expressions/method-call-expr.html) | The content exists in `rust-discipline/references/trait-resolution.md`. Add routing terms such as `method ambiguity`, `autoderef`, `UFCS`, and `E0034`; do not duplicate it in a new skill. |
| Type inference is not fully bidirectional. | `d + n.into()` can stay ambiguous even when the result type is known. A model can add a turbofish at the wrong expression or change the public type. | [E0282](https://doc.rust-lang.org/error_codes/E0282.html), [E0284](https://doc.rust-lang.org/error_codes/E0284.html) | Extend `rust-compiler-errors` for E0282, E0283, and E0284. Teach the smallest type anchor, a typed local, or a fully qualified call. |
| Async closures always capture their input arguments. Lending futures restrict the implemented `Fn` traits. | A model can transfer ordinary closure rules to async closures and predict the wrong lifetime, `Send`, size, or reusable call bound. | [Reference: async closure traits](https://doc.rust-lang.org/reference/types/closure.html#async-closure-traits) | Extend `rust-async-internals` with unused-input capture, lending, and dereference-projection cases. |
| Creating an invalid typed value is immediate undefined behavior. | An unused null reference or invalid enum is already invalid. A model can delay the UB until dereference or treat initialized bits as a valid value. | [Reference: invalid values](https://doc.rust-lang.org/reference/behavior-considered-undefined.html#invalid-values), [`MaybeUninit`](https://doc.rust-lang.org/std/mem/union.MaybeUninit.html) | Strengthen `rust-unsafe`. State that reference creation itself has validity requirements. |
| A pointer contains provenance as well as an address. | Under Strict Provenance, an address round trip does not carry provenance. Exposed-Provenance reconstruction can use previously exposed provenance, but the selected provenance is ambiguous. A model can use `ptr as usize` and reconstruct a pointer for tagged-pointer code without proving that contract. | [`std::ptr` provenance](https://doc.rust-lang.org/std/ptr/index.html#provenance) | Extend `rust-unsafe` with `addr`, `map_addr`, `with_addr`, and a narrow exposed-provenance fallback. |
| Drop order differs by storage shape. | Locals drop in reverse declaration order. Fields drop in declaration order. By-move closure captures can drop in an unspecified order. A model can apply stack LIFO to all three. | [Reference: destructors](https://doc.rust-lang.org/reference/destructors.html), [closure drop order](https://doc.rust-lang.org/reference/types/closure.html#drop-order) | Extend `rust-callback-bounds` and the `rust-discipline` drop checklist for closure captures. |
| A `move` closure is not necessarily `FnOnce`. | The closure call trait depends on what the body does with captures. A model can add boxing or cloning because it maps `move` directly to `FnOnce`. | [Reference: closure call traits](https://doc.rust-lang.org/reference/types/closure.html#call-traits-and-coercions) | Add a direct rule and compile probes to `rust-callback-bounds`. |
| Closure capture precision depends on the projection and edition. | Fields can be captured separately, but arrays, packed fields, unions, raw pointers, `Box`, and custom `Deref` have different rules. A model can predict the wrong `Send`, lifetime, or drop behavior. | [Reference: capture precision](https://doc.rust-lang.org/reference/types/closure.html#capture-precision), [Edition Guide: disjoint capture](https://doc.rust-lang.org/edition-guide/rust-2021/disjoint-capture-in-closures.html) | Add a compact matrix to `rust-callback-bounds`. |
| Edition 2024 changes match ergonomics and some temporary scopes. | A source edit can compile but change lock or destructor timing. A model can treat an edition as syntax only or emit an old binding pattern as a universal fix. | [Edition Guide: match ergonomics](https://doc.rust-lang.org/edition-guide/rust-2024/match-ergonomics.html), [`if let` temporary scope](https://doc.rust-lang.org/edition-guide/rust-2024/temporary-if-let-scope.html) | `cargo-workflows` covers the scope change. Add routing terms and put binding-mode rules in `rust-pattern-semantics`. |
| Editions are selected per crate and crates of different editions interoperate. | A model can require one atomic workspace migration. At the evidence cut-off, the catalog said both "never use a per-crate older edition" and "migrate per crate." | [Edition Guide: editions](https://doc.rust-lang.org/edition-guide/editions/) | Correct the contradiction in `cargo-workflows`. Describe one workspace edition as the steady state and temporary per-crate overrides as a valid migration tool. |
| Coherence includes future legal implementations. | A blanket impl can block later concrete or pointer-forwarding impls. A model can inspect only current impls or promise future stable specialization. | [Reference: coherence](https://doc.rust-lang.org/reference/items/implementations.html#trait-implementation-coherence), [RFC 2451](https://rust-lang.github.io/rfcs/2451-re-rebalancing-coherence.html) | The catalog already has deep coverage in `rust-discipline`. Improve routing; do not add another skill. |
| `Pin` and `Send` or `Sync` have nonlocal contracts. | A model can treat every field of a pinned type as pinned or repair a thread error with an unsound manual auto-trait impl. | [`std::pin`](https://doc.rust-lang.org/std/pin/index.html#subtle-details-and-the-drop-guarantee), [Nomicon: Send and Sync](https://doc.rust-lang.org/nomicon/send-and-sync.html) | `rust-pin-projection`, `rust-send-sync`, and `rust-unsafe` already cover these areas well. Keep them as regression targets. |

## Ecosystem and toolchain findings

| Behavior | Failure mode and likely LLM error | Primary source | Current coverage and action |
|---|---|---|---|
| Resolver 3 prefers an MSRV-compatible dependency but does not guarantee one. | Cargo can select an incompatible version when no compatible version satisfies the requirement. A model can treat `rust-version` as a strict transitive bound and skip the real MSRV build. | [Cargo resolver: Rust version](https://doc.rust-lang.org/cargo/reference/resolver.html#rust-version) | Extend `cargo-workflows` and keep the actual minimal-toolchain lane in `rust-crate-release`. |
| `cargo check` skips code generation and linking. | Monomorphization, native symbols, and linker failures can appear only in build or test. A model can stop at the cheapest green command. | [`cargo check`](https://doc.rust-lang.org/cargo/commands/cargo-check.html#description) | Make the rule explicit in the main `cargo-workflows` file. Target skills already require final link and runtime proof. |
| Cargo features are additive and unify through the graph. | A model can treat features as exclusive runtime modes. Default CI can miss `--no-default-features`, and `--all-features` can be an invalid product. | [Cargo feature resolution](https://doc.rust-lang.org/cargo/reference/resolver.html#features), [feature combinations](https://doc.rust-lang.org/cargo/reference/features.html#feature-combinations) | Extend `cargo-workflows` with a project-owned feature matrix. Do not require `--all-features` when the combination is invalid. |
| A build script runs for the host. | `cfg!(target_os = "android")` in `build.rs` tests the host and can select the wrong library. | [Cargo build-script inputs](https://doc.rust-lang.org/cargo/reference/build-scripts.html#inputs-to-the-build-script) | `rust-native-linking` already covers `HOST`, `TARGET`, and `CARGO_CFG_*`. Keep this as a regression case. |
| Cargo configuration lookup starts at the invocation directory. | A member-local `.cargo/config.toml` can work from that member and disappear when CI runs Cargo from the workspace root. | [Cargo configuration hierarchy](https://doc.rust-lang.org/cargo/reference/config.html#hierarchical-structure) | Add to `cargo-workflows/references/cross-compilation.md`. |
| A disabled `tokio::select!` branch still evaluates its async expression. | Synchronous setup can allocate, panic, lock, or change state even when the branch condition is false. A model can read the precondition as a lazy `if`. | [`tokio::select!` lifecycle](https://docs.rs/tokio/latest/tokio/macro.select.html) | Add a runtime probe to `rust-async-internals`. |
| Dropping `tokio::task::JoinHandle` detaches the task. | The task can continue after owner teardown and its panic or result can be lost. A model can infer cancellation from RAII. | [`tokio::task::JoinHandle`](https://docs.rs/tokio/latest/tokio/task/struct.JoinHandle.html) | Add an explicit abort, cancel, and join lifecycle to `rust-async-internals`. |
| `Deserialize<'static>` is not a general deserialization bound. | It rejects useful borrowed data or causes needless allocation. A model can add `'static` to silence a lifetime error. | [Serde deserializer lifetimes](https://serde.rs/lifetimes.html) | Extend `rust-serde` with `Deserialize<'de>` versus `DeserializeOwned`. |
| A type can implement `Serialize` but be invalid for one format. | JSON accepts string-like scalar map keys, including integers, but rejects unsupported compound keys. A model can treat a derive as proof of format compatibility. | [`serde_json::to_string` errors](https://docs.rs/serde_json/latest/serde_json/fn.to_string.html#errors), [`MapKeySerializer`](https://docs.rs/serde_json/latest/src/serde_json/ser.rs.html#795-1142) | Add a data-model capability table and a boundary round-trip test to `rust-serde`. |
| `serde_json::Value` does not represent every Rust integer by default. | `Number::from_i128` and `Number::from_u128` can fail without `arbitrary_precision`. A separate conversion through `f64` can lose precision. The streaming serializer can write `i128` and `u128` directly. | [`serde_json::Number`](https://docs.rs/serde_json/latest/serde_json/value/struct.Number.html), [serializer implementation](https://docs.rs/serde_json/latest/src/serde_json/ser.rs.html#114-150) | Add separate rules for the `Value` or `Number` DOM path and the streaming serializer. Test boundary values without a conversion through `f64`. |
| Dropping a `catch_unwind` payload can itself panic. | An FFI boundary can catch one panic and then abort during payload destruction. A model can treat `Err(payload)` as a harmless opaque value. | [`catch_unwind` notes](https://doc.rust-lang.org/std/panic/fn.catch_unwind.html#notes) | Extend `rust-panic-safety` with a payload disposal policy and a double-panic test. |
| `C-unwind` is not a cross-language exception adapter. | Unwinding through a non-unwind ABI is undefined. Catching a foreign exception with `catch_unwind` has unspecified behavior. | [Reference: FFI unwinding](https://doc.rust-lang.org/reference/panic.html#unwinding-across-ffi-boundaries) | `rust-panic-safety` already covers the boundary. Preserve the exact limitation. |
| Cross-compiled tests need a runner to execute. | `cargo test --target ...` can fail with an execution-format error, or an agent can report compile-only evidence as an executed test. | [Cargo target runner](https://doc.rust-lang.org/cargo/reference/config.html#targettriplerunner) | Extend the general cross-compilation reference in `cargo-workflows`. |
| Cargo target selection cannot depend on `cfg(feature = "...")`. | A target dependency or target configuration can silently fail to select the intended feature-specific path. | [Cargo platform-specific dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#platform-specific-dependencies), [target configuration](https://doc.rust-lang.org/cargo/reference/config.html#target) | Add next to feature resolution in `cargo-workflows`. |
| Cargo removes `RUSTFLAGS` from the build-script environment. | A nested `rustc` invocation can miss target or sanitizer flags. `CARGO_ENCODED_RUSTFLAGS` is for `rustc`; a C or C++ compiler needs its own target-specific `CC` and `CFLAGS` channel. | [Cargo build-script environment](https://doc.rust-lang.org/cargo/reference/environment-variables.html#environment-variables-cargo-sets-for-build-scripts) | Add the `rustc` and native-tool distinction to `rust-native-linking`. |
| One Miri execution is not exhaustive. | A green run can miss a layout or schedule dependent defect, and unsupported FFI or platform operations stay outside the run. | [Miri README: multiple executions](https://github.com/rust-lang/miri/#testing-multiple-different-executions) | `rust-sanitizers-miri` already explains the limits. Prefer a bounded many-seed CI example. |
| MemorySanitizer needs an instrumented standard library and dependency graph. | Instrumenting only the application can create false positives. | [Rust sanitizer documentation](https://doc.rust-lang.org/nightly/unstable-book/compiler-flags/sanitizer.html#memorysanitizer) | Already covered by `rust-sanitizers-miri`; keep as a regression check. |
| `wasm32-unknown-unknown` has `std` without a normal operating system. | Printing can do nothing, file APIs can fail, and thread creation can panic. A model can equate `std` with host services. | [rustc target documentation](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html) | Already covered by `rust-wasm`; no new skill is needed. |

## Skill-gap mapping and implementation status

The catalog had 42 skills at the evidence cut-off. The current repository has 44 skills and
implements the complete backlog below. The two new entry points are
[`rust-borrow-semantics`](../skills/rust-borrow-semantics/SKILL.md) and
[`rust-pattern-semantics`](../skills/rust-pattern-semantics/SKILL.md). The focused changes live
in their existing topic skills. A general `rust-llm-errors` skill still duplicates those topic
skills and is not recommended.

The harness now supports `rust,run` behavior probes, strict `compile_fail` error-code checks, and
catalog-to-routing-graph parity. These checks turn the cross-cutting compile and behavior rules
into observed gates where a portable example can express them.

### Implemented corrections

| Existing skill | Confirmed problem | Implemented correction | Current validation |
|---|---|---|---|
| `rust-compiler-errors` | Its E0716 row said an unnamed temporary dies at the end of the statement. This was not universal because temporary lifetime extension is syntax-sensitive. | The row now states the syntax-sensitive rule and routes full analysis to `rust-borrow-semantics`. | The harness runs extending-`let` and method-receiver probes and requires E0716 and E0502 negative probes. |
| `cargo-workflows` | The main file forbade a per-crate older edition, while its migration reference used temporary per-crate editions. | One inherited edition is now the steady state. Explicit per-crate editions are permitted during a staged migration. | Catalog validation passes. A consuming workspace must still run the documented mixed-edition migration lane. |

### Implemented new skills

| Skill | Distinct triggers | Completion contract | Why it is not an extension |
|---|---|---|---|
| `rust-borrow-semantics` | `temporary lifetime`, `drop scope`, `two-phase borrow`, `place expression`, `E0716 after desugaring` | Identify the exact place or value expression, temporary scope, reservation and activation points, and drop point. Prove the result with the smallest compiling or compile-fail probe. | `rust-compiler-errors` is diagnostic-driven. This skill also owns design and review questions that have no compiler error. |
| `rust-pattern-semantics` | `match guard`, `partial move`, `binding mode`, `match ergonomics`, `scrutinee lifetime`, `ref pattern` | State each binding mode, move or borrow point, guard evaluation count, and edition-dependent rule. Add a behavior or compile-fail test. | Pattern rules form a distinct user vocabulary and validation workflow. They do not fit cleanly in general style or borrow-error triage. |

The repository does not add `rust-trait-resolution`; the deep material and routing remain under
`rust-discipline`. It also does not add `rust-type-inference`; E0282, E0283, and E0284 remain a
focused section in `rust-compiler-errors` until that material needs an independent workflow.

### Implemented focused extensions

| Existing skill | Implemented coverage | Evidence class addressed | Original priority |
|---|---|---|---|
| `cargo-workflows` | Resolver 3 and MSRV limits, invocation-directory config lookup, a valid feature matrix, cross-test runners, target-cfg restrictions, and the `cargo check` boundary. | Ecosystem drift, dependency mismatch, false validation. | High |
| `rust-async-internals` | Disabled `select!` expression evaluation, detached `JoinHandle`, and async closure capture or lending rules. | Runtime semantic defects after a clean build. | High |
| `rust-serde` | `Deserialize<'de>` versus `DeserializeOwned`, format-specific map keys, large-number policy, and boundary round trips. | Type fixes that compile but break wire behavior. | High |
| `rust-unsafe` | Immediate invalid-value UB and stable Strict Provenance APIs. | Unsafe code that compiles but is unsound. | High |
| `rust-panic-safety` | Safe handling of a panic payload whose destructor can panic. | Boundary code that catches one panic and aborts on cleanup. | High |
| `rust-callback-bounds` | `move` call traits, capture precision, and closure capture drop order. | Wrong bounds, unnecessary clones, and hidden lifetime or `Send` changes. | Medium |
| `rust-native-linking` | `CARGO_ENCODED_RUSTFLAGS` for nested `rustc`, separate from target-specific native compiler flags. | Cross-target build drift. | Medium |
| `rust-discipline` | Routing for method lookup, UFCS, autoderef, E0034, and coherence. | Invented or misresolved APIs and traits. | Medium |
| `rust-compiler-errors` | Minimal type anchors for E0282, E0283, and E0284. | Type and trait mismatch repair loops. | Medium |
| `rust-sanitizers-miri` | A bounded many-seed example. | False confidence from one green dynamic run. | Low |

### Cross-cutting LLM-resistant contract

These rules live in the skills that own each workflow. The repository does not create one
meta-skill that repeats them.

1. Compile after the smallest coherent patch. Group cascading diagnostics by root cause.
2. Run code generation and linking when the change can reach monomorphization, native symbols, or a final artifact. `cargo check` is not enough.
3. Run behavior tests after compilation. A green compiler does not prove the requested semantics.
4. Search and update all callers after a signature, ownership, visibility, constness, or mutability change.
5. Reject `todo!()`, `unimplemented!()`, omitted files, and prose placeholders unless the task explicitly requests a stub.
6. Test the declared MSRV, supported targets, and project-owned feature combinations. Do not infer these from the current host build.
7. Run domain checks for properties that Rust does not encode, such as nonce uniqueness, protocol compatibility, archive safety, or UI lifecycle.
8. Inspect the final diff for unrelated rewrites, code deletion, weakened qualifiers, broad clones, new `unsafe`, and dependency edits.

These rules follow the empirical pattern: compiler feedback fixes many local errors, but incomplete output, error cascades, semantic regressions, API drift, and domain defects remain.

## Source inventory

- Deligiannis et al. [Fixing Rust Compilation Errors using LLMs](https://arxiv.org/abs/2308.05177). See also the [Microsoft Research publication page](https://www.microsoft.com/en-us/research/publication/fixing-rust-compilation-errors-using-llms/) and [paper PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/08/paper.pdf).
- Khatry et al. [CRUST-Bench: A Comprehensive Benchmark for C-to-safe-Rust Transpilation](https://arxiv.org/abs/2504.15254). See also the [official dataset repository](https://github.com/anirudhkhatry/CRUST-bench) and [leaderboard](https://crust-bench.github.io/).
- Liu et al. [RustRepoTrans paper](https://mingwei-liu.github.io/assets/pdf/ase2025rustrepotrans.pdf). See also the [official benchmark repository](https://github.com/SYSUSELab/RustRepoTrans).
- [Type-migrating C-to-Rust translation using a large language model](https://link.springer.com/article/10.1007/s10664-024-10573-2), Empirical Software Engineering.
- [An Empirical Security Evaluation of LLM-Generated Cryptographic Rust Code](https://arxiv.org/abs/2604.27001).
- [RustEvo official benchmark repository](https://github.com/SYSUSELab/RustEvo).
- [Multi-SWE-bench official project](https://multi-swe-bench.github.io/), [repository](https://github.com/multi-swe-bench/multi-swe-bench), and [paper](https://arxiv.org/abs/2504.02605).
- [MultiPL-E official repository](https://github.com/nuprl/MultiPL-E). This benchmark supplies compiler-and-test infrastructure for translated HumanEval and MBPP tasks, including Rust. This first pass does not use it for a Rust error rate because its public summary does not give the required Rust-specific taxonomy.
