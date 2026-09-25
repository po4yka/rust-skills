# Binding compatibility: checksums, the regeneration gate, and review

Detail behind the versioning rules in `SKILL.md`.

Contents:

- What the checksum protects, and what it does not
- Regeneration script contract
- CI gate
- Reviewing an FFI change
- Upgrading uniffi
- Coordinating a breaking change

---

## What the checksum protects, and what it does not

UniFFI computes one API checksum per exported function, constructor, and
method. The generated Kotlin and Swift embed the expected values and compare
them against the loaded library at run time. When that comparison runs depends
on the language; see the checksum section in `SKILL.md`.

Treat that as the second line of defence, not the first:

| Property | Value |
|----------|-------|
| When it fires (Swift) | At the first call into the library, not at compile time |
| When it fires (Kotlin 0.30.0–0.32.2) | Only inside `uniffiEnsureInitialized()`. A single-crate binding never calls it, so the consumer must call it at startup |
| How it fails | Kotlin: `ExceptionInInitializerError` caused by `RuntimeException`, then `NoClassDefFoundError` on later calls; Swift: `fatalError`. No fallback |
| What it covers | The signatures of exported functions, constructors, and methods |
| What it does **not** cover | Record fields and enum variants. A type enters a checksum only by its name (uniffi-rs #1789) |

The uncovered case is dangerous in both skew directions. New bindings with a
stale library expect a field that is absent and exhaust the `RustBuffer`. A new
library with stale bindings emits an extra field. The old reader can reject or
ignore trailing data, depending on the generated reader and UniFFI version.
Plausible but wrong values need a layout change that keeps a compatible encoded
shape, such as a reorder of two fields of the same type. Do not claim that
every appended field silently shifts old values.

No run-time check covers every version and skew direction. The portable defence
is process: the regenerated bindings and the rebuilt library land in the same
commit.

Do not put every skew failure under the record checksum gap:

| Native library or scaffolding | Consumer bindings | Expected failure |
|-------------------------------|-------------------|------------------|
| Same generated revision | Same revision | No skew failure |
| Changed checksummed export | Stale revision | Hard checksum mismatch: Swift at the first call; Kotlin only after `uniffiEnsureInitialized()`, otherwise no error |
| Stale library without an added record field | New bindings with that field | `RustBuffer` exhaustion or deserialization error |
| New library with an added record field | Stale bindings without that field | Trailing data is rejected or ignored; behavior depends on generated reader and version |
| Type-compatible field reorder on either side | Opposite stale layout | Values can go to the wrong fields without a checksum error |
| One generated interface side is stale at link time | Newer other side | Undefined symbols or linker failure; uniffi-rs #333 asks for clearer diagnostics |
| Same revision, UniFFI 0.30.0–0.32.0 | Same revision, Kotlin on an ARM32 device (0.30.0–0.31.1) or an `arm64-v8a` device (0.31.2–0.32.0) | Checksum mismatch from a UniFFI defect, not from skew (uniffi-rs #2740, #2939, #2935). Upgrade to 0.32.1 or later |

---

## Regeneration script contract

Write one script, check it in, and make it the only supported way to
regenerate. Hand-run `cargo run ... uniffi-bindgen` invocations drift between
developers.

### Modes

| Mode | Behavior | Exit code |
|------|----------|-----------|
| `--check` (default) | Generate into a temporary directory, `diff` against the checked-in files, print the diff | Non-zero on any difference |
| `--write` | Generate and overwrite the checked-in files | Non-zero only on a build or generation failure |

Make `--check` the default. A script that writes by default eventually runs in
CI by accident and hides the drift it exists to catch.

### Steps the script must perform

1. Build the host library with `--locked`. Fail if `Cargo.lock` would change.
2. Find the host library: try `lib<crate_name>.dylib`, `lib<crate_name>.so`,
   and `<crate_name>.dll`, and require exactly one match. Do not branch on the
   operating system name or assume that every library has a `lib` prefix.
   When the caller passes a library path, skip steps 1 and 2 and use it.
3. Run the in-crate generator once with `--language kotlin --language swift
   --no-format --out-dir <tmp>`. Do not pass `--library`; it has no effect since
   UniFFI 0.31. `--no-format` keeps the output independent of the `ktlint` and
   `swift-format` installs on the machine.
4. Normalize the output: strip trailing whitespace, use LF line endings, and
   enforce one final newline. Editor and Git settings can change checked-in
   files; without this step the `--check` gate fails on invisible characters.
5. Rename `<crate_name>FFI.modulemap` to `module.modulemap`, the name that you
   stage into Apple slices. `uniffi-bindgen generate` always writes
   `<ffi_module_filename>.modulemap`.
6. Compare or copy **every** generated file, not only the Kotlin and Swift
   sources. The C header and the modulemap are part of the contract.
7. Remove the temporary directory on both the success and the failure path.

For the target-independence check, run the script in `--check` mode with each
shipping target library (`.so` or `.a`) as its input, so that steps 3–7 all
run. Step 3 alone always differs from the checked-in files, on whitespace and
on the modulemap name. Pass the unstripped `target/<triple>/<profile>/` output:
the generator reads ELF metadata from the symbol table only, so a stripped
`.so` gives no metadata.

### Files under the contract

```text
<kotlin module>/.../uniffi/<crate_name>/<crate_name>.kt
<swift package>/Sources/<Bindings target>/<crate_name>.swift
<swift package>/ffi-headers/<crate_name>FFI.h
<swift package>/ffi-headers/module.modulemap
```

All four are generated and checked in. None are hand-edited. Keep the header
and modulemap outside `Sources/`. They are staged into the headers directory of
each XCFramework slice. A directory under `Sources/` invites a second SwiftPM C
target with the same module name.

---

## CI gate

Run `--check` in the Rust lane, not in the Android or iOS lane:

- It needs only the host toolchain. No NDK, no Xcode, no emulator.
- It is the fastest lane, so the feedback arrives first.
- It fails for a Rust-side reason, so the failure lands on the right lane.

Put it next to `cargo clippy` and `cargo test`. The gate must block the merge,
not warn.

The gate covers drift between the Rust source and the checked-in bindings. It
does **not** cover a stale prebuilt artifact on a developer machine. Add a
clean rebuild to the release job for that.

---

## Reviewing an FFI change

Use this list for a diff that touches the FFI crate:

1. **Are the generated files in the same commit?** If the Rust diff touches an
   exported item and no generated file changed, either the change is not
   exported or the author skipped regeneration. Find out which.
2. **Classify the change** against the table in `SKILL.md`. State the class in
   the review. Do not assume it.
3. **Record fields.** Did an exported record gain or lose a field? That is the
   checksum-blind case. A new field without a generated default adds a
   constructor parameter and breaks source. Accept an additive class only when
   every target language generates a default and an old call compiles. Confirm
   that the library and the bindings ship together.
4. **Enum and error variants.** A new, removed, or renamed variant breaks every
   exhaustive consumer `when` or `switch`. Check that each consumer was updated.
5. **Adapter arms.** Confirm that the consumer adapter still handles every
   variant explicitly. A wildcard arm turns a drift into silent behavior.
6. **Artifact names.** A package rename changes the `.so` name and the loader
   lookup. Treat it as breaking.
7. **No hand edits** in the generated files. Diff them against a fresh
   regeneration if anything looks manual.

---

## Upgrading uniffi

A uniffi bump changes generated code and can change checksums. UniFFI 0.31.0,
for example, removed the self type from method checksums. Handle the bump as
one atomic change:

1. Read the uniffi CHANGELOG for every version you skip, patch releases
   included. A patch release can fix one device checksum failure and add
   another: 0.31.2 fixed ARM32 and broke `arm64-v8a`, and 0.32.1 fixed
   `arm64-v8a`.
2. Bump the version once, at the workspace root. Let `Cargo.lock` freeze the
   patch.
3. If you pass `--config`, convert the file to the global config format when
   you cross 0.32.0. The generator ignores an old flat file with only a
   warning, so settings such as a package name or renames drop out of the
   generated code.
4. Regenerate with `--write`. The generator is built from the same crate, so
   it upgrades with the runtime. There is no second version to bump.
5. Review the generated diff. A bump rewrites large parts of the generated
   files. Read enough of it to confirm that the exported API did not shift.
   Some bumps change generated signatures for the same Rust code; for example,
   0.32.0 maps a `&[u8]` argument to a direct `java.nio.ByteBuffer` in Kotlin.
6. Fix the consumer adapters that no longer compile.
7. Rebuild both native artifacts and run the generated-binding call on a device
   or emulator for each shipping ABI family, and on a simulator. On Kotlin,
   call `uniffiEnsureInitialized()` first. A checksum change fails only at run
   time, so a compile-only check proves nothing.

Do not bump uniffi in the same commit as an API change. When the load then
fails, you cannot tell which half caused it.

---

## Coordinating a breaking change

When the classification table says breaking:

1. Land the Rust change and the regenerated bindings together.
2. Land the consumer adapter updates in the same change if the code lives in one
   repository. If it does not, publish the new artifact version first and update
   the consumers after.
3. Do not keep a compatibility shim in the generated layer. Put it in the
   adapter layer, where you own the code and can delete it later.
