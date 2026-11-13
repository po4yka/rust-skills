# Catalog audit fixes — 2026-11-13

Baseline: main commit `5d0b037399da9b2bb4f88f1e575cf93250e97c55`.
The audit covered 51 skills and 231 reference files, plus validation, workflows,
and release instructions. This change addresses each of its 22 findings.

The repository fixes for 03 and 19 correct the published instructions. Their live
GitHub configuration remains pending separate approval. No settings write, tag,
release, or merge is part of this change.

## Finding map

| ID | Finding | Change and evidence |
| --- | --- | --- |
| 01 | Swift input borrow can escape its contract | `rust-buffer-exports.md` uses a scoped higher-ranked callback; owned output run probe and rejected escaping-reference check |
| 02 | SendZc result is confused with buffer release | `manual-poll-bridge.md` distinguishes `F_MORE` and `F_NOTIF`, including cancellation; official liburing contract |
| 03 | Required GitHub protections are absent | README, AGENTS, and release docs state the observed settings; [approval proposal](../docs/github-settings-approval.md) remains pending |
| 04 | Temporary output paths collide | `platform-bridges.md` uses exclusive sibling files and writes through the open handle; cancellation, collision, commit, and commit-error probes |
| 05 | Safe RawFd helper assumes an unsafe contract | `adopt_copy` takes `BorrowedFd`; raw boundaries keep explicit lifetime obligations |
| 06 | Generic Drop promises no panic or blocking | Both cleanup references use explicit close; run probes check flush counts through success, errors, panic, and unwind; concrete destructor limits remain explicit |
| 07 | try_join is described as waiting for all | Routing separates all-results and fail-fast behavior; spawned JoinHandle detachment is explained |
| 08 | Reused tombstones accept stale indices | Require quiescence or a generation check; run probe rejects stale and out-of-range keys |
| 09 | Reading another union field is called UB | Require validity of the read type; portable numeric representation probe |
| 10 | Vec drop order is claimed as guaranteed | State unspecified order; probe explicitly consumes elements in order |
| 11 | Owning builders are called unsuitable for loops | Show reassignment in a working loop probe |
| 12 | Lifetime splitting is claimed to fix ownership | Working borrowed and owned cache probes; E0597 probe for a source that expires too soon |
| 13 | non_exhaustive scope is missing | State the defining-crate boundary; exhaustive local-match probe |
| 14 | jni 0.21 JavaVM is called Clone | Use `Arc<JavaVM>` for 0.21; alias the exact older API in the compile harness |
| 15 | XCFramework modulemaps collide | Put each module in its own headers subdirectory; real two-library consumer build |
| 16 | cfg(test) target coverage is unchecked | Check each Cargo stream independently; regression tests reject missing targets in either pass |
| 17 | Outcome workflow passes with no result | Fail missing, malformed, or empty measurements; real zero scores remain valid; tests run the workflow's summary program |
| 18 | macOS cross fallback is incomplete | Remove clang-only setup; document and supply a Linux container with C/C++ cross tools and PyO3 configuration |
| 19 | Private reporting is promised but disabled | SECURITY states the current gap and provides a details-free channel request; enabling reporting remains in the separate approval proposal |
| 20 | String conversion to boxed Error is denied | Separate the anyhow rule; run probe covers both standard-library boxed error forms |
| 21 | Empty license passes validation | Require exact BSD-3-Clause value; empty and wrong-value regression cases |
| 22 | Catalog and bundle counts are stale | README says 51 skills; remove the duplicated bundle count from release docs |

## Validation

- New analyzer coverage tests fail against the original analyzer and pass after
  the fix. The complete expected-error case still passes.
- The new license regression test fails against the original validator and passes
  after the fix.
- Summary tests execute the actual workflow code with missing, malformed, empty,
  and valid low-score result files. They require no model API call.
- Independent Rust 1.100.0 probes check the changed language, cleanup, and FFI
  examples. The JNI 0.21 example passes an isolated locked offline Cargo check.
- Two library XCFrameworks with module-specific header directories build in a
  real consumer with Xcode 27 on macOS ARM64. The original root modulemap layout
  failed with duplicate build outputs.
- Independent forward tests built a Rust static library and Swift 6.4.2 consumer.
  Owned parsed results survived release of Rust and Swift inputs. Empty and error
  paths passed. A two-thread file test preserved old outputs on cancellation,
  renderer failure, unwind, and rename failure. Both tests passed on macOS ARM64.

The complete `bash checks/check.sh` run passed in the image built from
`checks/Dockerfile`, on Linux ARM64 with x86_64 Linux example type checks:

- 51 skills passed catalog validation; the routing evaluation lint reported no problems.
- All unit-test groups passed, including the new analyzer, license, and summary cases.
- Both compile passes completed: 377 of 379 compile blocks built cleanly, with the
  same two listed fragments; all 97 run blocks compiled, and all 80 compile-fail
  blocks failed as tagged. The 21 existing ignored blocks remain listed.
- All 97 behavior probes, lint templates, compiler/Cargo/loom regressions, WASIp3
  capability checks, recorded sample-PGO replay, and nine outcome fixtures passed.
- The skills CLI found all 51 skills. Both supported agent clients installed all
  eight plugins with their exact skill inventories. Bundle routing phrases remained visible.
- `checks/baseline.txt` remains empty. No ignore or fragment allowance was added.

The first native macOS fast run stopped at a missing binary in the existing npm
client cache. The complete container run used clean client state and passed.
The container setup is the verified full-suite path for this macOS workspace.

## Limits and sources

The live SendZc kernel scenario, mobile devices, Windows runtime, and a new model
evaluation were not run. Compile checks do not establish foreign-pointer validity
or kernel completion behavior. The relevant contracts are linked in the changed
references and in the sources below.

- [Zero-copy send completion](https://github.com/axboe/liburing/blob/master/man/io_uring_prep_send_zc.3)
- [Raw slice safety](https://doc.rust-lang.org/1.100.0/std/slice/fn.from_raw_parts.html)
- [BorrowedFd safety](https://doc.rust-lang.org/1.100.0/std/os/fd/struct.BorrowedFd.html#method.borrow_raw)
- [Vec guarantees](https://doc.rust-lang.org/1.100.0/std/vec/struct.Vec.html#guarantees)
- [Union field reads](https://doc.rust-lang.org/reference/items/unions.html#reading-and-writing-union-fields)
- [non_exhaustive scope](https://doc.rust-lang.org/1.100.0/reference/attributes/type_system.html#the-non_exhaustive-attribute)
- [jni 0.21.1 JavaVM](https://docs.rs/jni/0.21.1/jni/struct.JavaVM.html)
