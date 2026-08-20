---
name: rust-wasm
description: Use when a Rust project targets WebAssembly for a browser, Node.js, a WASI runtime, or a Component Model host, or when it must diagnose a JavaScript boundary, runtime capability, target feature, test, or size failure. Triggers on "wasm32-unknown-unknown", "wasm32-wasip1", "wasm32-wasip2", "wasm-bindgen", "WebAssembly Component Model", or "wasm binary size".
license: BSD-3-Clause
---

# Rust WebAssembly

Build and verify Rust for the exact WebAssembly host that runs it. A `.wasm`
suffix does not define an ABI, an import set, or a runtime.

Keep these boundaries:

- Use `cargo-workflows` for workspace policy, feature unification, profiles, and
  general cross-compilation.
- Use `rust-async-internals` for executor-independent cancellation and future
  design. Use this skill for the host event loop and WebAssembly limitations.
- Use `rust-performance` after a measurement names a CPU or allocation hotspot.
  Use this skill for WebAssembly artifact size and boundary costs.
- Use `rust-native-linking` when WASI code links C or C++ through `wasi-sdk`.

## Write the host contract first

Record these facts before you edit `Cargo.toml` or Rust code:

1. Name the Rust target triple.
2. Name the host and its minimum version.
3. Name the artifact format: core module or component.
4. List allowed imports and capabilities.
5. Name the JavaScript output mode when JavaScript glue exists.
6. List required WebAssembly proposals, such as SIMD, bulk memory, or threads.

Do not infer the host from `target_arch = "wasm32"`. Browser, Node.js, WASIp1,
and WASIp2 builds can share that architecture and still have incompatible APIs.

## Select the target

| Host contract | Rust target | Output | Important constraint |
|---|---|---|---|
| Browser or JavaScript host with explicit imports | `wasm32-unknown-unknown` | Core module, often with generated JS | `std::fs` fails, `println!` does nothing, and `std::thread::spawn` panics |
| Existing WASI Preview 1 host | `wasm32-wasip1` | Core module with `wasi_snapshot_preview1` imports | Use for compatibility; WASIp1 interfaces no longer grow |
| WASI 0.2 and Component Model host | `wasm32-wasip2` | Component | The host must support components and the WASI interfaces that the program imports |
| WASIp1 host with the threads proposal | `wasm32-wasip1-threads` | Shared-memory core module | The host must provide threads and shared memory |
| Minimal WebAssembly 1.0 engine with `no_std` | `wasm32v1-none` | Core module | Use only when `core` and `alloc` are sufficient |

Do not use `wasm32-unknown-unknown` as a generic WASI target. It deliberately
has no WASI imports. Do not send a WASIp2 component to an API that accepts only
a core module.

Install and inspect the selected target:

```bash
rustup target add wasm32-unknown-unknown wasm32-wasip1 wasm32-wasip2
rustc --print cfg --target wasm32-wasip2
rustc -Ctarget-feature=help --target wasm32-unknown-unknown
```

Use the current target names. `wasm32-wasi` is the former name of
`wasm32-wasip1`.

## Keep portable logic separate

Put parsing, validation, state transitions, and business rules in a normal Rust
library. Put browser, Node.js, and WASI adapters at the edge. Run most tests on
the host, then run boundary tests in each shipped runtime.

Use target predicates only for facts that the compiler knows:

```rust
#[cfg(all(target_family = "wasm", target_os = "unknown"))]
fn minimal_wasm_host() -> bool {
    true
}

#[cfg(all(target_os = "wasi", target_env = "p1"))]
fn wasi_preview() -> u8 {
    1
}

#[cfg(all(target_os = "wasi", target_env = "p2"))]
fn wasi_preview() -> u8 {
    2
}

fn main() {}
```

Rust cannot detect browser against Node.js with `cfg`. If the same crate ships
to both, select adapters with explicit Cargo features and reject invalid feature
sets. Keep one neutral default when possible.

```rust
#[cfg(all(feature = "browser", feature = "node"))]
compile_error!("select only one JavaScript host feature");

fn main() {}
```

Target-specific dependency tables stop browser-only crates from entering WASI
resolution:

```toml
[target.'cfg(all(target_family = "wasm", target_os = "unknown"))'.dependencies]
wasm-bindgen = "0.2"
js-sys = "0.3"

[target.'cfg(all(target_family = "wasm", target_os = "unknown"))'.dependencies.web-sys]
version = "0.3"
features = ["Window", "console"]
```

Enable only the `web-sys` interfaces that the code uses. Each enabled interface
adds binding code and increases compile time and possible artifact size.

## Build for a JavaScript host

Use `cdylib` for a Rust library that `wasm-bindgen` exports:

```toml
[lib]
crate-type = ["cdylib", "rlib"]
```

Keep `rlib` when host tests or other Rust crates use the library.

Choose one generated-JavaScript contract and test that exact output:

| Consumer | Command | Output contract |
|---|---|---|
| A bundler such as Vite or webpack | `wasm-pack build --release --target bundler` | ES modules for bundler processing |
| Browser without a bundler | `wasm-pack build --release --target web` | ES module plus an asynchronous initializer |
| Node.js CommonJS consumer | `wasm-pack build --release --target nodejs` | Node.js loader and CommonJS glue |

For an ESM-only Node.js package, send `--target bundler` output through the
package's existing bundler and test the bundled result in Node.js. Do not label
`--target nodejs` output as ESM; its generated loader is CommonJS.

Do not publish the raw `target/wasm32-unknown-unknown/*/*.wasm` file when the
crate uses `wasm-bindgen`. The generated JavaScript glue implements its ABI.
Keep the Rust crate and the `wasm-bindgen` CLI on compatible versions. Prefer
`wasm-pack`, which coordinates the build and glue generation.

For `--target web`, wait for the initializer before you call any export:

```javascript
import init, { parse } from "./pkg/module.js";

await init();
const result = parse("input");
```

Serve browser tests over HTTP. Opening the HTML through `file://` does not prove
that module loading, MIME types, CORS, or `fetch` work in deployment.

## Design the JavaScript boundary

Keep the boundary narrow. Prefer numbers, booleans, strings, typed arrays, and
small exported handles. Convert once, then do bulk work in Rust.

- A string or vector conversion can allocate and copy. Do not cross the boundary
  once per element in a hot loop.
- A JavaScript typed-array view into WebAssembly memory can become stale after
  memory growth. Recreate the view after an allocation that can grow memory.
- Do not keep a borrowed Rust slice or string across a JavaScript callback or an
  `.await` point.
- Check generated TypeScript declarations for integer semantics. In particular,
  test 64-bit values in the real consumer instead of assuming JavaScript
  `number` can preserve them.
- Use `serde-wasm-bindgen` for structured values when its direct JS conversion
  matches the public API. Do not serialize JSON text only to cross the same
  in-process boundary.

Map expected failures to `Result`. For a synchronous exported function,
`Err(JsValue)` becomes a thrown JavaScript value. For an exported `async fn`,
it becomes a rejected `Promise`. Give consumers a stable error object or code;
do not make them parse a Rust debug string.

Mark an imported JavaScript function with `#[wasm_bindgen(catch)]` when it can
throw. Handle the returned `Result`. An unhandled JavaScript exception skips
normal Rust control flow and can bypass cleanup assumptions.

Treat callback lifetime as ownership:

1. Store the Rust `Closure` for as long as JavaScript can call it.
2. Unregister the JavaScript listener before you drop the `Closure`.
3. Use `Closure::forget` only for a callback that intentionally lives until the
   page or worker exits. It leaks the Rust allocation by design.

## Handle panic and error behavior

The standard WebAssembly targets use abort-oriented panic behavior by default.
A panic becomes a trap. Do not use `catch_unwind` as the normal error path and
do not assume a host can continue the same instance after a trap.

Use these rules:

- Return `Result` for input, network, capability, and domain failures.
- Install `console_error_panic_hook` in debug browser and Node.js builds when a
  readable JavaScript console stack is useful.
- Keep panic messages free of secrets and untrusted full payloads.
- Recreate or discard an instance after a trap when state integrity matters.
- Test the release profile. Debug-only panic output is not release behavior.

A panic hook improves diagnostics. It does not recover the computation. See
`rust-panic-safety` when a library changes the panic strategy or depends on
unwind behavior.

## Use the host async model

An `async fn` does not create an executor. Select the bridge that the host
provides.

For browser and Node.js builds:

- Convert JavaScript `Promise` values with `wasm_bindgen_futures::JsFuture`.
- Export an `async fn` when JavaScript must receive a `Promise`.
- Use `wasm_bindgen_futures::spawn_local` for a detached `!Send` future.
- Never block the JavaScript event-loop thread with a polling loop, synchronous
  sleep, or native blocking I/O.
- Do CPU-heavy work in bounded chunks or in a worker. An async wrapper alone
  does not move CPU work off the event-loop thread.

Do not enable a multi-thread Tokio runtime for ordinary browser WebAssembly.
Use only Tokio features that compile for the selected target, or use the host
Promise and timer APIs directly. WebAssembly threads require host support,
shared memory, worker setup, and the required HTTP isolation headers in a
browser. A successful `+atomics` compile proves none of those host conditions.

For WASI, select the executor and I/O library that supports the exact WASI
preview and runtime. Do not assume a native epoll, kqueue, socket, or thread
implementation exists. Run the I/O path under the shipping runtime.

## Build and inspect WASI artifacts

Build Preview 1 only for a host that implements its imports:

```bash
cargo build --locked --release --target wasm32-wasip1
wasm-tools validate target/wasm32-wasip1/release/<binary>.wasm
wasmtime run --dir ./fixtures target/wasm32-wasip1/release/<binary>.wasm
```

Grant only the directories, environment variables, sockets, and other host
capabilities that the test needs. A successful run with broad inherited access
does not prove the production capability policy.

Build a WASI 0.2 component for a component-aware host:

```bash
cargo build --locked --release --target wasm32-wasip2
wasm-tools validate target/wasm32-wasip2/release/<binary>.wasm
wasm-tools component wit target/wasm32-wasip2/release/<binary>.wasm
wasmtime run target/wasm32-wasip2/release/<binary>.wasm
```

Use native `wasm32-wasip2` and `wit-bindgen` tooling for new components. Do not
introduce `cargo-component` without a project-specific requirement; the
Component Model documentation is moving to native Cargo and Rust tooling.

Pin the WIT package versions and the host runtime together. A component can
validate structurally and still fail when the host provides a different world
or interface version.

## Test the matrix that ships

Use four layers. Stop only when all applicable layers pass.

1. Run portable logic on the host with `cargo nextest run --locked`.
2. Compile every supported target and feature set.
3. Run boundary tests in each real host mode.
4. Load the final packaged artifact from the JavaScript package or deployment
   directory, not from Cargo's target directory.

Browser and Node.js tests:

```bash
wasm-pack test --headless --chrome
wasm-pack test --headless --firefox
wasm-pack test --node
```

Do not replace browser tests with Node.js tests. Node.js has no DOM and uses a
different module loader. Do not replace runtime execution with
`cargo check --target`; it does not instantiate the module or resolve imports.

Add one JavaScript integration test that imports the generated package, awaits
initialization when required, calls a success path, and verifies the public
error shape. This catches stale glue, wrong package metadata, and a missing
`.wasm` deployment asset.

## Control compatibility and size

Build an explicit matrix in CI. Include the target, Cargo features, host, and
minimum host version in each row. Use `cargo tree --locked -e features` to find
an additive Cargo feature that leaks an unsupported dependency into a row.

Do not enable a WebAssembly target feature only because the compiler accepts
it. The final module can contain those instructions even when a runtime path
does not execute them. Validate the artifact in the oldest supported engine.
Gate optional SIMD code with `#[cfg(target_feature = "simd128")]` and keep a
portable implementation.

Measure the final packaged `.wasm`, both raw and compressed:

```bash
wc -c pkg/*_bg.wasm
gzip -9 -c pkg/*_bg.wasm | wc -c
twiggy top pkg/*_bg.wasm
```

Start with a measured release profile:

```toml
[profile.release]
opt-level = "s"
lto = true
codegen-units = 1
panic = "abort"
strip = "symbols"
```

Compare `opt-level = "s"`, `"z"`, and `3` on the final artifact. Smaller
codegen is not always a smaller compressed file or a faster application.
Run the full runtime test suite after `wasm-opt`. Pin its version in CI because
optimizer output and supported proposals change between releases.

Set a size budget on the packaged file. Report both the absolute size and the
change from the baseline. Do not count generated JavaScript, TypeScript, or
other shipped assets as zero.

## Triage

| Symptom | Likely cause | First check | Fix |
|---|---|---|---|
| `unknown import` at instantiation | Wrong target or missing host capability | Inspect imports with `wasm-tools print` | Select the correct target or implement and grant the import |
| `expected a WebAssembly.Module` for WASIp2 output | Host accepts a core module, but the artifact is a component | Run `wasm-tools component wit` | Use a component host or build the required core-module target |
| Export is undefined | Wrong generated-JS mode or initialization did not finish | Inspect the generated module and package test | Match the consumer mode and await initialization |
| `unreachable` or `RuntimeError` after a Rust failure | Panic became a trap | Enable bounded panic diagnostics and inspect the first panic | Return a typed error for expected failure; fix the panic |
| Callback fails after setup returns | Its Rust `Closure` was dropped | Find the owner and unregister path | Store the closure until listener removal |
| View returns corrupt or old bytes | Linear memory grew | Compare `memory.buffer` before and after allocation | Recreate the typed-array view |
| Browser passes but Node.js fails | DOM or ES-module assumption reached Node.js | Run the generated Node.js package test | Move the API behind the correct host adapter |
| Host build passes but Wasm target fails | Unconditional OS or thread dependency | Run `cargo tree -e features` for the target row | Gate the dependency and expose a portable interface |
| Module validates but fails on the oldest engine | Unsupported proposal or WIT version | Inspect target features and host interface versions | Rebuild to the supported baseline or raise the documented minimum |
| Size jumps after a small API change | Generic duplication, extra `web-sys` features, or glue growth | Compare `twiggy top` and package contents | Remove the measured source of growth |

## Completion evidence

Report:

- the target, host, minimum version, artifact type, and capability policy;
- the exact Cargo feature set and required WebAssembly proposals;
- the build, validation, and runtime commands for every shipped matrix row;
- a successful import of the final JavaScript package when JS glue exists;
- raw and compressed artifact sizes against the budget;
- any browser, Node.js, WASI, or component row that could not run.

Do not call the work complete when only the host tests or only
`cargo check --target` pass.
