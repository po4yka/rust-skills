# Swift consumer test

The Swift consumer test is the only check that proves the cross-language
lifetime of the boundary. Keep it outside the generated artifact directory. It
uses the same import path as the application and runs against the real release
library or XCFramework, not a Cargo target file.

## Required operations

- Import the Clang module.
- Create and release every handle kind.
- Pass empty and non-empty `Data`.
- Receive empty and non-empty Rust-owned buffers, then release them.
- Map one known error code and one unknown error code.
- Receive a callback from a Rust-created thread.
- Cancel during a callback and during idle work.
- Drop the Swift owner while work runs.
- Assert that the context release occurs once and that no later callback
  arrives.

## What each sanitizer covers

- The Xcode sanitizers instrument only the Swift, C, and Objective-C code that
  they compile. ASan checks no Rust memory access, but it still catches a
  double free or an invalid free on the Rust side. The `rust-debugging` skill,
  when it is installed, owns the details; without it, symbolicate the report
  with `atos` or `llvm-symbolizer`.
- Miri sees only Rust.
- When unsafe boundary code changes, also run a host ASan build of the Rust
  tests with the `rust-sanitizers-miri` flags. Without that skill, run
  `RUSTFLAGS=-Zsanitizer=address cargo +nightly test --target <host-triple>`.
