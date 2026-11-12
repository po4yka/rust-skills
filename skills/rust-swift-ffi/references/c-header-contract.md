# C header contract

Detail for the C ABI and header rules in `SKILL.md`: the boundary shapes,
scalar types, the Swift import of C enums, header generation and review, and
the modulemap.

## Boundary shapes

| Rust meaning | C ABI shape | Swift wrapper |
| --- | --- | --- |
| Stateful object | Pointer to an incomplete handle type | `final class` that releases once |
| Borrowed bytes | `const uint8_t *` plus `size_t` | `Data.withUnsafeBytes` |
| Rust-owned bytes | Pointer, length, capacity, and one Rust free function | Copy to `Data`, then free |
| Optional pointer | Nullable pointer with a documented null rule | Swift optional |
| Fallible call | Stable status code plus explicit output | `throws` |
| Long job | Opaque job handle plus non-blocking cancel | Task or stream wrapper |
| Callback state | `void *context` plus callback and release functions | Retained callback box |

Prefer caller-owned output for small fixed-size values. Use a size query plus
a caller buffer only when the second call can report a changed size and retry,
or when the Rust object holds a stable snapshot. Otherwise the size can change
between the two calls. Use the Rust-owned `rs_buffer_t` from `SKILL.md` for
other variable output.

## Scalar types

Use fixed-width integers for persistent values and serialized fields. Use
`size_t` only for the size of memory in the current process. Represent Boolean
values as `uint8_t` with `0` and `1` unless the header and both compilers agree
on a C `_Bool` contract. Write C `void` as no Rust return type. `-> c_void`
returns a Rust enum, and the `c_void_returns` lint warns on it since Rust 1.98.

## C enums in Swift

Swift 6.4 imports the three C enum forms differently:

| C form | Swift import | Value from a newer library |
| --- | --- | --- |
| Plain C enum | `RawRepresentable` struct | Any raw value is accepted |
| `enum_extensibility(open)` | Non-frozen enum | `switch` requires `@unknown default` |
| `enum_extensibility(closed)` | `@frozen` enum | Exhaustive `switch` has no case for it |

## Header generation and review

Generate the header with the pinned `cbindgen` version when Rust declarations
are the source of truth. Check the generated header into the SDK only when the
release process verifies that regeneration produces no diff. Restrict
generation to the boundary module, so that no internal Rust type reaches the
header.

Review the header as C, not as Rust source:

- Every public symbol has a stable prefix.
- Every handle is an incomplete type.
- Every integer has the intended width.
- Every pointer carries a nullability qualifier (`_Nonnull`, `_Nullable`), and a comment
  states its ownership.
- Every returned allocation names its matching release function.
- No Cargo package path or private type name appears.

Compile the header the way Swift reads it: included from a translation unit, not as the main
file.

```bash
printf '#include "<header>"\n' | xcrun clang -fsyntax-only -Werror -I <header-dir> -x c -
printf '#include "<header>"\n' | xcrun clang -fsyntax-only -Werror -I <header-dir> -x objective-c -
```

`clang -fsyntax-only -Werror -x c <header>` is the wrong check in both directions (clang 18):

- It rejects a valid header that uses `#pragma once`, which cbindgen can emit:
  `#pragma once in main file [-Werror,-Wpragma-once-outside-header]`.
- It accepts a header that mixes a `_Nonnull` pointer with an unannotated one. Clang reports
  `-Wnullability-completeness` only for an included header: `pointer is missing a nullability
  type specifier (_Nonnull, _Nullable, or _Null_unspecified)`. Swift then imports the
  unannotated pointer as an implicitly unwrapped optional.

cbindgen 0.29.4 writes a qualifier only where the Rust type proves one: with
`[ptr] non_null_attribute = "_Nonnull"`, a `&T` parameter becomes `const struct H *_Nonnull`,
and a raw `*mut H` stays bare. Its header therefore mixes annotated and bare pointers and fails
the include check. Do not wrap the header in `#pragma clang assume_nonnull`: that marks every
bare pointer non-null, including one the Rust side accepts as null. Write the qualifiers in a
reviewed header and regenerate the cbindgen output only to diff the declarations against it,
or add `_Nullable` to the generated file in a checked post-processing step.

## Modulemap

Put a Clang modulemap next to the public header:

```text
module RustCore {
    header "rust_core.h"
    export *
}
```

Swift imports the module name. Do not add a bridging header with a second
copy of the declarations.
