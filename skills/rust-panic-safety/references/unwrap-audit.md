# Unwrap audit and typed-error migration

Use this file when a workspace already has a large `.unwrap()` and `.expect()` population and
you must reduce the risk without a rewrite.

## Step 1: measure, do not remember

```bash
# Total in production code.
rg -n --type rust '\.unwrap\(\)|\.expect\(' \
  -g '!target/**' -g '!**/tests/**' -g '!**/benches/**' | wc -l

# Per crate, worst first.
rg -c --type rust '\.unwrap\(\)|\.expect\(' \
  -g '!target/**' -g '!**/tests/**' -g '!**/benches/**' \
  | sort -t: -k2 -rn | head -20

# Only the crates that sit on an FFI path.
rg -l 'extern "(C|system)"' --type rust | xargs -n1 dirname | sort -u
```

Record the number in the pull request, not in the skill. The number changes; the method does
not.

## Step 2: rank by reachability, not by count

A crate with 400 unwraps that no foreign caller reaches is lower risk than a crate with 12
unwraps inside an entry point. Rank the sites:

| Rank | Site | Why |
|---|---|---|
| 1 | Inside an `extern` body, outside the guard | Kills the host process immediately |
| 2 | On a code path an entry point calls, with input-derived data | Turns any malformed input into a crash |
| 3 | In a `Drop` implementation | Double panic during unwinding aborts |
| 4 | In a callback that a foreign runtime invokes | Unwinds into foreign frames |
| 5 | In a spawned task or thread | Kills the task; may deadlock the waiter |
| 6 | In startup code that runs once | Fails loudly and early; lowest risk |

Fix rank 1 to 4 first. Leave rank 6 alone unless it is cheap.

## Step 3: replace by category

### `Result` with an error type

```rust
// Before
let config = serde_json::from_str::<Config>(raw).unwrap();

// After
let config: Config = serde_json::from_str(raw).map_err(Error::InvalidConfig)?;
```

### `Option` from input

```rust
// Before
let host = url.host_str().unwrap();

// After
let host = url.host_str().ok_or(Error::MissingHost)?;
```

### Indexing and slicing

```rust
// Before
let header = &buf[..HEADER_LEN];

// After
let header = buf.get(..HEADER_LEN).ok_or(Error::Truncated)?;
```

### Numeric conversion

```rust
// Before
let len = buf.len() as u32;   // silently truncates

// After
let len = u32::try_from(buf.len()).map_err(|_| Error::TooLarge)?;
```

Keep the `.unwrap()` only when the bound is checked in the same function, and write the
proof. The check must survive release builds:

```rust
assert!(buf.len() <= MAX_U32 as usize, "buffer length is bounded by construction");
// Infallible: `buf.len() <= MAX_U32` is checked above.
let len: u32 = buf.len().try_into().unwrap();
```

Use the `map_err` form above when the length comes from input. An assertion is
only for a bound that construction already guarantees.

### Arithmetic

Integer overflow panics in debug builds and wraps in release builds unless the profile sets
`overflow-checks = true`. A wrapped length is worse than a panic, because it becomes a bad
slice bound.

```rust
let end = offset.checked_add(len).ok_or(Error::Overflow)?;
```

Turn on `overflow-checks = true` in the release profile of any crate that parses untrusted
input. You trade a small cost for a caught bug.

### Allocation

`Vec::with_capacity(n)` with an attacker-controlled `n` aborts when the allocator fails, and
no guard catches an abort.

```rust
let mut buf = Vec::new();
buf.try_reserve(len).map_err(|_| Error::TooLarge)?;
```

Bound the length before you allocate. `try_reserve` is the second line of defence, not the
first.

### Lock acquisition

```rust
// Acceptable: a poisoned lock is a fatal invariant violation.
let state = self.state.lock().expect("state mutex poisoned");
```

If the data is still valid after a panic, say so and recover:

```rust
// The map is only ever inserted into, so a partial insert cannot corrupt it.
let state = self.state.lock().unwrap_or_else(|err| err.into_inner());
```

### Environment and configuration at startup

```rust
// Before
let path = std::env::var("APP_DATA_DIR").unwrap();

// After
let path = std::env::var("APP_DATA_DIR").map_err(|_| Error::MissingEnv("APP_DATA_DIR"))?;
```

A library must never read the environment and panic. An application may fail fast, but it
should still print a usable message.

## Step 4: roll out the lints

Deny in one crate at a time. A workspace-wide `deny` on day one produces hundreds of
findings and gets reverted.

Order:

1. `clippy::panic`, `clippy::todo`, `clippy::unimplemented`, `clippy::unreachable` — usually
   a small population, and each hit is a real defect.
2. `clippy::unwrap_used` on the FFI adapter crates.
3. `clippy::expect_used` as `warn` on the same crates.
4. `clippy::indexing_slicing` and `clippy::arithmetic_side_effects` on parsers and decoders.
5. `clippy::panic_in_result_fn` everywhere. A function that returns `Result` and still panics
   defeats its own signature.
6. `clippy::missing_panics_doc` on public APIs that keep a documented panic.

```toml
# Workspace root Cargo.toml: the floor that every member inherits.
[workspace.lints.clippy]
panic = "deny"
todo = "deny"
unimplemented = "deny"
panic_in_result_fn = "deny"
```

```toml
# Member Cargo.toml: inherit the floor unchanged.
[lints]
workspace = true
```

```toml
# Member Cargo.toml of a crate on an FFI path: a local table instead of the floor.
[lints.clippy]
panic = "deny"
todo = "deny"
unimplemented = "deny"
panic_in_result_fn = "deny"
unwrap_used = "deny"       # tighten per crate as it is cleaned
```

Cargo rejects a manifest that sets `lints.workspace = true` and a `[lints.<tool>]` table at
the same time: `cannot override 'workspace.lints' in 'lints'`. A member either inherits the
floor or restates the whole list locally. Restate the list for the crates you tighten.

```toml
# clippy.toml at the workspace root
allow-unwrap-in-tests = true
allow-expect-in-tests = true
allow-panic-in-tests = true
```

Verify with the same command the CI uses:

```bash
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

## Step 5: the `#[allow]` contract

A local `#[allow]` is acceptable only with a justification on the same line or directly above.

```rust
// The key is inserted three lines above, so the lookup cannot miss.
#[allow(clippy::unwrap_used)]
let entry = map.get(&key).unwrap();
```

Rules:

- Never put `#![allow(clippy::unwrap_used)]` at a crate root to silence a migration. That
  deletes the signal for every future line.
- Scope the allow to the smallest item: the statement or the function, not the module.
- An allow with no comment is a review failure, the same as a bare `.unwrap()`.
- Re-check the allows when the surrounding code changes. The proof is attached to the code
  around it, and that code moves.

## Typed error design

Design the error type so the boundary can map it without a string match.

```rust
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("invalid input: {0}")]
    InvalidInput(String),
    #[error("resource not found")]
    NotFound,
    #[error("operation cancelled")]
    Cancelled,
    #[error("i/o failure")]
    Io(#[from] std::io::Error),
}
```

Rules:

- One error enum per crate, not one per function. A caller that must match on six unrelated
  enums stops matching and starts stringifying.
- Mark it `#[non_exhaustive]` when the crate is a public dependency, so a new variant is not
  a breaking change.
- Use `#[from]` only where the conversion is unambiguous. Two `#[from]` arms for the same
  source type do not compile, and that is a design signal.
- Keep the `Display` text short and free of secrets. It can end up in a host log or in an
  exception message that a user sees.
- Do not put a backtrace in the error type on an FFI path. The shipped panic hook emits only a
  closed site code plus bounded numeric location. Reproduce locally with
  `RUST_BACKTRACE=full`, or symbolicate the crash artifact offline against the exact binary.

### Where `anyhow` still fits

- Binaries, CLIs, and test harnesses: one propagation type, one report at the top.
- Internal orchestration code that never appears in a public signature.
- `anyhow::Context` on the way up, to add the operation name and the parameters:

  ```rust
  // `with_context` is a trait method. Without this import it is not in scope,
  // and the error reads "no method named `with_context`".
  use anyhow::Context as _;

  let raw = std::fs::read_to_string(&path)
      .with_context(|| format!("read config at {}", path.display()))?;
  ```

Convert to a typed error before the value crosses a crate boundary that a binding layer
consumes. Downcasting an `anyhow::Error` at an FFI boundary is a sign the type was wrong two
layers earlier.

## Audit report shape

When you finish an audit, report these lines and nothing else:

1. Total `.unwrap()`/`.expect()` in production code, before and after.
2. The count on FFI-reachable paths, before and after.
3. Crates that now deny `clippy::unwrap_used`.
4. Every remaining rank 1 to 4 site, with the reason it stays.
5. The lint command CI runs, so the next reviewer can reproduce the number.
