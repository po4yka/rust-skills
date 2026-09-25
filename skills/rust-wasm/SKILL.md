---
name: rust-wasm
description: Use when building, testing, or shrinking Rust for WebAssembly (wasm32-unknown-unknown, wasm32-wasip1, wasm32-wasip2, wasm32v1-none) in a browser, Node.js, a WASI runtime, or a WebAssembly Component Model host, or when diagnosing a wasm-bindgen boundary, instantiation, link, target-feature, or wasm binary size failure. Triggers on wasm-pack, wasm-bindgen, wit-bindgen, wasmtime, WASI, getrandom wasm_js, and "time not implemented on this platform".
license: BSD-3-Clause
---

# Rust WebAssembly

Build and verify Rust for the exact WebAssembly host that runs it. A `.wasm`
suffix does not define an ABI, an import set, or a runtime.

Related skills, when installed: `cargo-workflows` for features and profiles,
`rust-async-internals` for executor-independent futures, `rust-performance` and
`rust-hot-path` for a measured hotspot. This skill owns the host event loop,
WebAssembly limits, artifact size, and boundary costs.

## Write the host contract first

When you add a WebAssembly target, a host, or a published package, record these
facts. They decide the target, the dependencies, and the test matrix:

1. Name the Rust target triple.
2. Name the host and its minimum version.
3. Name the artifact format: core module or component.
4. List allowed imports and capabilities.
5. Name the JavaScript output mode when JavaScript glue exists.
6. Name the engine feature baseline: the WebAssembly features that the oldest
   supported engine accepts.

Do not infer the host from `target_arch = "wasm32"`. Browser, Node.js, WASIp1,
and WASIp2 builds can share that architecture and still have incompatible APIs.

## Select the target

| Host contract | Rust target | Output | Important constraint |
|---|---|---|---|
| Browser or JavaScript host with explicit imports | `wasm32-unknown-unknown` | Core module, often with generated JS | `std::fs` fails, `println!` does nothing, `std::thread::spawn` panics, and `Instant::now()` and `SystemTime::now()` panic |
| Existing WASI Preview 1 host | `wasm32-wasip1` | Core module with `wasi_snapshot_preview1` imports | Use for compatibility; WASIp1 interfaces no longer grow |
| WASI 0.2 and Component Model host | `wasm32-wasip2` | Component | The host must support components and the WASI interfaces that the program imports |
| WASIp1 host with the threads proposal | `wasm32-wasip1-threads` | Shared-memory core module | The host must provide threads and shared memory |
| Minimal WebAssembly 1.0 engine with `no_std` | `wasm32v1-none` | Core module | Use only when `core` and `alloc` are sufficient |
| WASI 0.3 async component host | `wasm32-wasip3` | Component | Tier 3 as of Rust 1.98.1: rustup ships no `std` for it. Do not select it for a stable-toolchain product ([target page](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip3.html)) |

Do not use `wasm32-unknown-unknown` as a generic WASI target. It deliberately
has no WASI imports. Do not send a WASIp2 component to an API that accepts only
a core module.

The `std` targets do not emit WebAssembly 1.0 code. They enable `multivalue`,
`mutable-globals`, `reference-types`, and `sign-ext` by default, and `bulk-memory` and
`nontrapping-fptoint` since Rust 1.87 (LLVM 20). An engine without one of these
features can reject the module. For a 1.0 engine, use `wasm32v1-none` on stable,
or rebuild `std` for the MVP on nightly. Read `references/target-setup.md` when
the engine baseline is older than these defaults or the MSRV is below 1.87.

Do not enable a WebAssembly target feature only because the compiler accepts
it. The final module can contain those instructions even when a runtime path
does not execute them. Gate optional SIMD code with
`#[cfg(target_feature = "simd128")]` and keep a portable implementation.

Install each target with `rustup target add <triple>`. Rust 1.84 removed the
`wasm32-wasi` name, so that command fails for it. Rename it to `wasm32-wasip1`
in CI, `.cargo/config.toml`, and `rust-toolchain.toml`.

## Triage

| Symptom | Likely cause | First check | Fix |
|---|---|---|---|
| `unknown import` at instantiation | Wrong target or missing host capability | Inspect imports with `wasm-tools print` | Select the correct target or implement and grant the import |
| `rust-lld: error: ...: undefined symbol: <name>` on Rust 1.96+ | WebAssembly targets no longer pass `--allow-undefined`, so an undeclared import no longer becomes an `env` import | Find the `extern` block or the C object that should provide `<name>` | Put `#[link(wasm_import_module = "<module>")]` on the `extern` block of a host import; fix the C build otherwise. Use `-Clink-arg=--allow-undefined` only as a temporary migration shim |
| Wasmtime: `expected a WebAssembly module but was given a WebAssembly component`; V8 or Node.js: `expected version 01 00 00 00, found 0d 00 01 00` | Host accepts a core module, but the artifact is a component | Run `wasm-tools component wit` | Use a component host or build the required core-module target |
| `compile_error!` from `getrandom` on `wasm32-unknown-unknown` | No random backend for a JavaScript host | `cargo tree --locked --target wasm32-unknown-unknown -e features -i getrandom` | Enable the backend for each major version in the final `cdylib` or binary, never in a library (see "Keep portable logic separate") |
| "rust Wasm file schema version" from `wasm-bindgen` | CLI version differs from the locked crate | Compare `wasm-bindgen --version` with `Cargo.lock` | Install the exact locked version, or build through `wasm-pack` |
| `wasm-opt` rejects bulk-memory or non-trapping float-to-int instructions | The optimizer does not enable the Rust 1.87+ default features | Find `found wasm-opt at ...` in the wasm-pack log (absent means the bundled binaryen ran), then run `wasm-opt --version` on that binary | Enable both features in the `wasm-opt` arguments; `references/size-and-optimizer.md` has the setting |
| `cc` build script fails for a WASI target, for example `'stdio.h' file not found` | `cc` fell back to a system `clang` with no WASI sysroot | `echo "$WASI_SDK_PATH"`, `ls "$WASI_SDK_PATH/bin"`, and the `cc` version in `Cargo.lock` (1.2.39 or later) | Install wasi-sdk, set `WASI_SDK_PATH`, and update `cc`, or set `CC_<target>`; `references/wasi.md` has the details |
| Export is undefined | Wrong generated-JS mode or initialization did not finish | Inspect the generated module and package test | Match the consumer mode and await initialization |
| "time not implemented on this platform", or a bare `RuntimeError: unreachable` near timing code | `Instant::now()` or `SystemTime::now()` on `wasm32-unknown-unknown` | Install the panic hook in a debug build and read the message | Read the clock in the JavaScript adapter. For a dependency, enable its wasm or JavaScript feature, or replace it (`web-time` gives drop-in types) |
| `unreachable` or `RuntimeError` after a Rust failure | Panic became a trap | Enable bounded panic diagnostics and inspect the first panic | Return a typed error for expected failure; fix the panic; discard the instance when state integrity matters |
| Callback fails after setup returns | Its Rust `Closure` was dropped | Find the owner and unregister path | Store the closure until listener removal |
| View returns corrupt or old bytes | Linear memory grew | Compare `memory.buffer` before and after allocation | Recreate the typed-array view |
| Browser passes but Node.js fails | DOM or ES-module assumption reached Node.js | Run the generated Node.js package test | Move the API behind the correct host adapter |
| Host build passes but Wasm target fails | Unconditional OS or thread dependency | Run `cargo tree --target <triple> -e features` for the row | Gate the dependency and expose a portable interface |
| Module validates but fails on the oldest engine | Default post-1.0 features, an enabled proposal, or a WIT version the host lacks | `wasm-tools validate --features=wasm1` (or `wasm2`), then the host interface versions | Build for the baseline (`wasm32v1-none`, or an MVP `std` build on nightly) or raise the documented minimum |
| Size jumps after a small API change | Generic duplication, extra `web-sys` features, or glue growth | Compare `twiggy top` or `wasm-tools objdump` output and package contents | Remove the measured source of growth |

## Verify the matrix that ships

Use four layers. Stop only when all applicable layers pass.

1. Run portable logic on the host with `cargo nextest run --locked`, or
   `cargo test --locked` when cargo-nextest is not installed.
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
error shape and any 64-bit value round trip. This catches stale glue, wrong
package metadata, and a missing `.wasm` deployment asset.

Build an explicit matrix in CI. Include the target, Cargo features, host, and
minimum host version in each row. Use
`cargo tree --locked --target <triple> -e features` to find an additive Cargo
feature that leaks an unsupported dependency into a row.

Validate each final artifact against the engine baseline. Plain
`wasm-tools validate` accepts every phase 4 proposal, so it proves nothing about
an old engine. `wasm2` includes SIMD; append `,-simd` when the baseline has no
SIMD. A `wasm1` or `wasm2` group replaces the whole feature set and turns off
the component model, so for a component add `,component-model`.

```bash
wasm-tools validate --features=wasm2 pkg/<name>_bg.wasm   # WebAssembly 2.0 engine
wasm-tools validate --features=wasm1 pkg/<name>_bg.wasm   # WebAssembly 1.0 engine
wasm-tools validate --features=wasm2,component-model target/wasm32-wasip2/release/<binary>.wasm
wasm-tools print pkg/<name>_bg.wasm | grep '(import '     # compare with the host contract
```

Read `references/wasi.md` when a matrix row targets `wasm32-wasip1` or
`wasm32-wasip2`. It has the build, validate, and `wasmtime run` commands. Grant a
WASI run only the directories, environment variables, sockets, and other host
capabilities that it needs. A run with broad inherited access does not prove the
production capability policy. Pin the WIT package versions and the host runtime
together. A component can validate and still fail against a different world or
interface version.

Run the checks again after a toolchain bump, a dependency bump, or a `wasm-opt`
change. Load the module in the oldest supported engine when the contract names
one.

Measure the final packaged `.wasm`, raw and gzip-compressed, against a size
budget. Pin the wasm-pack version and the `wasm-opt` that it runs: a wasm-pack
upgrade can silently change the bundled optimizer. Read
`references/size-and-optimizer.md` when you set a size budget, change the
release profile, or change how `wasm-opt` runs.

## Completion evidence

Report:

- the target, host, minimum version, artifact type, and capability policy;
- the exact Cargo feature set and the engine feature baseline;
- the build, validation, and runtime commands for every shipped matrix row,
  including the `wasm-tools validate --features=...` baseline check and the
  import list of each final artifact;
- a successful import of the final JavaScript package when JS glue exists;
- raw and compressed artifact sizes against the budget;
- any browser, Node.js, WASI, or component row that could not run.

## Keep portable logic separate

Put parsing, validation, state transitions, and business rules in a normal Rust
library. Put browser, Node.js, and WASI adapters at the edge.

Use target predicates only for facts that the compiler knows:
`cfg(all(target_family = "wasm", target_os = "unknown"))` for a bare JavaScript
host, and `cfg(all(target_os = "wasi", target_env = "p1"))` or
`target_env = "p2"` for a WASI preview. Rust cannot detect browser against
Node.js with `cfg`. If the same crate ships to both, select adapters with
explicit Cargo features and reject invalid feature sets. Keep one neutral
default when possible.

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

Enable only the `web-sys` interfaces that the code uses. Each one adds binding
code, compile time, and possible artifact size.

Inject the clock. On `wasm32-unknown-unknown`, read time in the JavaScript
adapter (`js_sys::Date::now()` or `web_sys::Performance::now()`) and pass it to
the portable code, because `std::time` panics there.

`getrandom` has no default backend on `wasm32-unknown-unknown`. Enable feature
`wasm_js` (0.3.4 and later, 0.4) or `js` (0.2) for each major version in the
graph. Set it in the final `cdylib` or binary crate, not in a library: upstream
warns that it breaks non-JavaScript WebAssembly builds. Read
`references/target-setup.md` when the graph holds `getrandom` 0.3.0 to 0.3.3 or
more than one major version.

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

Use the `wasm-bindgen` CLI at the exact `wasm-bindgen` version in `Cargo.lock`.
Upstream supports only an exact match. Prefer `wasm-pack`: it reads
`Cargo.lock` and installs the matching CLI. In a manual pipeline, run
`cargo install wasm-bindgen-cli --locked --version <locked version>`, and
install the same version again after each `wasm-bindgen` update.

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
   `Closure::into_js_value()` hands ownership to JavaScript instead; the
   JavaScript garbage collector frees it where the engine supports weak
   references, and it leaks otherwise.

## Handle panic and error behavior

The standard WebAssembly targets use abort-oriented panic behavior by default.
A panic becomes a trap. Do not use `catch_unwind` as the normal error path and
do not assume a host can continue the same instance after a trap. Unwinding
needs nightly `-Zbuild-std`, so do not design a stable product around it.

- Return `Result` for input, network, capability, and domain failures.
- Install `console_error_panic_hook` in debug browser and Node.js builds when a
  readable JavaScript console stack is useful. Its repository is archived; the
  crate still works, but expect no fixes.
- Keep panic messages free of secrets and untrusted full payloads.
- Recreate or discard an instance after a trap when state integrity matters.
- Test the release profile. Debug-only panic output is not release behavior.

A panic hook improves diagnostics. It does not recover the computation. Use the
`rust-panic-safety` skill, when it is installed, when a library changes the
panic strategy or depends on unwind behavior.

## Use the host async model

An `async fn` does not create an executor. Select the bridge that the host
provides.

For browser and Node.js builds:

- Convert JavaScript `Promise` values with `wasm_bindgen_futures::JsFuture`.
- Export an `async fn` when JavaScript must receive a `Promise`.
- Use `wasm_bindgen_futures::spawn_local` for a detached `!Send` future.
- Never block the JavaScript event-loop thread with a polling loop, synchronous
  sleep, or native blocking I/O. A loop that waits for a Promise never ends,
  because no Promise can resolve while the thread is blocked. Other blocking
  calls freeze the page or the Node.js process.
- Do CPU-heavy work in bounded chunks or in a worker. An async wrapper alone
  does not move CPU work off the event-loop thread.

Do not enable a multi-thread Tokio runtime for ordinary browser WebAssembly.
Use only Tokio features that compile for the selected target, or use the host
Promise and timer APIs directly. WebAssembly threads require host support,
shared memory, worker setup, and the required HTTP isolation headers in a
browser. A successful `+atomics` compile proves none of those host conditions.

For WASI, do not assume a native epoll, kqueue, socket, or thread
implementation. Read `references/wasi.md` when you select the executor and I/O
library for a WASI preview.

## Build WASI artifacts

Read `references/wasi.md` when you ship a WASI component or compile C or C++
for a WASI target.
