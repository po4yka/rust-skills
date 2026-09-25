# Rust Pitfalls and LLM Errors: Evidence Map

Status: evidence complete for the stated cut-off; implementation mapping current

Evidence cut-off: 2026-08-20

Addendum cut-off: 2026-09-24. The addendum adds sources published from 2026-08-20 to 2026-09-24, and three earlier sources the first pass missed. It does not change the original findings.

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

### Addendum method

The addendum repeats the search for the period from 2026-08-20 to 2026-09-24. Two independent searches used the arXiv API, ACL Anthology, OpenReview, ACM DL, IEEE Xplore, USENIX, benchmark repositories, leaderboards, dataset cards, and vendor system cards. Where the two searches disagreed on a number or a classification, this document uses the primary source. "Study limitations and open evidence risks" records the differences that the primary source did not resolve.

The addendum adds these task types:

- native Rust repository issue resolution;
- repository-level Rust unit-test generation;
- contest-style Rust code generation with runtime errors;
- C-to-Rust refactoring tools evaluated for memory security;
- agentic porting of one C library with differential fuzzing.

The tables mark each new source with "Addendum". "Addendum, pre-cut-off" marks a source that was published before 2026-08-20 and that the first pass missed. Neither search found a revision after 2026-08-20 of a source that the first pass used.

## Main findings

1. Compiler failure is still the main observed failure mode in repository translation. RustRepoTrans reports that 1,614 of 1,748 unsuccessful samples failed to compile. This is 92.3% of the unsuccessful samples.
2. The most repeated compiler-level classes are missing or invented APIs, unresolved context, type mismatches, missing trait implementations, and borrow or mutability errors.
3. Compiler feedback improves many results. It does not remove incomplete implementations or semantic defects. It can also introduce new type and borrow errors.
4. A successful build is weak evidence of correctness. Tests found semantic regressions in RustAssistant. Tests also separated build success from functional success in CRUST-Bench.
5. Security properties need checks outside the compiler. A cryptographic Rust study found domain-specific vulnerabilities in 32 of 56 samples that compiled.
6. The current evidence is translation-heavy. It gives less direct evidence for macros, build scripts, async Rust, unsafe Rust, FFI, embedded Rust, and large native Rust maintenance tasks.

Addendum findings. These findings come from the sources that the addendum adds. They extend findings 1 to 6. They do not replace them.

7. Native Rust repository work now has direct evidence. In Rust-SWE-bench (pre-cut-off), name, scope, and path resolution errors caused 43.7% of the agent compile errors, and type and trait errors caused 32.6%. Its most frequent codes, E0599, E0433, E0432, E0425, E0308, and E0277, also lead the translation studies. This narrows the maintenance gap in finding 6. It does not close the gap for macros, build scripts, async Rust, unsafe Rust, FFI, or embedded Rust.
8. A compile repair can move a defect to run time or to the toolchain. In one C-to-Rust study, an LLM repair loop removed compile errors with `unwrap()` calls, unstable feature flags, and new crate dependencies. This is a qualitative observation with no counts, and the repair agent was an auxiliary tool of the authors, not a subject of the study. Repository inference: an added `unwrap()` can panic, and an unstable feature flag needs a nightly compiler. The paper does not measure either consequence.
9. A passing generated test is weak evidence. In Rust unit-test generation, 28.3% of the passing test suites did not call the focal function. In Rust-SWE-bench, 35.5% of the failed issue reproductions used tests that did not exercise the reported behavior.
10. Memory safety does not prove behavioral equivalence. Five agentic ports of one C library had zero `unsafe` blocks and no memory-safety crashes under fuzzing. Differential fuzzing against the C library still found divergences in four of the five ports within seconds.
11. A safety rule in a prompt is not enforcement. In one LLM-based C-to-Rust tool, the prompt required safe Rust and no raw pointers. The study shows output that uses an `unsafe` block and raw pointers.
12. Runtime panics are a residual class after a clean build. In LLM-generated Rust contest solutions (pre-cut-off), numeric overflow caused 44.0% of the classified runtime errors, and out-of-bounds access caused 28.1%. The authors attribute the overflow share to overflow checks in debug builds.

## Primary source evidence

| Source | Task and data | Quantitative result | Error evidence | Important limits |
|---|---|---|---|---|
| [Fixing Rust Compilation Errors using LLMs](https://www.microsoft.com/en-us/research/publication/fixing-rust-compilation-errors-using-llms/) ([paper PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/08/paper.pdf), [arXiv](https://arxiv.org/abs/2308.05177)) | RustAssistant repairs compiler errors. The evaluation uses 270 compiler-error microbenchmarks, 50 Stack Overflow programs, and 182 real commits from popular crates. | With GPT-4 and five completions per prompt, Table 1 reports 252 of 270 microbenchmarks. The corresponding results are 36 of 50 Stack Overflow programs and 134 of 182 commits. The paper is internally inconsistent because the abstract and nearby prose state 250 of 270 and 92.59%. | Syntax, types, generics, traits, ownership, and lifetimes. Failure cases include partial cross-file repair, fix-and-undo loops, and a required dependency edit outside the allowed edit scope. | The study uses older model snapshots and Rust 1.67.1. It can contain training contamination. It excludes package configuration, build configuration, FFI, and unsafe Rust from the microbenchmarks. Human semantic review is subjective. |
| [CRUST-Bench: A Comprehensive Benchmark for C-to-safe-Rust Transpilation](https://arxiv.org/pdf/2504.15254) ([dataset repository](https://github.com/anirudhkhatry/CRUST-bench), [project page](https://crust-bench.github.io/)) | Repository-level C-to-safe-Rust translation for 100 C repositories. The benchmark supplies manually written safe Rust interfaces and tests. | In one-shot generation, the strongest shown build/test results were 43/22 for Claude Opus 4 and 35/19 for OpenAI o3. After three compiler-repair rounds, these were 78/29 and 68/31. After test repair, o3 reached 48 passing tasks. | Type mismatch, borrowing, missing symbols, incomplete code, trait errors, wrong arguments, and unsafe or unstable code. Incomplete outputs include placeholders and comments such as "similarly" instead of code. | This is C translation, not general Rust work. Results depend on a prompt that forbids unsafe code. Tests are incomplete specifications. Coverage data covers only part of the dataset. |
| [RustRepoTrans: Repository-Level Code Translation Benchmark Targeting Rust](https://mingwei-liu.github.io/assets/pdf/ase2025rustrepotrans.pdf) ([benchmark repository](https://github.com/SYSUSELab/RustRepoTrans)) | 375 incremental repository translation tasks: 122 Java-to-Rust, 145 C-to-Rust, and 108 Python-to-Rust tasks. | Of 1,748 unsuccessful samples, 1,614 failed to compile. Failed samples had 1 to 193 compiler errors, with a mean of 7.7 and a median of 3. Repository context reduced Pass@1 by 16.2 to 30.8 points against the compared function-level benchmark. | The most frequent compiler codes were E0599, E0425, E0308, E0277, E0609, and E0433. The study maps them to target-feature misunderstanding, cross-language differences, dependency resolution, signature mismatch, syntax, and missing context. | The benchmark gives the model selected repository context. It does not fully test global-state migration or all static and dynamic analysis methods. Translation data can be present in model training data. The taxonomy uses manual coding. |
| [Type-migrating C-to-Rust translation using a large language model](https://link.springer.com/article/10.1007/s10664-024-10573-2) | Whole-program C-to-Rust type migration with compiler suggestions and LLM repair. | The full GPT-4o-mini method reduced type errors by 71.5% against its ablation baseline. It still left a mean of 1,155.3 type errors per program. Only 55.9% of functions had no local type errors in the best setting. | Missing explicit casts, incompatible numeric operations, and incorrect target types. Compiler suggestions do not cover all mixed-type operations. | Most full programs did not compile. This prevented full semantic test execution. A manual 41-function sample showed evaluator disagreement about semantic correctness. This is C migration, not native Rust generation. |
| [An Empirical Security Evaluation of LLM-Generated Cryptographic Rust Code](https://arxiv.org/pdf/2604.27001) | 240 single-file AEAD samples from three models, two algorithms, four prompt styles, and ten repetitions. | Only 56 of 240 samples compiled. Of 184 compilation failures, the paper assigns 41.3% to API hallucinations, 28.6% to type errors, 18.5% to trait errors, and 11.6% to unresolved imports. A domain-specific analyzer found findings in 32 of 56 compiling samples. | Invented cryptographic APIs, incorrect types and traits, unresolved imports, panic through `unwrap()`, nonce reuse, and a hard-coded key. | This is a 2026 preprint and a narrow AEAD study. It uses small samples per configuration. Its custom analyzer has limited single-file rules. It can miss indirect and cross-module defects. The result needs replication. |
| [RustEvo benchmark repository](https://github.com/SYSUSELab/RustEvo) | Rust code generation across 588 API changes from the standard library and 15 crates, for Rust 1.71 through 1.84. | The repository reports lower mean Pass@1 for behavioral changes (38.0%) and deprecations (40.4%) than for stabilizations (65.8%) and signature changes (58.2%). | API version drift, behavioral change, deprecation, signature change, and new stable API use. | The repository marks the benchmark as under construction. Treat its current numbers as provisional. It does not yet give a stable, peer-reviewed error taxonomy. |
| [Multi-SWE-bench](https://multi-swe-bench.github.io/) ([repository](https://github.com/multi-swe-bench/multi-swe-bench), [paper](https://arxiv.org/abs/2504.02605)) | Real repository issue repair in seven languages. The dataset includes 239 Rust tasks in a total of 1,632 tasks. | The public aggregate leaderboard does not isolate a Rust error rate. Addendum: the paper's Table 4 reports per-language resolved rates, including Rust, for nine 2024–2025 models. | The benchmark can support future study of real Rust maintenance failures and agent behavior. | Current public summary results combine languages. They do not provide a Rust-specific error taxonomy. Do not use the aggregate rate as a Rust rate. |
| **Addendum, pre-cut-off.** [Evaluating and Improving Automated Repository-Level Rust Issue Resolution with LLM-based Agents](https://arxiv.org/abs/2602.22764) (Rust-SWE-bench, ICSE 2026; [benchmark repository](https://github.com/GhabiX/Rust-SWE-Bench)) | 500 issue-resolution tasks from 34 Rust repositories. Four agents (OpenHands, SWE-agent, Agentless, and AutoCodeRover) with four model snapshots from 2024 and 2025 (Claude 3.7 Sonnet, GPT-4o 2024-11-20, o4-mini, and Qwen3). | The best studied configuration resolved 21.2% of tasks. The authors' own agent, RustForger, resolved 28.6%. The baseline agents reproduced at most 55.5% of the issues. When the authors disabled reproduction in the best configuration, its resolution rate fell by 42%. | Table 4 ranks the compile errors that agents met during their runs: E0599 18.06%, E0433 16.21%, E0432 12.08%, E0425 8.54%, E0308 6.81%, E0277 6.50%, and E0412 5.69%. The authors group E0433, E0432, E0425, E0412, and E0405 as repository-structure errors (43.7%), and E0599, E0308, E0277, and E0407 as type and trait errors (32.6%). No ownership or borrow code appears among the 13 listed codes. Of the failed reproductions, 52.5% came from dependency or workspace configuration, 35.5% from tests that did not exercise the reported behavior, and 12.0% from tests that did not compile. | 2024 and 2025 model snapshots. The paper does not state its Rust version. The table counts errors during agent runs, not errors in final patches, and it lists only the most frequent codes. RustForger is the authors' method, so its result is not an independent baseline. |
| **Addendum, pre-cut-off.** [Unreliable in Practice? A Comprehensive Study of Errors in LLM-Generated Code](https://arxiv.org/abs/2608.00661) (ISSRE 2026) | 1,651 CodeNet contest problems from the PROBE dataset in C++, Java, C, and Rust. Seven 2024 and 2025 models with a baseline prompt and a chain-of-thought prompt. The baseline setting includes up to two regenerations after test feedback; the chain-of-thought setting is single-pass. Across both prompts, 23,416 Rust samples failed to compile and 11,038 Rust samples had a runtime error. | Rust compile errors, baseline prompt (Table VI, n = 12,942): incompatible parameter types 43.4%, missing import 20.5%, ownership and lifetime 16.7%, and trait or type bound 6.1%. Rust runtime errors, baseline prompt (Table X): numeric overflow 44.0% (2,508 samples) and out-of-bounds access 28.1%. | Overflow errors are frequent in Rust and rare in the other three languages. The authors attribute this to Rust overflow checks in debug builds, and they state that the other languages overflow silently. | Contest problems, not repository work. An LLM classifier assigns the labels; its exact-match accuracy against manual labels is 0.91 for Rust compile errors and 0.84 for Rust runtime errors (Table IV). The analysis excludes wrong output and timeouts. The paper does not state its Rust toolchain or build profile. The text and the tables disagree on some counts, for example 43.9% against 44.0% for the overflow share. |
| **Addendum, pre-cut-off.** [When LLMs Invent Rust Crates: An Empirical Study of Hallucination Patterns and Mitigation](https://arxiv.org/abs/2606.08444) (Internetware 2026) | 2,794 Rust coding tasks from Stack Overflow, GitHub, and LLM-generated task descriptions. 14 models from six families. The study parses crate names from generated source and compares them with a crates.io name list. It does not compile the code. | The parser flagged 10,779 of 48,494 extracted crate references (22.23%). Self-refinement lowered the rate by 2.22 to 3.26 percentage points on three open models. Retrieval changed it by -1.92, -0.96, and +0.34 points on the same models. | The authors classify 45.47% of the flagged names as standard-library modules used as crates, for example `thread`. They report that many other flagged names are near-miss variants of real crate names: in 32.96% of 13,332 analyzed cases, the flagged name lacks a hyphen that the matching real crate name has. Of the frequent names that are not modules, 38.9% come from other language or platform ecosystems. | The detector flags the first segment of any `name::item` path that is not a crate name. Valid code, such as `Duration::from_secs` after a `use` declaration, can match this rule. The authors state that the metric can include false positives and does not measure build failures. Repository inference: the paper's own examples look like parser artifacts. The hyphen examples `httpresponse`, `tokentree`, `servicebuilder`, and `genericarray` are lowercased type names (`HttpResponse`, `TokenTree`, `ServiceBuilder`, `GenericArray`). The cross-domain examples are `queryparser`, which is also a lowercased Rust type name (`QueryParser`), and `winuser`, a module of the `winapi` crate. The top-10 list contains type names such as `duration`, `vecdeque`, and `ordering`, and `t`-prefixed names such as `trefcell` and `tu32`. Rust source spells a hyphenated crate name with underscores, so a source parser cannot observe a missing hyphen. Treat all of the study's pattern findings as indirect and likely inflated: the 22.23% rate, the 45.47% module share, the 32.96% hyphen share, and the 38.9% cross-domain share. |
| **Addendum.** [XRepoTest: Benchmarking Multilingual Repository-Level Unit Test Generation for Large Language Models](https://arxiv.org/abs/2608.25939) (v1 2026-08-26, v2 2026-09-15, accepted to EMNLP 2026; [artifact](https://github.com/solis-team/XRepoTest)) | Repository-level unit-test generation for 3,642 focal functions in five languages. Rust has 931 focal functions from eight repositories. 14 models. Tests run with `cargo test` in Docker. | In the standard-context setting, the best Rust test pass rate was 12.78%. With file-level context, the best was 21.16%. 28.3% of the passing Rust test suites did not call the focal function, against 9.7% across all five languages. The Rust mutation score (MS) was at most 4.14%, but MS counts every sample whose tests fail as 0. On passing samples only (MS@Pass), the mean Rust mutation score was 50.69% to 87.70% for 13 of the 14 models; the table gives 0.00 for the fourteenth (Table A.5). A headless Claude Code agent raised the Rust pass rate from 38.5% to 72.3% on a stratified subset (Table 5). | In the standard setting, Table 4 assigns 48.05% of Rust outcomes to API hallucination, 26.42% to logic and assertion errors, and 11.31% to type-system and memory errors. With file-level context, these shares are 36.09%, 30.79%, and 14.82%. Of the Rust API hallucinations, 77.9% in the standard setting and 72.9% with context are "Phantom Library" cases, which the paper defines as imports of non-existent packages (Table A.13). The authors call Rust "a scaffolding bottleneck". | Test generation, not implementation work. One prompt and one decoding configuration. The paper does not state its Rust version. It does not say if "Phantom Library" separates an invented crate from a real crate that is absent from `[dev-dependencies]`. The authors state that small differences between models with a low Rust pass rate can be statistically unreliable. |
| **Addendum.** [C-to-Rust Fallacy: Automatic Refactoring ≠ Memory Security](https://arxiv.org/abs/2609.25682) (preprint, 2026-09-22) | Four C-to-Rust refactoring tools on 116 NIST Juliet C programs with memory-safety bugs, for 464 Rust programs. Two tools, C2SaferRust and FLOURINE (spelled FLUORINE in the paper body), use an LLM. The authors add a Claude Sonnet 4 compile-repair agent with `cargo build` as its tool and five attempts. | Table 2: 342 of 464 programs failed to compile before the repair agent, and 51 failed after it. In the 413 programs that compiled, the tools mitigated 236 original bugs and kept 177 (Table 3). The tools added 77 new bugs (Table 5): 52 for C2Rust-analyze, 11 for CROWN, 8 for C2SaferRust, and 6 for FLOURINE. | E0308 occurs in the output of all four tools. The repair agent replaced invalid dereferences of `Option` wrappers with `unwrap()` calls, and it added unstable feature flags and crate dependencies. The paper reports these repairs qualitatively, with no counts. The FLOURINE prompt required safe Rust and no raw pointers; the study counts six bugs from conflicting prompt constraints. Of the 77 new bugs, 46 are panics in `pub unsafe extern "C" fn` functions that C code can call. The two static tools produced 44 of these 46. | Preprint. Small synthetic programs. Bug detection combines six Clippy lints, ASan, Miri, and an LLM agent, so the authors call the counts a lower bound. The paper does not state its Rust toolchain. It labels a panic across an FFI boundary as undefined behavior; that label holds only before Rust 1.81.0 (see "A panic at an FFI boundary is version-sensitive"). The prose gives 84 and 108 mitigated bugs for the two LLM tools, but Table 3 gives 84 for C2SaferRust and 109 for FLOURINE, and only the table sums to 236. This map uses the table. |
| **Addendum.** [LLM-Assisted Porting of Security-Critical C Libraries to Idiomatic Rust: A Multi-Model Empirical Study](https://doi.org/10.3390/fi18090471) (Future Internet 18(9):471, 2026-09-07) | One manual expert port and five agentic LLM ports of cJSON, about 3,200 lines of C with 14 CVEs. The prompt required zero `unsafe` and comprehensive tests. Rust 1.93.1 stable, with 1.95.0 nightly for the verification tools only. | All six ports had zero `unsafe` blocks and eliminated the in-scope CVEs. The five LLM ports had 0 to 9 residual bugs (Table 6). Differential fuzzing against C found a divergence within the first seconds in four of the five LLM ports. In five repeated runs of one model, two ports panicked on multi-byte (non-ASCII) input. | The ports were memory-safe but did not match C behavior. One port validated the remaining input as UTF-8 for each character, which is O(n²). A 12-line fix reduced its geometric-mean time from 2.12 to 0.99 times the C time. | One compact, single-threaded library that has been public since 2011, so training contamination is possible. Only one model was repeated. Because the prompt required zero `unsafe`, the zero-`unsafe` result does not show what a model does without that rule; the authors state this circularity. |

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
| API and context hallucination | The model calls a method that does not exist. It names a missing item, field, crate, module, or import. | RustRepoTrans reports E0599, E0425, E0609, E0433, and E0432 among its most frequent codes. The cryptographic study assigns 41.3% of compile failures to API hallucinations and 11.6% to unresolved imports. Addendum: Rust-SWE-bench assigns 43.7% of agent compile errors in native repositories to name, scope, and path resolution. In the standard setting, XRepoTest assigns 48.05% of Rust test-generation outcomes to API hallucination, and 77.9% of those to imports of packages that do not exist (36.09% and 72.9% with file-level context). Indirect evidence only: the crate hallucination study reports near-miss crate names and names from other ecosystems, but it parses source without compiling it, and its examples are likely inflated by lowercased type names. |
| Type and trait mismatch | The model selects the wrong concrete type. It omits a conversion. It assumes that an operator or trait implementation exists. | RustRepoTrans reports E0308 and E0277 as frequent codes. The type-migration study shows that required numeric casts are often absent. The cryptographic study assigns 28.6% of compile failures to type errors and 18.5% to trait errors. Addendum: Rust-SWE-bench assigns 32.6% of agent compile errors to type and trait semantics. In contest code, incompatible parameter types caused 43.4% of Rust compile errors. |
| Ownership, borrowing, lifetime, and mutability | The model moves a value too early. It creates conflicting borrows. It applies immutable and mutable borrows inconsistently. It does not propagate a lifetime or ownership change to callers. | RustAssistant directly evaluates ownership, lifetime, and trait failures. CRUST-Bench reports borrowing as a major class. RustRepoTrans gives an example that passes one variable as both `&value` and `&mut value` under an incompatible design. Addendum: in contest code, ownership and lifetime errors caused 16.7% of Rust compile errors. Rust-SWE-bench lists no ownership or borrow code among its 13 most frequent agent compile errors. |
| Signature and call mismatch | The model changes a function but not its call sites. It uses the wrong number or order of arguments. | RustRepoTrans reports E0061 and a signature-inconsistency category. RustAssistant reports partial fixes that do not propagate through the call graph. |
| Incomplete implementation | The output ends early. It leaves `unimplemented!()`, a placeholder, or a prose comment in place of code. | CRUST-Bench identifies unimplemented or incomplete output as a large residual class. It links some cases to output truncation and placeholder text. |
| Repair loop and error cascade | A repair removes one error and restores an earlier error. A semantic repair introduces a new borrow or type error. | RustAssistant reports fix-and-undo loops. CRUST-Bench reports that test-based repair can reduce build success by 5 to 20 points because aggressive changes introduce compiler errors. |
| Compiles but changes behavior | The edit satisfies the compiler but changes the required result. | In a RustAssistant microbenchmark, a repair replaced an invalid float shift with multiplication by 2.0. The intended shift by two bits corresponds to multiplication by 4. The code compiled but its test failed. RustAssistant also found 13 test failures in one single-attempt microbenchmark setting. Addendum: in the cJSON port study, differential fuzzing against C found divergences in four of five memory-safe LLM ports. |
| Compiles but violates a security invariant | The code type-checks, but it can panic or misuse a cryptographic primitive. | The cryptographic Rust study reports findings in 32 of 56 compiling samples. It includes `unwrap()` on fallible operations, nonce reuse, and a hard-coded key. Addendum: in the C-to-Rust Fallacy study, four refactoring tools kept 177 original memory-safety bugs in 413 compiling programs and added 77 new bugs. 46 of the new bugs are panics in functions that C code can call; see the version note under "Quantitative details". |
| Ecosystem and version mismatch | The model uses an API from the wrong crate or Rust version. It misses a deprecation or a behavioral change. | RustEvo is direct but provisional evidence. RustAssistant also reports a case that needed a dependency update in `Cargo.toml`, which its repair scope did not permit. |
| **Addendum.** Repair moves the defect to run time or to the toolchain | A repair removes a compile error with `unwrap()`, a nightly `#![feature]` gate, a new crate, or a return to `unsafe` code. The build passes, but the code can panic, needs an unstable compiler, or keeps the original unsafety. | The C-to-Rust Fallacy study reports `unwrap()`, feature-flag, and crate additions from a Claude Sonnet 4 repair loop, qualitatively and with no counts. It also reports that C2SaferRust restores the unsafe C2Rust output of a function after five failed repair attempts. |
| **Addendum.** Passing test does not exercise the target | A generated test passes, but it calls a mock, a stub, or an unrelated public API instead of the changed function. | XRepoTest reports that 28.3% of passing Rust test suites did not call the focal function. In Rust-SWE-bench, 35.5% of failed reproductions used tests that did not exercise the reported behavior. |
| **Addendum.** Safety rule stated only in the prompt | The prompt forbids `unsafe` or raw pointers, and the output uses them. A text search after generation reports the violation but does not prevent it. | The C-to-Rust Fallacy study reports this for FLOURINE and counts six bugs from conflicting prompt constraints. |
| **Addendum.** Runtime panic on unexercised input | The code compiles and passes its own tests, but it panics on other input: an integer overflow, an out-of-bounds index, or multi-byte UTF-8. | The ISSRE 2026 contest study assigns 44.0% of Rust runtime errors to numeric overflow and 28.1% to out-of-bounds access. In the cJSON port study, two of five runs of one model panicked on non-ASCII input. |

## Quantitative details that affect validation design

### Compiler feedback helps, but it has a limit

RustAssistant groups related diagnostics and applies iterative patches. Its full GPT-4 prompt fixed 252 of 270 microbenchmarks in the reported prompt ablation. A minimal prompt fixed 139 of 270. This result shows that diagnostic selection and patch format materially affect repair quality.

CRUST-Bench shows a similar effect at repository scale. Three compiler-repair rounds increased build success from 35 to 68 tasks for o3 and from 43 to 78 tasks for Claude Opus 4. Functional success stayed much lower at 31 and 29 tasks.

Compiler feedback can also reach a plateau. CRUST-Bench reports that borrowing and trait errors fall sharply in early repair rounds, while some type mismatches remain. The paper also reports that test repair can introduce new compiler errors.

Use compiler feedback as a repair input. Do not use a clean build as the completion condition.

Addendum: a repair loop can satisfy the compiler by weakening the code. In the C-to-Rust Fallacy study, the Claude Sonnet 4 repair agent reduced compile failures from 342 to 51 of 464 programs. It replaced invalid `Option` dereferences with `unwrap()` calls and added unstable feature flags and crate dependencies. The paper reports these repairs qualitatively, with no counts, and it states that the repair agent is an auxiliary tool, not a focus of its contributions. That the repaired code can panic or needs a nightly compiler is a repository inference. The LLM-based tool C2SaferRust restores the unsafe C2Rust output of a function after five failed repair attempts. Before you accept a repair, inspect its diff for new `unwrap()`, `expect()`, `#![feature]`, dependency, and `unsafe` lines.

### Tests catch semantic regressions after a clean build

RustAssistant runs tests after a repair. Its float-shift example shows why this step is necessary. The generated patch was type-correct but computed the wrong value.

For 134 fixed real commits, the paper classified 55 as semantically unambiguous. Of the remaining commits, 41 matched the developer patch, 29 differed but had the same runtime behavior under review, and 9 had different runtime behavior. These categories depend on human judgment.

CRUST-Bench also separates build and test results. Its best stated test-repair result was 48 passing projects, although several configurations built more than 60 projects. A build gate alone would overstate success.

### A passing test must call the changed code (addendum)

XRepoTest found that 28.3% of the passing Rust test suites did not call the focal function. The authors inspected these suites manually. The suites called mocks, stubs, or unrelated public APIs. In Rust-SWE-bench, 35.5% of the failed issue reproductions used tests that did not exercise the reported behavior.

The XRepoTest mutation data does not show that passing Rust tests are weak. Its mutation score (MS, at most 4.14% for Rust) counts every sample whose tests fail as 0, so it mostly measures failing tests. On passing samples only (MS@Pass), the mean Rust mutation score was 50.69% to 87.70% for 13 of the 14 models; the table gives 0.00 for the fourteenth.

Confirm that each new test calls the changed function. Confirm that it fails before the change and passes after it. Use mutation testing for critical changes. A pass rate alone overstates test quality.

### Issue reproduction limits native repository repair (addendum)

In Rust-SWE-bench, the best baseline configuration reproduced 55.5% of the issues. When the authors disabled reproduction, its resolution rate fell by 42%. Of the failed reproductions, 52.5% came from dependency or workspace configuration, for example a wrong `Cargo.toml` or workspace path. The authors' RustForger agent builds a separate test workspace that imports the target crate as a path dependency. With the same model, it reproduced 67.3% of the issues.

Reproduce a bug with a failing test before you change the code. If the test does not build, fix the test workspace before you change the product code.

### Compare with a reference implementation when one exists (addendum)

In the cJSON port study, all five LLM ports had zero `unsafe` blocks, eliminated the in-scope CVEs, and had no memory-safety crashes under fuzzing. Miri found no undefined behavior in the ports whose test suites were large enough to check. Differential fuzzing against the C library still found a divergence within seconds in four of the five ports. In five repeated runs of one model, two ports panicked on multi-byte input. One port was O(n²) because it validated the remaining input as UTF-8 for each character.

When a change ports or rewrites code that has a reference implementation, run differential tests against the reference. Include non-ASCII, invalid UTF-8, and boundary input. Compare the performance with the reference. Treat this conclusion as strong for this single-library study and unproven for large or concurrent code.

### Overflow behavior depends on the build profile (addendum)

In the ISSRE 2026 study of LLM-generated contest solutions, numeric overflow caused 44.0% of the classified Rust runtime errors in the baseline setting. The authors attribute this share to overflow checks in debug builds. The study does not state its build profile.

Repository-level inference: Cargo's default `dev` profile enables `overflow-checks`, and the default `release` profile disables them ([Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html#overflow-checks)). The same generated code can panic under `cargo test` and wrap silently in a default release build. Run behavior tests in a profile with overflow checks. Enable `overflow-checks` in the release profile of code that handles untrusted input.

### Error counts can hide one root cause

RustRepoTrans found up to 193 compiler diagnostics in one failed sample. The median was 3. Rust compiler diagnostics can cascade from one missing type, method, or import.

Group related diagnostics before repair. Re-run the compiler after the smallest coherent patch. Do not treat each emitted diagnostic as an independent defect.

### Safety instructions change the observed taxonomy

CRUST-Bench finds little unsafe code, but its prompt explicitly forbids unsafe Rust. This result does not show that models avoid unsafe code in normal generation.

The RustAssistant microbenchmark also excludes unsafe Rust and FFI. Current evidence cannot establish a general LLM error rate for soundness boundaries.

Addendum: a prompt rule is not enforcement. In the C-to-Rust Fallacy study, the FLOURINE prompt required safe Rust and no raw pointers. The study shows output that uses an `unsafe` block and raw pointers, and it counts six bugs from conflicting prompt constraints. FLOURINE checks the rule only after generation, with a text search. Enforce such a rule with a compiler or lint gate, for example `#![forbid(unsafe_code)]`. The cJSON study also required zero `unsafe` in its prompt. Its zero-`unsafe` result therefore does not show what a model does without that rule.

### Security needs domain checks

The cryptographic study shows that compile success and general static analysis are not sufficient for its AEAD tasks. The compiler cannot prove nonce uniqueness or key provenance. The paper's CodeQL queries also did not give useful positive findings for this narrow setup.

Use domain-specific assertions and review for security invariants. Treat this conclusion as strong for the studied AEAD patterns and unproven for other security domains.

Addendum: in the C-to-Rust Fallacy study, four refactoring tools kept 177 original memory-safety bugs in 413 compiling programs. A clean compile and a low `unsafe` count do not show that a port removed the original defect. Run the original bug trigger against the port. Use ASan or Miri where they apply. The study states that Miri cannot execute across an FFI boundary. By default, Miri does not execute foreign code. Its `-Zmiri-native-lib` flag is experimental and Unix-only: it calls native functions, but Miri does not check what the native code does ([Miri README](https://github.com/rust-lang/miri/blob/master/README.md)).

### A panic at an FFI boundary is version-sensitive (addendum)

The C-to-Rust Fallacy study classifies 46 panics in `pub unsafe extern "C" fn` functions as undefined behavior. The paper does not state its Rust toolchain. The Reference gives these cases for non-unwinding ABIs:

- A Rust panic that reaches a non-unwinding ABI boundary, such as `extern "C"`, aborts the process under `panic=unwind`. Rust 1.81.0 (2024-09-05) introduced this abort. Before 1.81.0, the same unwind was undefined behavior.
- A foreign unwind, such as a C++ exception, that enters Rust through a non-unwinding ABI is undefined behavior.

On Rust 1.81.0 and later, the 46 cases are process aborts. An abort is a denial of service, not undefined behavior. Do not copy the paper's label without this condition. Most of the 46 cases come from the two static tools (44), not from the LLM-based tools (2). Sources: [Reference: ABI unwinding behavior](https://doc.rust-lang.org/reference/items/functions.html#unwinding), [Reference: unwinding across FFI boundaries](https://doc.rust-lang.org/reference/panic.html#unwinding-across-ffi-boundaries), and [RELEASES.md, Rust 1.81.0](https://github.com/rust-lang/rust/blob/master/RELEASES.md#version-1810-2024-09-05).

## Concrete failure examples

These examples are paraphrases of source cases. They do not copy source code.

1. A repair sees an invalid bit shift on a floating-point value. It changes the operation to multiplication by 2.0. The program compiles, but a shift count of two requires a factor of 4 for the intended test behavior.
2. A repository translation uses one local value through both immutable and mutable references without a valid ownership plan. The compiler reports a borrow or mutability conflict.
3. A translation assumes that a source-language helper has a direct Rust equivalent. It calls a nonexistent method and produces E0599.
4. A generated implementation changes a callee signature. It does not update all callers. The first local error disappears, but call-site errors remain.
5. A model returns a partial file with a comment that says the remaining functions are similar. The output does not implement the required interface.
6. A cryptographic sample compiles and encrypts data. It reuses a nonce or embeds a key. The compiler does not reject this semantic security defect.
7. Addendum. A repair agent meets an invalid dereference of an `Option` wrapper. It inserts `unwrap()`. The program compiles, and the null case now panics.
8. Addendum. A generated unit test calls a mock or an unrelated public API instead of the focal function. The test passes, but it does not test the target.
9. Addendum. An agentic port of a C parser has no `unsafe` and passes its own tests. A differential fuzzer finds input on which the port and the C library give different results. Another run of the same model panics on multi-byte input.
10. Addendum. A contest solution raises a loop variable to a power that the input controls. The result overflows the integer type, and the checked build panics.

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

Addendum limitations:

- Most addendum sources do not state their Rust toolchain: Rust-SWE-bench, the ISSRE 2026 study, XRepoTest, and the C-to-Rust Fallacy study. Only the cJSON study states it (Rust 1.93.1).
- A study can state a version-dependent Rust rule without its toolchain. The C-to-Rust Fallacy study calls a panic across an FFI boundary undefined behavior. That is true only before Rust 1.81.0 for a Rust panic. Check the Reference before you copy such a claim.
- Benchmark test oracles can be wrong. CRUST-Bench issue [#42](https://github.com/anirudhkhatry/CRUST-bench/issues/42) (opened 2026-05-01) and issue [#43](https://github.com/anirudhkhatry/CRUST-bench/issues/43) (opened 2026-09-12) report Rust tests that do not match the C tests, and both are open at the addendum cut-off. For #43, the published dataset confirms the difference: the C test checks a one-sided tolerance, and the Rust test checks a two-sided `.abs()` tolerance. The CRUST-Bench numbers in this map are the paper's numbers. When a plausibly correct change fails a benchmark test, check the test against the specification before you change the code.
- Two crate-name measurements are indirect. The crate hallucination study parses path prefixes and does not compile, so valid code can count as a hallucination. This applies to all of its pattern findings, not only to the 22.23% rate: the 45.47% module share, the 32.96% missing-hyphen share, and the 38.9% cross-domain share. Its hyphen and cross-domain examples look like lowercased type names or modules, and a source parser cannot see a missing hyphen because Rust source spells a hyphenated crate name with underscores (repository inference). XRepoTest does not say if a real crate that is absent from `[dev-dependencies]` counts as a "Phantom Library".
- The addendum rates come from narrow task populations: contest problems, test generation for eight Rust repositories, small synthetic Juliet programs, and one C library. Do not transfer them to general Rust development.
- Vendor system cards in the addendum window report only aggregate multilingual scores. Do not use such a score as a Rust rate.
- The addendum search read arXiv titles, abstracts, and comments, not full text. It did not search ACM DL or IEEE Xplore full text. A multilingual agent study with an unnamed Rust subset can be missing.
- Differences between the two addendum searches that the primary sources resolved: the C-to-Rust Fallacy prose and Table 3 disagree on the per-tool mitigation counts, and this map uses the table. One search read only the abstract of the cJSON study; this map uses the full text. For the package-hallucination study in the source inventory, the prose says that retrieval raised the Rust rate for no model, but its Table 4 shows a rise for one model; this map does not use its numbers. One search could not explain why the cJSON study reports 13 of 13 CVEs for some ports and 11 of 11 for others. The full text explains it: 11 core CVEs apply to all ports, and 2 more apply only to the three ports that implement `cJSON_Minify`. The two searches disagreed on whether SWE-Bench ProMax gives a Rust breakdown. Its Sec. 5.1 does: it gives per-language resolve rates, including Rust.
- Open items: the ISSRE 2026 text and tables disagree on some counts, and this map uses the tables. The C-to-Rust Fallacy study does not name the models that FLOURINE and C2SaferRust use, so its LLM-tool results have no model attribution.

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
| `C-unwind` is not a cross-language exception adapter. | A foreign unwind that enters Rust through a non-unwind ABI is undefined. A Rust panic that reaches a non-unwind ABI boundary, such as `extern "C"`, aborts the process under `panic=unwind` since Rust 1.81.0; before 1.81.0 it was undefined. A Rust `extern "C-unwind"` function that unwinds into code that does not support unwinding, such as C or C++ built with `-fno-exceptions`, is also undefined. Catching a foreign exception with `catch_unwind` has unspecified behavior. | [Reference: FFI unwinding](https://doc.rust-lang.org/reference/panic.html#unwinding-across-ffi-boundaries), [Reference: ABI unwinding behavior](https://doc.rust-lang.org/reference/items/functions.html#unwinding) | `rust-panic-safety` already covers the boundary and states the Rust 1.81 abort rule. Preserve the exact limitation. |
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

### Addendum: owners for the new classes

The addendum evidence does not show a new domain. Each new class maps to an existing skill, so the catalog adds no new skill. The table states the intended coverage of each owner.

| New class | Evidence | Owner | Intended coverage |
|---|---|---|---|
| Passing test does not exercise the target | XRepoTest invocation rate; Rust-SWE-bench reproduction failures | `rust-tdd` | A new test must call the changed function. It must fail first, for the predicted reason, and pass after the change. Use mutation testing for a critical change; this is a recommendation, not a measured XRepoTest result. |
| Ports that differ from their reference | cJSON port study | `rust-test-tools` | Differential testing against a reference implementation for a port or a rewrite, with non-ASCII, invalid UTF-8, and boundary input. Secondary owner for mutation testing: the `cargo-mutants` workflow. |
| Repair moves the defect to run time or to the toolchain; unresolved or invented names | C-to-Rust Fallacy; Rust-SWE-bench; XRepoTest; crate hallucination study (indirect, parser-based) | `rust-compiler-errors` | Do not repair a compile error with `unwrap()`, a nightly `#![feature]`, a new crate, or `unsafe`. For E0432 and E0433, first check for a missing `use std::...` path. Confirm the exact crate name on crates.io before `cargo add`. |
| Safety rule stated only in the prompt | C-to-Rust Fallacy; cJSON port study | `rust-unsafe` | A prompt rule is not enforcement. Enforce the rule with `#![forbid(unsafe_code)]` or a lint gate. |
| Panic at a C ABI boundary | C-to-Rust Fallacy, with the version note | `rust-panic-safety` | A panic must not unwind out of a function that foreign code calls. The policy states the Rust 1.81 abort and the earlier undefined behavior. |
| Runtime overflow panic | ISSRE 2026 contest study | `rust-panic-safety` | The release-profile example already sets `overflow-checks = true`. Keep the study as regression evidence. |

The compile-check harness does not validate these rules. They are workflow and review rules. A `rust,run` or `compile_fail` block cannot prove that a test calls its target or that a repair diff adds no `unwrap()`. A reviewer must confirm that each owner states its rule.

Routing note: Rust-SWE-bench ranks E0432 third (12.08%) and E0412 seventh (5.69%) among agent compile errors. Both codes belong to the resolution group that `rust-compiler-errors` owns.

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

Addendum rules 9 to 12 state the intended coverage of the owners in the addendum table.

9. Confirm that each new test calls the changed function and fails before the change.
10. Do not remove a compile error with `unwrap()`, a nightly `#![feature]`, a new crate, or `unsafe`.
11. Enforce a safety rule with `#![forbid(unsafe_code)]` or a lint gate, not with a prompt.
12. Run differential tests against a reference implementation when one exists.

These rules follow the empirical pattern: compiler feedback fixes many local errors, but incomplete output, error cascades, semantic regressions, API drift, and domain defects remain. The addendum adds tests that miss their target, repairs that move a defect to run time, and ports that are memory-safe but not equivalent.

## Source inventory

- Deligiannis et al. [Fixing Rust Compilation Errors using LLMs](https://arxiv.org/abs/2308.05177). See also the [Microsoft Research publication page](https://www.microsoft.com/en-us/research/publication/fixing-rust-compilation-errors-using-llms/) and [paper PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/08/paper.pdf).
- Khatry et al. [CRUST-Bench: A Comprehensive Benchmark for C-to-safe-Rust Transpilation](https://arxiv.org/abs/2504.15254). See also the [official dataset repository](https://github.com/anirudhkhatry/CRUST-bench) and [leaderboard](https://crust-bench.github.io/).
- Liu et al. [RustRepoTrans paper](https://mingwei-liu.github.io/assets/pdf/ase2025rustrepotrans.pdf). See also the [official benchmark repository](https://github.com/SYSUSELab/RustRepoTrans).
- [Type-migrating C-to-Rust translation using a large language model](https://link.springer.com/article/10.1007/s10664-024-10573-2), Empirical Software Engineering.
- [An Empirical Security Evaluation of LLM-Generated Cryptographic Rust Code](https://arxiv.org/abs/2604.27001).
- [RustEvo official benchmark repository](https://github.com/SYSUSELab/RustEvo).
- [Multi-SWE-bench official project](https://multi-swe-bench.github.io/), [repository](https://github.com/multi-swe-bench/multi-swe-bench), and [paper](https://arxiv.org/abs/2504.02605).
- [MultiPL-E official repository](https://github.com/nuprl/MultiPL-E). This benchmark supplies compiler-and-test infrastructure for translated HumanEval and MBPP tasks, including Rust. This first pass does not use it for a Rust error rate because its public summary does not give the required Rust-specific taxonomy.

### Addendum sources

- Pre-cut-off. Xiang et al. [Evaluating and Improving Automated Repository-Level Rust Issue Resolution with LLM-based Agents](https://arxiv.org/abs/2602.22764), arXiv 2602.22764, 2026-02-26, ICSE 2026. See also the [Rust-SWE-bench repository](https://github.com/GhabiX/Rust-SWE-Bench).
- Pre-cut-off. Nogueira et al. [Unreliable in Practice? A Comprehensive Study of Errors in LLM-Generated Code](https://arxiv.org/abs/2608.00661), arXiv 2608.00661, 2026-08-01, ISSRE 2026.
- Pre-cut-off. Zheng et al. [When LLMs Invent Rust Crates: An Empirical Study of Hallucination Patterns and Mitigation](https://arxiv.org/abs/2606.08444), arXiv 2606.08444, v1 2026-06-07 and v2 2026-08-14, Internetware 2026.
- Le Quang et al. [XRepoTest: Benchmarking Multilingual Repository-Level Unit Test Generation for Large Language Models](https://arxiv.org/abs/2608.25939), arXiv 2608.25939, v1 2026-08-26 and v2 2026-09-15, accepted to EMNLP 2026. See also the [artifact repository](https://github.com/solis-team/XRepoTest).
- Chen et al. [C-to-Rust Fallacy: Automatic Refactoring ≠ Memory Security](https://arxiv.org/abs/2609.25682), arXiv 2609.25682, 2026-09-22.
- Parrillo et al. [LLM-Assisted Porting of Security-Critical C Libraries to Idiomatic Rust: A Multi-Model Empirical Study](https://doi.org/10.3390/fi18090471), Future Internet 18(9):471, doi:10.3390/fi18090471, 2026-09-07.
- CRUST-Bench issues [#42](https://github.com/anirudhkhatry/CRUST-bench/issues/42) and [#43](https://github.com/anirudhkhatry/CRUST-bench/issues/43).
- [Reference: ABI unwinding behavior](https://doc.rust-lang.org/reference/items/functions.html#unwinding), [Reference: unwinding across FFI boundaries](https://doc.rust-lang.org/reference/panic.html#unwinding-across-ffi-boundaries), [RELEASES.md, Rust 1.81.0](https://github.com/rust-lang/rust/blob/master/RELEASES.md#version-1810-2024-09-05), and [Cargo profiles: overflow-checks](https://doc.rust-lang.org/cargo/reference/profiles.html#overflow-checks).

Read in full and not added, because they confirm existing findings or give no Rust failure measurement:

- [Translator vs. Challenger: Adversarial Agentic Learning for C-to-Rust Translation](https://arxiv.org/abs/2609.15381) (TRAIL), arXiv 2609.15381, 2026-09-14. It confirms the CRUST-Bench gap between `cargo check` and `cargo test` with three 2026 models.
- [TRACTOR Benchmark for Evaluating C to Rust Translators](https://arxiv.org/abs/2609.25121), arXiv 2609.25121, 2026-09-20. It describes a benchmark and publishes no translator scores.
- [Evaluating Inference-Time Defenses Against Package Hallucination in LLM-Generated Code](https://arxiv.org/abs/2608.22652), arXiv 2608.22652, 2026-08-23, ASE 2026. It uses eight open models of 1B to 8B parameters on synthetic package-recommendation prompts, and its results may not transfer to frontier agents (repository inference).
- [Software Aging in LLM-Generated Applications](https://arxiv.org/abs/2608.26391), arXiv 2608.26391, 2026-08-26. It studies four Rust services, and its generator, framework, and language are confounded.
- Pre-cut-off. [Generative Compilation: On-the-Fly Compiler Feedback as AI Generates Code](https://arxiv.org/abs/2607.13921), arXiv 2607.13921, 2026-07-15. It supports the existing rule to group cascading diagnostics.
- [Shortcutting the Fix](https://arxiv.org/abs/2609.06780), arXiv 2609.06780, 2026-09-06. It audits SWE-bench Multilingual, which contains Rust tasks, but it gives no per-language result.

Not yet read in full (abstract level only):

- Pre-cut-off. [RustEvo²](https://arxiv.org/abs/2503.16922), arXiv 2503.16922, 2025-03-21, the paper behind the RustEvo repository.
- Pre-cut-off. [The Best Programming Language for Tokenmaxxing](https://arxiv.org/abs/2607.22807), arXiv 2607.22807, 2026-07-24.
- Pre-cut-off. [PROBE](https://arxiv.org/abs/2607.13820), arXiv 2607.13820, 2026-07-15, the dataset behind the ISSRE 2026 study.
- Pre-cut-off. [SWE-Bench ProMax](https://arxiv.org/abs/2608.09802), arXiv 2608.09802, 2026-08-10, COLM 2026. Its Sec. 5.1 gives per-language resolve rates, including Rust, on 170 refactoring instances. It gives no Rust error taxonomy.
- Pre-cut-off. [RustMizan](https://arxiv.org/abs/2607.04729), arXiv 2607.04729, 2026-07-06, a Rust vulnerability-detection benchmark for agents.
