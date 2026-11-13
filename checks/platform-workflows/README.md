# Rust 1.100 platform workflow checks

These are test inputs, not product crates. Run commands from the repository root.
A missing tool or different version fails; it does not produce a passing skip.

## WASIp3 runtime smoke

```bash
rustup target add --toolchain 1.100.0 wasm32-wasip3
python3 checks/platform-workflows/fetch_tools.py --output /tmp/rust-platform-tools
python3 checks/platform-workflows/wasip3_smoke.py --tools /tmp/rust-platform-tools --output /tmp/rust-wasip3-evidence
```

The installer checks official release-asset SHA-256 values before copying the
executables. Pins cover Wasmtime 50.0.1 and wasm-tools 1.263.0 on Linux x86_64,
Linux aarch64, and macOS arm64. It writes only to the supplied output directory.

The guest waits for a WASI 0.3 async clock and reads a file. The check verifies
async WIT interfaces, success with one directory capability, failure after the
clock wait without that capability, and missing-interface rejection with WASIp3
disabled. It does not test network or thread support.

## Sample PGO capture and measurement

On Apple Silicon macOS with Xcode `atos` and samply 0.13.1:

```bash
rustup component add llvm-tools --toolchain 1.100.0
python3 checks/platform-workflows/sample_pgo.py --output /tmp/rust-sample-pgo-new-run
```

Use a new output directory. The script captures real leaf-PC samples at 1000 Hz,
resolves the fixture's noinline symbol with its matching dSYM, converts observed
counts to LLVM text, and uses rustc's LLVM tools to encode the profile. It checks
profile metadata on `sampled_hot` in emitted IR before timing nine alternating
pairs. Both binaries must produce the same output. Timing and binary sizes are
measurements, not a throughput gate. Keep raw captures out of git: they carry
absolute paths and binary identifiers.

The converter supports this one fixture, not arbitrary optimized Rust. It does
not reconstruct inline contexts, discriminator data, or unobserved call counts.

## Deterministic profile replay

```bash
python3 checks/platform-workflows/test_sample_pgo.py
python3 checks/platform-workflows/sample_pgo.py --replay --output /tmp/rust-pgo-replay-new-run
```

Replay checks source and profile hashes, converts recorded real samples, requires
an attached profile on the hot function, and compares program output. It does not
sample or assert a speedup. Replay on another target proves format consumption
and output only, not a production optimization benefit on that architecture.

`sample_capture.txt` contains only the sampled function and line counts.
`sample_capture.json` records public tool versions, source/profile hashes, sample
totals, all timings, and binary sizes. The measurement and its limits are recorded
in `../../research/rust-1.100-platform-workflows-2026-11.md`.
