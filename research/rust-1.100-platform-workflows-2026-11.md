# Rust 1.100 sample PGO and WASIp3 workflows

Date: 2026-11-13. Rust 1.100.0 (`0ef1bc386`, LLVM 23.1.5).
The fixtures live in `checks/platform-workflows/`. They are test inputs only.

## Sample PGO: real capture, consumption, and measurement

Host: aarch64 macOS 27.2.1. Sampler: samply 0.13.1 at 1000 Hz.
Converter: `sample_pgo.py`, restricted to the fixture's noinline unmangled
`sampled_hot` function. Symbolization uses Xcode `atos` and the training binary's
dSYM. LLVM conversion uses rustup's `llvm-profdata` 23.1.5 from Rust 1.100.0.

Observed command:

```bash
python3 checks/platform-workflows/sample_pgo.py --output /tmp/rust-platform-final-pgo
```

The run captured 8,134 weighted leaf samples. Of these, 8,128 resolve to the hot
function. No sample was observed at its entry, so the text profile records zero
entry samples. Body counts are 5,218 at line offset 1, 2,905 at offset 3, and 5
at offset 8. The converter does not invent a call count.

`llvm-profdata merge --sample --extbinary` accepted the profile. Its `show --sample`
output names `sampled_hot` with 8,128 body samples. The profile-use build emits
no warning. The hot function in its LLVM IR has `!prof` metadata referencing
`function_entry_count`. Both binaries print `2378606452826756027` for 30,000
iterations.

Each binary has one unmeasured warmup. Nine measured pairs alternate their order.
Both use opt-level 3, debuginfo 2, and frame pointers. Sampling is outside the
measured runs. The files retain equal debug settings, with separate dSYM.

| Measurement | Baseline | Sample PGO |
| --- | ---: | ---: |
| Median wall time | 2.055540 s | 2.114412 s |
| Minimum wall time | 1.658963 s | 1.281662 s |
| Maximum wall time | 2.887884 s | 2.830601 s |
| Executable bytes | 491,896 | 491,848 |

The median ratio is 1.02864. This is **not evidence of a speedup or a confirmed
regression**: other work ran on the shared host, and the observed spread is much
larger than the median difference. The useful result is that real samples were
captured, converted, consumed, and measured against a baseline with equal output.
No production-performance claim follows from this synthetic CPU workload.

The repository stores the small real text profile and sanitized measurement JSON.
They contain no private source path or host identifier. Source and profile hashes
bind replay to this fixture. Raw samply files and dSYM remain outside the tree.
`sample_pgo.py --replay` passed on the native host. It proves profile consumption
and correct output, not a performance result on the replay host.

## WASIp3: actual async host calls and denied capability

Pinned tools: Wasmtime 50.0.1 (`c307ec81d`, 2026-10-29), wasm-tools 1.263.0
(`7a2fa422c`, 2026-10-30). The installer verifies official release-asset SHA-256
values for each supported host before installing to a caller-owned directory.

Observed commands:

```bash
python3 checks/platform-workflows/fetch_tools.py --output /tmp/rust-platform-final-tools
python3 -O checks/platform-workflows/wasip3_smoke.py --tools /tmp/rust-platform-final-tools --output /tmp/rust-platform-final-wasi
```

The pure-std guest builds with `rustc +1.100.0 --target wasm32-wasip3`. Its WIT
exports async `wasi:cli/run@0.3.0` and imports WASI 0.3 async clock waits and
filesystem interfaces. `std::thread::sleep(25 ms)` uses the async host clock;
it does not create an OS thread. The fixture checks elapsed time before reading
`/fixture/input.txt`.

- With only the fixture directory mapped to `/fixture`, the timer and file read
  pass and print their two completion lines.
- Without `--dir`, the timer still completes. The file read exits nonzero with
  `NotFound` (WASI error code 44). This establishes that the guest reached the
  capability boundary, rather than failing during startup.
- With `-S p3=n`, Wasmtime rejects the missing `wasi:cli/environment@0.3.0`
  linker implementation. The check matches that diagnostic, not any failure.

Acceptance checks use explicit exceptions, so Python `-O` does not disable them.
The seven unit tests for capture/source consistency, empty or inconsistent
profiles, and fail-closed acceptance also pass under Python `-O`.
This is runtime acceptance for one clock and file operation on the pinned host.
It does not establish cancellation, streaming HTTP, cooperative threads, another
runtime's support, or production support for all WASIp3 interfaces.

## Primary sources

- [Rust sample-profile codegen option](https://doc.rust-lang.org/1.100.0/rustc/codegen-options/index.html#profile-sample-use)
- [LLVM sample-profile text format](https://clang.llvm.org/docs/UsersManual.html#sample-profile-text-format)
- [llvm-profgen](https://llvm.org/docs/CommandGuide/llvm-profgen.html)
- [Rust WASIp3 requirements](https://doc.rust-lang.org/1.100.0/rustc/platform-support/wasm32-wasip3.html#requirements)
- [Wasmtime CLI](https://docs.wasmtime.dev/cli-options.html)
- [Wasmtime 50.0.1 assets](https://github.com/bytecodealliance/wasmtime/releases/tag/v50.0.1)
- [wasm-tools 1.263.0 assets](https://github.com/bytecodealliance/wasm-tools/releases/tag/v1.263.0)
