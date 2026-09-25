# WebAssembly size and optimizer control

Use this file when you set or defend a size budget, change the release profile,
or change how `wasm-opt` runs.

## Measure the shipped file

Measure the packaged file that consumers load, not the file in `target/`:

```bash
wc -c pkg/*_bg.wasm
gzip -9 -c pkg/*_bg.wasm | wc -c
twiggy top pkg/*_bg.wasm
wasm-tools objdump pkg/*_bg.wasm
```

The `twiggy` repository is archived. If it cannot parse the module, read the
section sizes from `wasm-tools objdump`.

Set a size budget on the packaged file. Report the absolute size and the change
from the baseline. Do not count generated JavaScript, TypeScript, or other
shipped assets as zero.

## Start from a measured release profile

```toml
[profile.release]
opt-level = "s"
lto = true
codegen-units = 1
strip = "symbols"
```

The WebAssembly targets already abort on panic, so the profile needs no `panic`
key. The release profile applies to every target in the workspace, so a native
release build gets the same settings.

Compare `opt-level = "s"`, `"z"`, and `3` on the final artifact. Smaller
codegen is not always a smaller compressed file or a faster application. `"s"`
and `"z"` also disable loop vectorization, which matters for SIMD-heavy code.

## Pin `wasm-opt`

`wasm-pack` runs any `wasm-opt` on `PATH` without a version check. If there is
none, it downloads the binaryen release that its own version pins
(`version_117` in wasm-pack 0.13.1 to 0.15.0). The wasm-pack log line
`found wasm-opt at ...` shows when the `PATH` binary ran. Optimizer output and
supported proposals change between binaryen releases, and a wasm-pack upgrade
can change the bundled one. Pin the wasm-pack version, and pin `wasm-opt` in
one of two ways:

- Put a pinned `wasm-opt` on `PATH` in CI.
- Set `wasm-opt = false` under `[package.metadata.wasm-pack.profile.release]`
  and run a pinned binary as a separate step.

Rust 1.87+ output uses bulk-memory and non-trapping float-to-int instructions
by default. If `wasm-opt` rejects them, enable them explicitly:

```toml
[package.metadata.wasm-pack.profile.release]
wasm-opt = ["-Os", "--enable-bulk-memory", "--enable-nontrapping-float-to-int"]
```

This list replaces the default arguments, so keep an `-O` level in it. The flags
are a workaround from an open `wasm-pack` issue; check them against the pinned
binaryen version.

After any optimizer change, run the full runtime test suite and the
engine-baseline validation from `SKILL.md` on the optimized file.
