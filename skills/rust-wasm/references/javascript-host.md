# JavaScript host builds and boundary

Use this file when the crate exports to a browser or Node.js through
`wasm-bindgen`. It holds "Build for a JavaScript host" and "Design the
JavaScript boundary" from `SKILL.md`.

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
