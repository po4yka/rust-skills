# What `#![forbid(unsafe_code)]` catches

The rule and the governance steps are in [SKILL.md](../SKILL.md). This file lists what the lint
reports for each source of `unsafe`, and why a macro from a dependency escapes it.

## Result by source of `unsafe`

The lint checks the crate's own source text. It does not check the code the crate compiles to.
Measured on rustc 1.98.1, edition 2024, and on 1.88.0 and 1.97.1 for the attribute rows:

| Where the `unsafe` comes from | Result under `#![forbid(unsafe_code)]` |
| --- | --- |
| A hand-written `unsafe { ... }` block, or an `unsafe extern` block | ``error: usage of an `unsafe` block``, or ``usage of an `unsafe extern` block``. The build fails. |
| `#[unsafe(no_mangle)]`, `#[unsafe(export_name)]`, or `#[unsafe(link_section)]` in the crate | One error per attribute on every edition-2024 toolchain. Since 1.98: ``usage of the unsafe `#[no_mangle]` attribute``. Before 1.98: ``declaration of a `no_mangle` function``, and the same `declaration of ...` form for the other two. |
| Other unsafe attributes, such as `#[unsafe(naked)]` | Rejected only since 1.98: ``usage of the unsafe `#[naked]` attribute``. 1.88 to 1.97 build it with no diagnostic. |
| A `macro_rules!` defined in the same crate | The same block error at the macro body, with the call site marked `in this macro invocation` |
| A `macro_rules!` or a proc macro from a dependency crate | No diagnostic. The unsafe block runs, and an injected `#[unsafe(no_mangle)]` export builds. |

```rust,compile_fail
#![forbid(unsafe_code)]

// Rejected on every edition-2024 toolchain. Since 1.98 the message is
// "usage of the unsafe `#[no_mangle]` attribute"; before 1.98 it was
// "declaration of a `no_mangle` function".
#[unsafe(no_mangle)]
pub extern "C" fn exported() {}
```

A local `#[allow(unsafe_code)]` under the crate-level `forbid` is
`error[E0453]: allow(unsafe_code) incompatible with previous forbid`.

## Why a dependency macro escapes the lint

rustc suppresses lints on tokens that an external macro expanded. The boundary is the crate that
wrote the macro, not whether the macro is procedural. `cargo clippy -- -D unsafe_code` is silent
on the same code. No dependency filter closes the gap: `cargo tree -p <crate> | rg proc-macro`
lists nothing for a crate that exports a plain `macro_rules!`. Only the expansion shows every
case. Use the `-Zunpretty=expanded` command from the inventory in [SKILL.md](../SKILL.md).
