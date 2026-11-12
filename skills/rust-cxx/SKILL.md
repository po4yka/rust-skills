---
name: rust-cxx
description: Use when writing, reviewing, or fixing a cxx::bridge module for safe Rust and C++ interop with the cxx crate and cxx-build. Triggers on extern "C++", extern "Rust", UniquePtr, SharedPtr, CxxString, CxxVector, Pin<&mut T> on a C++ method, cxx::Exception, rust::Error, std::terminate after a C++ throw, error[cxxbridge], a missing bridge header, or a link error on a cxxbridge1 symbol. Also covers the choice of cxx, bindgen, or autocxx. Not for a C library, a *-sys crate, or linker search order; use rust-native-linking.
license: BSD-3-Clause
---

# Rust cxx

cxx checks both sides of the boundary. The `#[cxx::bridge]` macro writes the
Rust side. `cxx_build` in `build.rs` writes the C++ side, with static
assertions that each declared signature matches the header, and compiles it.
A signature mismatch fails the build script. A missing C++ definition fails
only the link, and only for a function that the linked artifact reaches
([Verify](#verify)). The facts below are for cxx 1.0.205 (MSRV 1.88).

## Gotchas

- `cxx_build` prints `cargo:rerun-if-changed` for the bridge `.rs` file. Cargo
  then stops its package-wide scan, so an edited `.cc` or `.h` file with no
  rule of its own is not recompiled, and the old object links silently.
- A C++ exception that leaves an `extern "C++"` function declared without
  `Result` calls `std::terminate` (`terminate called after throwing an instance
  of ...`, SIGABRT).
- A Rust panic in any `extern "Rust"` function aborts, with or without
  `Result`: `panic in ffi function <path>, aborting.`
- `UniquePtr::pin_mut` and `Deref` panic on a null pointer. A C++ factory that
  can return `nullptr` needs an `is_null()` check.
- An opaque C++ type has no `Send` or `Sync` impl. Add `unsafe impl Send for
  ffi::T {}` only when the C++ class is thread-safe, with the reason above it.
- A shared enum is a `#[repr(transparent)]` struct with associated constants,
  because C++ can hold any value of the base integer. Every `match` on it needs
  a `_` arm (E0004 without it).

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `undefined symbol: ns$cxxbridge1$205$name` | `cxx_build` did not run on this bridge file, or did not compile its output | List every file that holds a bridge in `cxx_build::bridges([..])`, and call `.compile(..)` |
| `undefined symbol: ns::name(...)` with a demangled C++ signature | The C++ definition is not compiled into the archive | Add the `.cc` file with `.file(..)` on the same `cc::Build` |
| `fatal error: <path>.h: No such file or directory` in `main.rs.cc` | `include!` path does not start with the crate name or `CFG.include_prefix` | Write `include!("<package-name>/include/x.h")`, relative to the manifest directory |
| `invalid use of incomplete type 'const struct ns::Config'`, or a Rust function `was not declared` | The `.cc` file does not include the generated header | Add `#include "<package-name>/src/<file>.rs.h"` |
| `cannot convert 'int32_t (ns::T::*)() const' to 'int64_t (ns::T::*)() const'` | The bridge signature differs from the C++ declaration | Make the Rust declaration match the header exactly |
| `error[cxxbridge]: mutable reference to opaque C++ type requires a pin` | `&mut T` for an opaque C++ type | Use `self: Pin<&mut T>` |
| `error[cxxbridge]: passing opaque C++ type by value is not supported` | A C++ class passed or returned by value | Pass `&T`, `Pin<&mut T>`, `UniquePtr<T>`, or `SharedPtr<T>` |
| `error[cxxbridge]: block must be declared unsafe extern "C++"` | A safe function in a plain `extern "C++"` block | Write `unsafe extern "C++"` and audit each signature, or mark the function `unsafe fn` |
| E0507 `cannot move out of dereference of UniquePtr<T>` | Rust tried to move a C++ object | Keep it behind the pointer; Rust cannot run a C++ move constructor |
| `terminate called after throwing an instance of ...` | A throw crossed a function without `Result` | Declare `-> Result<T>` in the bridge |
| `panic in ffi function ..., aborting.` | A panic in an `extern "Rust"` function | Return `Result` with an error, and keep panics out of the export |
| C++ edit has no effect | No `rerun-if-changed` rule for that file | Add one rule per `.cc` and `.h` file |
| Link fails on a mismatched `$cxxbridge1$NNN$` number in a non-Cargo build | `cxxbridge-cmd` and `cxx` are different releases | Pin `cxxbridge-cmd` to the exact `cxx` version |

Cargo keeps the two versions equal: cxx 1.0.205 declares `cxx-build = "=1.0.205"`
under `cfg(any())`, so a mismatched pin fails resolution. The patch number is
in every bridge symbol.

## Choose the tool

| Situation | Use |
|-----------|-----|
| A C API, or C++ behind an `extern "C"` header | `bindgen` (the `rust-native-linking` skill, when it is installed; else `bindgen::Builder::default().header(..)` in `build.rs` and an `unsafe` wrapper) |
| A small or medium C++ surface that a team designs for Rust: classes, `std::string`, `std::vector`, `std::unique_ptr`, exceptions | cxx |
| A large existing C++ header set that nobody will wrap by hand | autocxx 0.30.0: `include_cpp! { #include "x.h" generate!("ns::T") }` generates cxx bindings from the headers |
| Rust exposes an API to C++ only | cxx with `extern "Rust"` |

cxx binds only the standard templates it names (`UniquePtr`, `SharedPtr`,
`WeakPtr`, `CxxVector`, `CxxString`), no by-value C++ class, and no `async`
function (not implemented in cxx 1.0.205). Write a C++ shim with a concrete
signature for each other case.

## Write the bridge

```rust
#[cxx::bridge(namespace = "engine")]
mod ffi {
    // Shared types: both languages see the fields, and pass them by value.
    struct Config {
        name: String,
        mode: Mode,
    }

    enum Mode {
        Fast,
        Safe,
    }

    extern "Rust" {
        type Journal;
        fn record(self: &mut Journal, line: &str);
        fn check_level(level: i32) -> Result<i32>;
    }

    unsafe extern "C++" {
        include!("demo/include/engine.h");

        type Engine;

        fn new_engine(config: &Config) -> UniquePtr<Engine>;
        fn push(self: Pin<&mut Engine>, value: i32);
        fn total(&self) -> i32;
        fn name(&self) -> &CxxString;
        fn parse_level(text: &str) -> Result<i32>;
        fn drain(self: Pin<&mut Engine>, journal: &mut Journal);
    }
}

pub struct Journal {
    lines: Vec<String>,
}

impl Journal {
    fn record(&mut self, line: &str) {
        self.lines.push(line.to_owned());
    }
}

// The bridge names only the Ok type; any error type with Display works here.
fn check_level(level: i32) -> Result<i32, String> {
    if (0..=9).contains(&level) {
        Ok(level)
    } else {
        Err(format!("level {level} is out of range"))
    }
}

pub fn run(journal: &mut Journal) -> Result<i32, cxx::Exception> {
    let config = ffi::Config { name: "main".to_owned(), mode: ffi::Mode::Safe };
    let mut engine = ffi::new_engine(&config);
    if engine.is_null() {
        return Ok(0);
    }
    engine.pin_mut().push(3);
    let level = ffi::parse_level("7")?;
    let total = engine.total() + level;
    engine.pin_mut().drain(journal);
    Ok(total)
}
```

Rules:

- Declare the C++ side in a header that the bridge names with `include!`. The
  `.cc` file includes that header and the generated `<file>.rs.h`, which holds
  the shared types and the `extern "Rust"` declarations.
- A `self` parameter makes a member function: `&self` is `const`, and
  `self: Pin<&mut T>` is non-`const`. Use `#[Self = "T"]` for a static member.
- `unsafe extern "C++"` is a claim that every function without `unsafe fn` is
  safe to call. cxx checks types, not preconditions: mark a function that takes
  an index, a raw pointer, or a lifetime rule `unsafe fn`.
- Give `Result<T>` to every `extern "C++"` function that can throw. The error is
  a `cxx::Exception`; `what()` returns the C++ message. A `Result` from an
  `extern "Rust"` function throws `rust::Error` in C++, with the `Display` text.
- Pass text as `&str` or `String` when Rust owns it, and `&CxxString` when C++
  owns it. `CxxString::to_str()` validates UTF-8; use `to_string_lossy()` only
  for logs.

Read [references/bridge-types.md](references/bridge-types.md) when you map a
type that the example does not show: `CxxVector`, `SharedPtr` mutation, a
`CxxString` built in Rust, a type shared by two bridges, a bindgen type, a
borrowed C++ type, or thread-safety impls.

## Build with cxx-build

```rust,ignore
// build.rs. Cargo.toml: cxx = "1.0.205" in [dependencies],
// cxx-build = "1.0.205" in [build-dependencies].
fn main() {
    cxx_build::bridge("src/lib.rs")
        .file("src/engine.cc")
        .std("c++17")
        .compile("demo-bridge");

    println!("cargo::rerun-if-changed=src/engine.cc");
    println!("cargo::rerun-if-changed=include/engine.h");
}
```

- `bridge` returns a `cc::Build`: add every C++ source with `.file`, then call
  `.compile` once. Use `cxx_build::bridges([..])` for more than one bridge file.
- `cxx_build` does not set a language standard. Set `.std(..)` to the standard
  the C++ code needs, or the compiler default decides.
- Include paths start with the package `name` from `Cargo.toml`, hyphens kept:
  `include/engine.h` in package `demo` is `"demo/include/engine.h"`. Set
  `cxx_build::CFG.include_prefix` before `bridge` to change the prefix.
- `cxx_build` links the C++ standard library through the `link-cplusplus`
  crate. Do not add `rustc-link-lib=stdc++`.

Read [references/build-and-headers.md](references/build-and-headers.md) when a
downstream crate includes the headers of this crate, a header includes a system or
dependency header, or a non-Cargo build (CMake, Bazel, Buck) generates the C++
side. For a native C++ library that the bridge calls, the `rust-native-linking`
skill, when it is installed, owns discovery, link order, and runtime loading;
else emit `cargo::rustc-link-lib=static=<name>` after `cargo::rustc-link-search`
in the same `build.rs`.

## Verify

| Check | Command | Proves | Does not prove |
|-------|---------|--------|----------------|
| Bridge syntax and Rust types | `cargo check --locked` | The macro accepts the bridge; the build script ran and the C++ side compiled against the header | Linking: `cargo check` links nothing |
| Every C++ definition exists | `cargo test --locked` with a test that calls each `extern "C++"` function once | The symbols link and the calls return | Functions that no test reaches: the linker drops them, and an unlinked one still passes |
| Exceptions map to `Err` | A test that makes each fallible C++ function throw and asserts `Err` | `Result` is declared where C++ throws | Throws from functions not under test |
| C++ edits rebuild | Touch each `.cc` and `.h` file, run `cargo build -vv`, and look for a `Dirty <package>` line that names the file | The `rerun-if-changed` rule of each file you touched | A file you did not touch |
| Memory safety across the boundary | `RUSTFLAGS=-Zsanitizer=address CXXFLAGS=-fsanitize=address cargo +nightly test --target x86_64-unknown-linux-gnu` | ASan reports a use-after-free or overflow in either language, on the paths that run (nightly 2026-11-09, g++ 13) | Paths no test runs, and data races |

Run the call-every-function test after any bridge change. A green `cargo
check` is not evidence of a working binding. The `rust-sanitizers-miri` skill,
when it is installed, owns the sanitizer setup; else pass the same sanitizer to
both compilers, as in `-Zsanitizer=address` with `-fsanitize=address`. Miri
cannot run C++ code.
