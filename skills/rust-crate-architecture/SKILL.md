---
name: rust-crate-architecture
description: Use when you add, split, merge, rename, or remove a crate in a Rust workspace, when you define or enforce dependency layers and direction rules, when you decide whether new code belongs in a new crate or an existing module, when you restructure a workspace after a layering violation or a dependency cycle between normal crates, or when you lay out modules inside a crate that grew too large. A cyclic package dependency that involves a proc-macro crate belongs to rust-macros.
license: BSD-3-Clause
---

# Rust Crate Architecture

This skill covers the shape of a Rust workspace: which crates exist, which
crate is allowed to depend on which, and how modules are laid out inside a
crate. `cargo-workflows` covers the mechanics of the manifests, profiles, and
build commands. Use both together.

## Establish ground truth first

A workspace changes faster than its documentation. Before you move any crate,
read the current graph from cargo, not from a diagram.

```bash
# Authoritative machine-readable inventory of the workspace members.
cargo metadata --locked --no-deps --format-version 1

# Forward dependencies of one crate: what it is allowed to know.
cargo tree --locked -p <crate> -e normal

# Reverse dependencies of one crate: who is allowed to know it.
# Pass the crate as the value of -i, and keep --workspace, or the inverted
# tree is scoped to that crate alone and shows no dependents.
cargo tree --locked --workspace -i <crate>
```

Rules:

- Treat any hand-written architecture document as stale until `cargo metadata`
  agrees with it. Fix the document in the same change that moves a crate.
- Do not hardcode a crate count in documentation. Derive it from
  `cargo metadata`.
- Run every command from the directory that holds the workspace `Cargo.toml`,
  or pass `--manifest-path <workspace-root>/Cargo.toml`.

## The layer model

Give every crate exactly one layer. The layer says what the crate is allowed to
know. Names of layers matter less than the direction between them.

| Layer | Contents | May depend on | Must not depend on |
|-------|----------|---------------|--------------------|
| 0 Foundation | Pure data types, error types, format and protocol primitives. No I/O, no global state. | Third-party leaf crates only | Any workspace crate |
| 1 Domain | Algorithms, state machines, policy, decisions. Deterministic and testable without I/O. | Layer 0 | Layers 2 and 3 |
| 2 Runtime | I/O, sockets, files, timers, task scheduling, process state. | Layers 0-1 | Layer 3 |
| 3 Adapter | FFI boundary crates (`cdylib` / `staticlib`), platform bindings, CLI binaries. | Layers 0-2 | Nothing in the workspace depends on an adapter |

Two derived rules:

- **Place a new crate at the lowest layer that satisfies its dependencies.**
  If the crate compiles without a Layer 2 dependency, it is not a Layer 2 crate.
- **Dependencies flow toward smaller, shared crates and away from adapter
  crates.** An adapter crate is a sink. If something needs to depend on an
  adapter, the thing you need is in the wrong crate.

## Direction rules

### 1. No upward dependencies

A Layer N crate must not depend on a Layer N+1 crate. Cargo rejects cycles, but
an acyclic upward edge is still an architecture defect: it drags I/O, platform
code, and heavy dependency trees into crates that were supposed to stay pure.

Violation:

```toml
# crates/core-config/Cargo.toml   (Layer 0)
[dependencies]
runtime-engine = { workspace = true }   # WRONG: Layer 0 -> Layer 2
```

Fix: find the type that `core-config` actually needs, and move that type down
into Layer 0. The runtime crate then depends on the config crate, not the
reverse.

### 2. Independent stacks stay independent

When a workspace hosts two product areas, model them as two dependency trees
that meet only at the foundation layer.

```text
Stack A:  core-types -> core-config  -> domain-a -> runtime-a -> ffi-a
Stack B:  core-types -> device-config -> domain-b -> runtime-b -> ffi-b
                \______ shared Layer 0 crates ______/
```

`runtime-b` must not depend on `runtime-a`. If both stacks need the same type,
the type belongs in a Layer 0 crate that both already depend on. A cross-stack
edge means one stack can no longer be built, tested, or shipped alone.

### 3. Test-support crates are dev-dependencies only

Fixture and harness crates must appear under `[dev-dependencies]` only. They
pull in servers, temporary files, and assertion machinery that must never reach
a shipped artifact.

| Test-support crate role | Typical contents |
|-------------------------|------------------|
| Golden-file support | Snapshot loading, blessing, diff reporting |
| Network fixture | Local DNS / HTTP / TCP servers bound to loopback |
| Soak support | Long-running stress and leak harness |
| Platform support | Platform logging and binding helpers |

The only accepted exception is a platform-support crate that also carries real
runtime helpers. Such a crate may be a normal dependency, but only of adapter
crates, and never of a Layer 0 or Layer 1 crate.

### 4. Observation is an adapter edge, not a core dependency

A diagnostics, monitoring, or metrics crate may depend on domain and runtime
crates to observe them. Domain and runtime crates must not depend back on it.

```text
ALLOWED:   diagnostics-monitor -> runtime-engine -> domain
FORBIDDEN: runtime-engine -> diagnostics-monitor
```

When a runtime crate must emit an observation, define the sink as a trait or a
handle in a Layer 0 contracts crate. The runtime crate depends on the contract.
The monitor crate implements it. Split a large diagnostics area into a
contracts crate, a runner crate, and one crate per protocol or subsystem, so a
consumer takes only the part it needs. See `rust-observability`.

### 5. Platform isolation uses `cfg`, not layer breaks

Platform-specific code lives behind `#[cfg(target_os = "...")]`. A target-gated
dependency is still a dependency, and it must respect the same direction rules.

```toml
# Acceptable: a platform binding crate pulled in only on that target.
[target.'cfg(target_os = "android")'.dependencies]
jni = { workspace = true }
```

```toml
# WRONG: a target gate used to smuggle an upward dependency into a domain crate.
[target.'cfg(target_os = "android")'.dependencies]
ffi-adapter = { workspace = true }
```

A conditional dependency that is legal on one target and illegal on another is
a layering violation on every target. It also hides from a host-only CI job.

### 6. Adapter crates stay thin

An FFI or platform crate does four things: marshal arguments, manage handle
lifetimes, translate errors, and contain panics. Decisions and algorithms belong
one layer down, where they can be tested without the platform. See `rust-jni`,
`uniffi-boundary`, and `ffi-error-progress-cancel`.

## Crate or module?

A new crate is not free. It costs a manifest, a lint block, an entry in two
workspace tables, a place in the members order, and one more unit that every
contributor has to locate. Default to a module inside an existing crate.

Create a crate when at least one of these is true:

- Two otherwise-unrelated crates both need the code, and neither should inherit
  the other's dependency tree.
- The code needs a different unsafe policy, for example the surrounding crate is
  `#![forbid(unsafe_code)]` and this code cannot be.
- The code needs a different dependency set, feature set, or target set: a
  host-only tool, a platform binding, a heavy optional backend.
- The code is a deliberate rebuild boundary: it is stable and large, and the
  code around it changes every day.
- The code is published separately.

These are not reasons: the file is long, the area "feels like a component",
one type wants a home of its own. Split the module first. Promote it to a crate
when a rule above becomes true.

## Creating a new crate

### Checklist

1. **Choose the layer.** List the crates the new crate must depend on. Its layer
   is one above the highest of them. If that puts it above the crate that will
   use it, the design is wrong: stop and re-read [Direction rules](#direction-rules).

2. **Create the directory** from the workspace root. `crates/` is the common
   layout; use whatever directory the workspace already uses for members.

   ```bash
   cargo init --lib crates/<crate-name>
   ```

3. **Register it in the workspace `Cargo.toml`**, in alphabetical order in both
   tables:

   ```toml
   [workspace]
   members = [
       # ... existing members, leaf crates first, adapter crates last
       "crates/<crate-name>",
   ]

   [workspace.dependencies]
   # The path resolves the crate inside the workspace.
   <crate-name> = { path = "crates/<crate-name>" }
   ```

   `cargo init` appends the member to `members` for you, at the end of the
   list. Move the entry into alphabetical order yourself. `cargo init` never
   writes the `[workspace.dependencies]` entry. Add that entry by hand. Without
   it, a dependent that writes `workspace = true` fails to resolve.

   Add a `version` field to the `[workspace.dependencies]` entry only when you
   publish the crate, and set it to the version the member actually has. A
   version requirement that does not match the member version makes every
   cargo command fail with `failed to select a version for the requirement`.

4. **Write the crate manifest.** Inherit everything the workspace defines, and
   take every dependency through `workspace = true`:

   ```toml
   [package]
   name = "<crate-name>"
   edition.workspace = true
   version.workspace = true
   license.workspace = true

   [dependencies]
   core-types = { workspace = true }

   [dev-dependencies]
   golden-test-support = { workspace = true }

   [lints]
   workspace = true
   ```

5. **Add the safety attribute** to `src/lib.rs`:

   ```rust
   #![forbid(unsafe_code)]
   ```

   Omit it only when the crate genuinely needs `unsafe`: an FFI or JNI crate, a
   driver, a crate over a raw C API. A crate that keeps `unsafe` must document
   every block. See `rust-unsafe`.

6. **Verify before you write any logic:**

   ```bash
   cargo clippy --locked -p <crate-name> --all-targets -- -D warnings
   cargo deny --locked check
   cargo tree --locked -p <crate-name> -e normal
   ```

   Read the tree output. Every crate in it must sit at or below the new crate's
   layer.

### Naming conventions

- When a workspace hosts several independent stacks, give each stack one prefix:
  `<stack>-<role>`. The prefix makes a cross-stack dependency visible in a diff.
- Name test-support and utility crates by role, with no stack prefix:
  `golden-test-support`, `network-fixture`.
- Do not encode a layer number in the name. Layers move during a refactor;
  renaming a crate is expensive.
- Crate names use hyphens. The library target and the `use` path use
  underscores, and so does the built artifact file name. Renaming a crate
  renames `lib<name>.so` or `lib<name>.a` and breaks every loader and binding
  that names it. See `cargo-workflows`.

## Module structure inside a crate

Pick the layout from the size of the crate. Move up a tier when the current tier
stops fitting on one screen of `ls`.

### Small crate, under about 500 lines

A single `src/lib.rs` with an inline `#[cfg(test)] mod tests`.

### Medium crate, about 500 to 2000 lines

```text
src/
  lib.rs           # mod declarations + pub use re-exports
  types.rs         # data structures
  logic.rs         # core algorithms
```

Keep tests inline, or in a single `tests.rs`.

### Large crate, over about 2000 lines

```text
src/
  lib.rs           # mod declarations + pub use re-exports
  engine.rs        # module root: declares its sub-modules
  engine/
    plan.rs
    report.rs
    runners.rs
    tests.rs       # focused test module for engine/
  types.rs         # module root
  types/
    request.rs
    response.rs
  test_fixtures.rs # shared test helpers, #[cfg(test)]
  tests.rs         # top-level unit tests
tests/
  integration.rs   # integration tests: public API only
  golden/          # golden test fixtures
```

Rules:

- Use the `name.rs` + `name/` pattern. Use `mod.rs` only at three or more levels
  of nesting, where the repeated file name stops being ambiguous.
- `lib.rs` holds `mod` declarations and `pub use` re-exports, and nothing else.
  Keep the public surface one level deep, so a caller writes
  `my_crate::Request`, not `my_crate::types::request::Request`.
- Everything not re-exported stays `pub(crate)`. A `pub` item is an API promise.
- A file under `tests/` links against the crate as an external user. It can only
  use the public API, which makes it the honest check on the re-export list.

## Restructuring an existing workspace

Read `references/dependency-direction.md` for the full procedure. The short
form:

| Situation | Move |
|-----------|------|
| Two crates need the same type | Move the type down to the lowest crate both already depend on |
| A lower crate calls into a higher crate | Invert with a trait defined in the lower crate |
| One crate does two unrelated jobs | Split it, and keep a re-export shim for one release to keep the diff reviewable |
| Two crates always change together and share no other consumer | Merge them, and delete a layer boundary that was never real |
| A cycle appears the moment you add an edge | The edge is wrong; find the shared type and extract it downward |

Do a restructure on its own branch, and in its own commit. A move plus a
behavior change in one diff is unreviewable.

## Verification and review gate

Run these before you claim a crate change is complete:

```bash
cargo metadata --locked --no-deps --format-version 1     # inventory changed as intended
cargo tree --locked -p <changed-crate> -e normal          # no higher-layer crate appears
cargo tree --locked --workspace -i <foundation-crate>     # who now depends on the shared crate
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo deny --locked check
```

Checklist:

- [ ] The new or moved crate sits at the lowest layer that compiles.
- [ ] `cargo tree -e normal` for the crate contains no crate from a higher layer.
- [ ] No cross-stack edge appeared.
- [ ] Test-support crates are under `[dev-dependencies]` only.
- [ ] The crate manifest inherits `edition`, `version`, `license`, and
      `[lints] workspace = true`.
- [ ] Every dependency uses `workspace = true`.
- [ ] `#![forbid(unsafe_code)]` is present, or the `unsafe` need is stated.
- [ ] The crate appears in both `members` and `[workspace.dependencies]`, in
      alphabetical order.
- [ ] `Cargo.lock` is committed with the change.
- [ ] The architecture document matches `cargo metadata` again.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Upward dependency, for example Layer 1 -> Layer 2 | Extract the shared type into a lower-layer crate |
| Cross-stack dependency between two independent trees | Keep the stacks independent; put the shared type in Layer 0 |
| Runtime crate depends on the diagnostics crate | Define the sink as a trait in a contracts crate; invert the edge |
| Test-support crate under `[dependencies]` | Move it to `[dev-dependencies]` |
| Missing `[lints] workspace = true` in a new crate | Always inherit the workspace lints |
| Missing `#![forbid(unsafe_code)]` on a safe crate | Add it to `lib.rs` unless the crate genuinely needs `unsafe` |
| `version = "0.1.0"` in a member manifest | Use `version.workspace = true`; all members share one version |
| Dependency declared with an explicit version in a member | Use `workspace = true` so the version stays in one place |
| Crate added to `members` but not to `[workspace.dependencies]` | Add both; `workspace = true` in a dependent needs the second entry |
| New member appended at the end of `members` | Keep the list in alphabetical order inside its group |
| Logic added to an FFI or platform adapter crate | Move it one layer down, where it can be tested without the platform |
| Target-gated dependency that breaks the layer model | The gate does not make the edge legal; restructure instead |
| A crate created for one type | Make it a module; promote it when a real crate reason appears |

## Related skills

- `cargo-workflows` for manifests, dependency inheritance, workspace lints,
  profiles, cross-compilation, and edition migration.
- `rust-lints` for the lint catalogue that `[lints] workspace = true` inherits.
- `rust-unsafe` for the crates that cannot use `#![forbid(unsafe_code)]`.
- `rust-discipline` for the public API surface a crate boundary exposes.
- `rust-observability` for the contract a diagnostics crate implements.
- `rust-jni`, `uniffi-boundary`, and `ffi-error-progress-cancel` for what an
  adapter crate at Layer 3 is allowed to contain.
