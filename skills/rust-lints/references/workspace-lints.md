# `[workspace.lints]` templates

Two levels of the same table: the strict target, and the baseline an existing workspace
can adopt today. Both belong in the workspace root manifest, and every member crate
inherits them with `[lints] workspace = true`.

This is the target policy for a workspace that wants machine-generated code
rejected early. Start here for a new workspace. For an existing workspace with
a large backlog, start from the [pragmatic baseline](#pragmatic-baseline-for-an-existing-workspace)
and climb.

```toml
[workspace.lints.rust]
unsafe_op_in_unsafe_fn       = "deny"   # force an explicit `unsafe { .. }` inside an unsafe fn
missing_docs                 = "warn"
unused_lifetimes             = "warn"
unreachable_pub              = "warn"
elided_lifetimes_in_paths    = "warn"
let_underscore_drop          = "deny"   # catches `let _ = guard;` swallowing Drop
unconditional_recursion      = "deny"   # warn by default; catches a body that calls only itself
non_ascii_idents             = "deny"
trivial_numeric_casts        = "warn"
unused_must_use              = "deny"
# unsafe_code              = "forbid"   # set per crate, not workspace-wide (see below)

[workspace.lints.clippy]
# Group activations. priority = -1 lowers the group below the individual
# lints below it, so a single lint can override its own group.
all                          = { level = "deny",  priority = -1 }
pedantic                     = { level = "warn",  priority = -1 }
nursery                      = { level = "warn",  priority = -1 }
cargo                        = { level = "warn",  priority = -1 }

# Highest-value promotions for machine-generated code.
mem_forget                   = "deny"   # forget on a Drop type is data loss
undocumented_unsafe_blocks   = "deny"   # every unsafe block needs a // SAFETY: comment
multiple_unsafe_ops_per_block = "deny" # one SAFETY: comment per operation, not per block
missing_safety_doc           = "deny"   # a # Safety section on every pub unsafe fn
missing_panics_doc           = "warn"
missing_errors_doc           = "warn"
unwrap_used                  = "warn"   # promote to deny per crate when the backlog is clear
expect_used                  = "warn"
panic                        = "warn"
todo                         = "warn"
unimplemented                = "warn"
dbg_macro                    = "deny"
print_stdout                 = "warn"
exit                         = "deny"
large_stack_arrays           = "warn"
large_stack_frames           = "warn"
large_futures                = "warn"
large_enum_variant           = "warn"   # fires on the size DIFFERENCE between the two largest variants
result_large_err             = "warn"   # warn by default; fires when the Err variant reaches 128 bytes
exhaustive_enums             = "warn"   # require #[non_exhaustive] on a pub enum
exhaustive_structs           = "warn"
inefficient_to_string        = "warn"
disallowed_methods           = "deny"
disallowed_types             = "deny"
str_to_string                = "warn"
implicit_clone               = "warn"
assigning_clones             = "warn"   # pedantic: `a = b.clone()` becomes `a.clone_from(&b)`
redundant_clone              = "warn"   # nursery
or_fun_call                  = "warn"   # nursery: `ok_or(build())` becomes `ok_or_else(build)`
unnecessary_lazy_evaluations = "warn"   # style: the reverse error, a closure that should stay eager
needless_collect             = "warn"   # nursery: return `impl Iterator<Item = T>`, not `Vec<T>`
needless_pass_by_value       = "warn"
ptr_arg                      = "warn"   # style, NOT perf: `&Vec<T>` becomes `&[T]`
ref_option                   = "warn"
trivially_copy_pass_by_ref   = "warn"
redundant_closure_for_method_calls = "warn"
collapsible_if               = "warn"
uninlined_format_args        = "warn"

# Restriction-class lints with a high signal-to-noise ratio.
allow_attributes             = "warn"
allow_attributes_without_reason = "warn"   # reject a bare #[allow(..)] with no justification
indexing_slicing             = "warn"   # prefer .get() over buf[i] on data read from I/O
integer_division             = "warn"
arithmetic_side_effects      = "warn"   # catches unchecked integer arithmetic
modulo_arithmetic            = "warn"
unwrap_in_result             = "warn"

[workspace.lints.rustdoc]
broken_intra_doc_links       = "deny"
private_intra_doc_links      = "warn"
missing_crate_level_docs     = "warn"
bare_urls                    = "warn"
```

Notes on this set:

- `clippy::string_to_string` was removed in clippy 1.86. `implicit_clone`
  covers the same ground. Do not re-add it.
- Add the async lints only when the workspace actually runs an async runtime.
  A synchronous, compute-bound workspace gains nothing from
  `await_holding_lock`. See `references/lint-catalog.md`.
- Add the pointer and FFI lints only in a workspace that contains `unsafe`
  pointer work. See `references/lint-catalog.md`.
- `unsafe_code = "forbid"` belongs in each crate's `lib.rs`, not in the
  workspace table. Otherwise the one crate that owns `unsafe` cannot opt out.
- `unconditional_recursion` is warn-by-default, so the strict template must
  promote it. An inherent method that carries a trait method's name resolves
  first, so `fn into_iter(self) -> Owned { self.into_iter() }` inside
  `impl IntoIterator` calls the inherent method and passes review. Delete that
  inherent method in a later cleanup and the same body calls itself. rustc
  still only warns and the binary links. A debug build then dies with `fatal
  runtime error: stack overflow, aborting` and exit code 134. A release build
  is worse: LLVM turns the tail call into an infinite loop, so the process
  hangs with no diagnostic at all.
- Most of the performance lints above are not in the `perf` group.
  `assigning_clones` is `pedantic`; `redundant_clone`, `or_fun_call` and
  `needless_collect` are `nursery`; `ptr_arg` and `unnecessary_lazy_evaluations`
  are `style`. Only `large_enum_variant` and `result_large_err` come from
  `perf`. A config that enables `clippy::perf` alone gets those two and nothing
  else. See `references/lint-catalog.md`.

### Pragmatic baseline for an existing workspace

An existing workspace with thousands of files cannot land the strict set in one
commit. Use group levels first, then cherry-pick the pedantic lints that pay
for themselves:

```toml
[workspace.lints.clippy]
correctness = { level = "deny", priority = -1 }   # almost certainly a bug
suspicious  = { level = "deny", priority = -1 }   # very likely wrong
style       = { level = "warn", priority = -1 }
complexity  = { level = "warn", priority = -1 }
perf        = { level = "warn", priority = -1 }

# Cherry-picked pedantic lints - cheap to fix, high hit rate.
cloned_instead_of_copied            = "warn"
explicit_iter_loop                  = "warn"
explicit_into_iter_loop             = "warn"
implicit_clone                      = "warn"
inefficient_to_string               = "warn"
map_unwrap_or                       = "warn"
redundant_closure_for_method_calls  = "warn"
semicolon_if_nothing_returned       = "warn"
uninlined_format_args               = "warn"
unnested_or_patterns                = "warn"
manual_let_else                     = "warn"
trivially_copy_pass_by_ref          = "warn"
unused_self                         = "warn"
default_trait_access                = "warn"
match_wildcard_for_single_variants  = "warn"

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"
```

This baseline is a starting point, not a destination. Record which strict lints
are still off and why. Then follow [Tighten a lint safely](../SKILL.md#tighten-a-lint-safely).

Write down the level that is actually deployed. A skill or a README that
describes an aspirational level as if it were enforced is worse than no
document: reviewers stop checking what the compiler is not checking either.

