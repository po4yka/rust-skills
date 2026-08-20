# Binding compatibility: checksums, the regeneration gate, and review

Detail behind the versioning rules in `SKILL.md`.

---

## What the checksum protects, and what it does not

UniFFI computes an API checksum per exported function and per exported type. The
generated Kotlin and Swift embed the expected values and compare them against
the loaded library the first time the binding touches it. A mismatch throws
immediately.

Treat that as the second line of defence, not the first. The properties matter:

| Property | Value |
|----------|-------|
| When it fires | At library load or first call, not at compile time |
| How it fails | Hard error, no silent fallback |
| What it covers | Function signatures, type identities, method sets |
| What it does **not** cover | Field additions inside an exported record (uniffi-rs #1789) |

The uncovered case is dangerous in both skew directions. New bindings with a
stale library expect a field that is absent and exhaust the `RustBuffer`. A new
library with stale bindings emits an extra field; the old reader can reject or
ignore trailing data, depending on the generated reader and UniFFI version.
Plausible but wrong values require a layout change that still has a compatible
encoded shape, such as reordering two fields of the same type. Do not claim that
every appended field silently shifts old values.

There is no reliable run-time defence across versions and skew directions. The
portable defence is process: regenerated bindings and the rebuilt library land
in the same commit.

Do not group every skew failure under the record checksum gap:

| Native or scaffolding | Consumer bindings | Expected failure |
|-----------------------|-------------------|------------------|
| Same generated revision | Same revision | No skew failure |
| Changed checksummed export | Stale revision | Hard checksum mismatch at first use |
| Stale library without an added record field | New bindings with that field | `RustBuffer` exhaustion or deserialization error |
| New library with an added record field | Stale bindings without that field | Trailing data is rejected or ignored; behavior depends on generated reader and version |
| Type-compatible field reorder on either side | Opposite stale layout | Values can be assigned to the wrong fields without a checksum error |
| One generated interface side is stale at link time | Newer other side | Undefined symbols or linker failure; #333 asks for clearer diagnostics |

---

## Regeneration script contract

Write one script, check it in, and make it the only supported way to regenerate.
Hand-run `cargo run ... uniffi-bindgen` invocations drift between developers.

### Modes

| Mode | Behaviour | Exit code |
|------|-----------|-----------|
| `--check` (default) | Generate into a temporary directory, `diff` against the checked-in files, print the diff | Non-zero on any difference |
| `--write` | Generate and overwrite the checked-in files | Non-zero only on a build or generation failure |

Make `--check` the default. A script that writes by default eventually runs in
CI by accident and hides the very drift it exists to catch.

### Steps the script must perform

1. Build the host library with `--locked`. Fail if `Cargo.lock` would change.
2. Locate the host library by trying both `lib<crate_name>.dylib` and
   `lib<crate_name>.so`. Do not branch on the operating system name.
3. Run the in-crate bindgen once per language, each into its own temporary
   directory.
4. Normalize the output: strip trailing whitespace, enforce a single final
   newline. Editors and formatters differ between machines; without
   normalization the `--check` gate fails on invisible characters.
5. Normalize the modulemap file name to the single name you stage into Apple
   slices. The generator has emitted it under more than one name across
   releases.
6. Compare or copy **every** generated file, not only the Kotlin and Swift
   sources. The C header and the modulemap are part of the contract too.
7. Remove the temporary directories on both the success and the failure path.

### Files under the contract

```text
<kotlin module>/.../uniffi/<crate_name>/<crate_name>.kt
<swift package>/.../Sources/<Bindings target>/<crate_name>.swift
<swift package>/.../Sources/<crate_name>FFI/<crate_name>FFI.h
<swift package>/.../Sources/<crate_name>FFI/module.modulemap
```

All four are generated. All four are checked in. None are hand-edited.

---

## CI gate

Run `--check` in the Rust lane, not in the Android or iOS lane. Reasons:

- It needs only the host toolchain. No NDK, no Xcode, no emulator.
- It is the fastest lane, so the feedback arrives first.
- It fails for a Rust-side reason, so the failure lands on the right lane.

Wire it next to `cargo clippy` and `cargo test`. The gate must block the merge,
not warn.

The gate covers drift between the Rust source and the checked-in bindings. It
does **not** cover a stale prebuilt artifact on a developer machine. Add a clean
rebuild to the release job for that.

---

## Reviewing an FFI change

Work through this list on any diff that touches the FFI crate:

1. **Are the generated files in the same commit?** If the Rust diff touches an
   exported item and no generated file changed, either the change is not
   exported or the author skipped regeneration. Find out which.
2. **Classify the change** against the semver table in `SKILL.md`. State the
   class in the review, do not assume it.
3. **Record fields**: did any exported record gain or lose a field? That is the
   checksum-blind case. A new required field is source-breaking because it adds
   a generated constructor parameter. Accept an additive classification only
   when every target generates a supported default and an old call compiles.
   Confirm the library and bindings ship together.
4. **Error variants**: a new, removed, or renamed variant is breaking. Check
   that every consumer's exhaustive match or switch was updated.
5. **Adapter arms**: confirm the consumer-side adapter still handles every
   variant explicitly. A wildcard arm in the adapter turns a drift into silent
   behaviour, which is the failure mode this whole discipline exists to
   prevent.
6. **Artifact names**: a package rename changes the `.so` name and the loader
   lookup. Treat it as breaking.
7. **No hand edits** in the generated files. Diff them against a fresh
   regeneration if anything looks manual.

---

## Upgrading uniffi

A uniffi minor bump changes generated code and can change the checksum
algorithm. Handle it as one atomic change:

1. Read the uniffi CHANGELOG for every version you skip, not only the target
   version. Breaking changes are documented per minor release.
2. Bump the version once, at the workspace level. Let `Cargo.lock` freeze the
   patch.
3. Regenerate with `--write`. Because the generator is built from the same
   crate, it upgrades with the runtime automatically - there is no second
   version to bump and no globally installed binary to remember.
4. Review the generated diff. A uniffi bump usually rewrites large parts of the
   generated files; read enough of it to confirm the exported API did not shift.
5. Fix the consumer-side adapters that no longer compile.
6. Rebuild both native artifacts and run the on-device smoke tests. A checksum
   algorithm change fails at load, so a compile-only check proves nothing.

Never bump uniffi in the same commit as an API change. When the load then fails,
you cannot tell which half caused it.

---

## Coordinating a breaking change

When the semver table says breaking:

1. Land the Rust change and the regenerated bindings together.
2. Land the consumer adapter updates in the same change if the code lives in one
   repository. If it does not, publish the new artifact version first and update
   consumers after.
3. Never keep a compatibility shim in the generated layer. Put it in the adapter
   layer, where you own the code and can delete it later.
4. Delete the shim on a schedule. An adapter that carries three generations of
   compatibility is harder to reason about than the breaking change was.
