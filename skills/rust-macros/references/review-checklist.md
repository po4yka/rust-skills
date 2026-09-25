# Macro review checklist

Each line restates a rule from `SKILL.md`. Use it to review a finished macro change.

- Every `macro_rules!` definition appears above every use in its file.
- `#[macro_export]` appears only on a macro that is part of the public API.
- Every emitted path starts with `$crate::`, `::core::`, or, from a derive, `::facade::`. `::std::` and `::alloc::` appear only when no `#![no_std]` caller is supported.
- A dependency of the macro crate is reached through a `$crate::__private` re-export, not through `::dep_name::`.
- Every generated item name comes from a metavariable, or sits in an anonymous `const _: () = { ... };`.
- No metavariable expands inside an `unsafe` block.
- Separators respect the follow set of the fragment before them.
- No arm used in expression position ends its body with `;`.
- Every repetition that spans lines ends with `$(,)?`.
- The procedural macro crate uses the syn major the tree already builds, or syn 3.
- A rejected input returns a `syn::Error`, and no code path panics.
- Every helper attribute appears in `attributes(...)`, and none shares a built-in attribute name.
- The author reads the expansion once with `-Zunpretty=expanded` or `cargo expand`.
- Each claim in the verification table of `SKILL.md` has a passing check.
