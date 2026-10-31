---
name: rust-swift-ffi
description: Use when designing or reviewing the ownership, threading, or lifecycle contract of a hand-written Swift FFI, where Swift calls Rust through a C ABI without UniFFI. Triggers on an opaque Rust handle in Swift, a Rust-owned buffer returned to Swift, callbacks from Rust threads, @MainActor Rust callback, Unmanaged.passRetained, AsyncStream over a C callback, or SWIFT_DEFAULT_ACTOR_ISOLATION MainActor in the wrapper. Not for UniFFI-generated Swift (use uniffi-boundary) or XCFramework packaging (use rust-ios-build).
license: BSD-3-Clause
---

# Rust Swift FFI

This skill owns the contract between a hand-written C ABI and its Swift
wrapper. Keep the exported C surface small. Keep domain behavior in ordinary
Rust code and idiomatic Swift types outside the boundary.

Route neighboring work to these skills when they are installed:

- `uniffi-boundary` when UniFFI generates the Swift API. Do not keep a second
  hand-written ABI for the same surface.
- `rust-ios-build` for Apple targets, modulemap staging, XCFramework, SwiftPM.
- `rust-native-linking` for `build.rs` and `cbindgen` setup.
- `rust-unsafe` for raw-pointer soundness, layout, and the `unsafe_code` policy.
- `rust-sanitizers-miri` for Miri and sanitizer flags.
- `rust-panic-safety` for the unwind audit and the panic hook.
- `ffi-error-progress-cancel` for a shared mobile error, progress, and
  cancellation model.

## First decide whether a hand-written ABI is necessary

Use UniFFI when Kotlin and Swift consume the same object model, records,
errors, and async operations. Use a hand-written C ABI only when at least one
condition is true:

- The public product is an existing C-compatible SDK.
- The Swift wrapper must preserve a fixed ABI across independent releases.
- The surface uses a C library convention that UniFFI cannot represent.
- The project needs a very small leaf interface and accepts manual ownership.

Do not select a hand-written ABI only to avoid one generator step. The manual
path owns every destructor, callback race, error conversion, and Swift
concurrency annotation.

## Completion evidence

Prove the boundary with the artifact that ships. A Rust unit test, a generated
header, or a clean archive link does not prove that Swift can use the boundary.

| Claim | Check | Run it when |
| --- | --- | --- |
| The header matches the exports | Regenerate with the pinned `cbindgen`, then `git diff --exit-code -- <header>` | An exported item changes |
| Clang accepts the header | `xcrun clang -fsyntax-only -Werror -x c <header>`, then again with `-x objective-c` | The header changes |
| The archive defines each header function | `nm -gU <lib>.a` shows a `T _rs_...` line for every declared function | Before packaging |
| Swift imports and calls the real artifact | The consumer test below, built with the app target's `SWIFT_VERSION`, `SWIFT_DEFAULT_ACTOR_ISOLATION`, and `SWIFT_APPROACHABLE_CONCURRENCY`, and again in Swift 6 language mode | The boundary changes |
| Swift code that Rust reaches is not main-actor code | Review that each declaration that Rust reaches is `nonisolated`. A clean build alone proves nothing, and Swift 5 mode reports even less | A wrapper or callback changes |
| Callbacks and cancellation are race-free | The consumer test under Thread Sanitizer: `swift test --sanitize=thread`, or `xcodebuild test -enableThreadSanitizer YES` | A callback or cancel path changes |
| The Swift use of Rust memory has no memory error | The consumer test under Address Sanitizer: `swift test --sanitize=address`, or `xcodebuild test -enableAddressSanitizer YES`. Miri cannot run this path | A buffer, handle, or release path changes |
| Rust buffer and handle code is sound | `cargo +nightly miri test --locked` (when the `miri` component is installed; otherwise report it as not checked by Miri) with a Rust test callback that dereferences the context pointer | Unsafe boundary code changes |
| Every shipped slice works | A smoke test on each supported Apple slice (`rust-ios-build` owns the lanes) | Before release |

Keep a small Swift consumer test outside the generated artifact directory. It
uses the same import path as the application and runs against the real release
library or XCFramework, not a Cargo target file. It does these operations:

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

The Xcode sanitizers instrument only the Swift, C, and Objective-C code that
they compile. ASan checks no Rust memory access, but it still catches a double
free or an invalid free on the Rust side. The `rust-debugging` skill, when it is
installed, owns the details. Miri sees only Rust. Only the consumer test proves
the cross-language lifetime, for the paths that it runs.
When unsafe boundary code changes, also run a host ASan build of the Rust
tests with the `rust-sanitizers-miri` flags.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Swift imports no functions | Modulemap name, header path, or visibility is wrong | Compile the header with Clang and inspect the packaged modulemap |
| Duplicate or missing symbol | The header and archive came from different builds | Regenerate both from one release build and inspect exported symbols |
| Crash in `deinit` | The pointer was copied or released twice | Hide it in one non-copyable class and consume it once |
| Heap corruption after returning bytes | Swift used its allocator on Rust memory, or Rust rebuilt the `Vec` with the wrong capacity | Copy, then call the matching Rust release function with the unchanged buffer |
| Rust reads freed bytes after a call returns | Rust kept the temporary `withUnsafeBytes` pointer | Copy the bytes before the closure returns |
| Crash after several progress events | The callback used `takeRetainedValue()` | Use `takeUnretainedValue()` and release only in the release callback |
| Crash or corrupt state when an Objective-C API raises in a callback | An `NSException` unwound into an `extern "C"` Rust frame, which is UB | Call the API through an `@try`/`@catch` shim, or keep it out of the callback |
| `main actor-isolated ... can not be referenced from a nonisolated context`, `main actor-isolated default value in a nonisolated context`, `call to main actor-isolated ... in a synchronous nonisolated context`, or a `deinit` Sendable error | The module uses default MainActor isolation | Mark `nonisolated` every type, extension, function, and global that Rust reaches |
| UI hangs while an async wrapper waits on Rust | A `nonisolated` async method runs on the main actor under `nonisolated(nonsending)` | Mark it `@concurrent` |
| Thread Sanitizer reports a race in a context box that compiles clean in Swift 6 | `Unmanaged` hides a non-`Sendable` box | Make the box a `final class` marked `Sendable`, with `let` properties and a `let` lock |
| Trap in `dispatch_assert_queue` on the first callback | `MainActor.assumeIsolated` ran on a Rust thread | Make the box `nonisolated` and hop with `Task { @MainActor in ... }` |
| UI isolation warning or crash | Rust called a main-actor value directly | Copy the event and schedule it with `Task { @MainActor in ... }` |
| Newer library breaks an older app's `switch` | The status is an `enum_extensibility(closed)` C enum, so Swift has no unknown case | Map codes through an unknown case, or use an `int32_t` status or an open enum |
| Owner stays alive after the job | Swift owner, job, and callback form a cycle | Use a weak owner and release the callback at terminal state |
| Callback arrives after cancellation | Cancel was treated as synchronous completion | Stop, drain callbacks, then release the context |
| Cancellation freezes the UI | Cancel or release joins a worker | Make cancel non-blocking and let the worker own its final reference |
| `failed to join thread: Resource deadlock avoided (os error 11)` | Swift dropped the last job reference inside `release_context`, and release joins the worker | Make release non-blocking and call `release_context` with no lock held |
| Progress stream memory grows | `AsyncStream` uses the default `.unbounded` buffer | Use `bufferingPolicy: .bufferingNewest(1)` |
| Error text changes into invalid bytes | String encoding or ownership is implicit | Use owned UTF-8 bytes and one Rust release function |
| App aborts with no Swift error | A Rust panic reached an `extern "C"` boundary | Catch it in the export and return the reserved internal-error code |
| Works in a Rust test but not the app | The test did not consume the packaged module | Compile, link, and call from the Swift consumer test |

## Freeze a C ABI and make the header the contract

Export only `extern "C"` functions and C-compatible values. Do not export a
Rust struct layout, trait object, reference, `String`, `Vec`, `Result`, enum
with data, or unwinding function. Swift imports the Clang module name, not a
bridging header with a second copy of the declarations.

Read [references/c-header-contract.md](references/c-header-contract.md) when
you choose the C shape, integer width, or output style for a Rust value,
generate or review the header with `cbindgen`, or write the modulemap.

Keep the `#[unsafe(no_mangle)]` exports (required by Edition 2024) in one
boundary crate, because `#![forbid(unsafe_code)]` rejects that attribute. Keep
`#![forbid(unsafe_code)]` on each crate that has no hand-written `unsafe`. The
`rust-unsafe` skill owns this policy and the boundary crate's lint list.

Do not rely on a plain or `enum_extensibility(closed)` C enum as the
compatibility guard. Swift imports the closed form as an `@frozen` enum, so an
exhaustive `switch` has no case for a value that a newer library adds. Prefer
an `int32_t` status with named constants, or an open enum. Reserve an unknown
status value and map it to an `unexpected` Swift error.

## Use one opaque type per handle kind

Declare each handle as a different incomplete C type:

```c
typedef struct rs_engine rs_engine_t;
typedef struct rs_job rs_job_t;
typedef struct rs_error rs_error_t; /* not a handle: complete struct below */

rs_engine_t * _Nullable rs_engine_create(rs_error_t * _Nonnull error_out);
void rs_engine_release(rs_engine_t * _Nullable engine);
```

Do not use `void *` for all handles. The C compiler then accepts a job where an
engine is expected.

Use one exact create and release pair. The create function returns one owned
reference. The release function consumes that reference. Make release accept
null, and document that a second release of the same non-null pointer is
invalid.

The Swift owner releases once:

```swift
nonisolated final class Engine {
    private let raw: OpaquePointer

    init() throws {
        var error = rs_error_t()
        guard let raw = rs_engine_create(&error) else {
            throw EngineError(taking: &error)
        }
        self.raw = raw
    }

    deinit {
        rs_engine_release(raw)
    }
}
```

Do not make the raw pointer public. Do not make the wrapper a copyable struct.
Do not call a blocking join from `deinit` or from the main actor. Let an active
worker hold its own Rust reference until it stops.

Mark the wrapper `@unchecked Sendable` only when the Rust type behind the
handle is `Send + Sync` and every export that takes it is safe to call
concurrently. State that invariant next to the conformance. Otherwise keep the
wrapper non-`Sendable` or confine it to one actor.

## Keep allocator ownership symmetric

Use an explicit Rust buffer for variable output:

```c
typedef struct rs_buffer {
    uint8_t * _Nullable ptr;
    size_t len;
    size_t capacity;
} rs_buffer_t;

void rs_buffer_release(rs_buffer_t buffer);
```

Swift copies the bytes to `Data`, then passes the exact, unchanged value to
`rs_buffer_release` once. Swift must not call `free`, `deallocate`, or a
Foundation release function on it. The release function cannot validate
pointer provenance.

Apply these rules on the Rust side:

- Use a zeroed buffer (null, 0, 0) as the one empty value. It means "nothing
  to free", because Swift zero-initializes `rs_buffer_t()` and `rs_error_t()`.
- Carry the real capacity, because `Vec::from_raw_parts` needs the original
  allocation's capacity.
- Never rebuild a `Vec` when `len > capacity`.
- Map every zero-length borrowed input to `&[]`, because
  `slice::from_raw_parts` needs a non-null pointer even for length zero, and
  an empty Swift buffer can have a nil `baseAddress`.
- Reject null with a non-zero length.
- Reject a length above the operation limit before you build a slice.

Read [references/rust-buffer-exports.md](references/rust-buffer-exports.md)
when you write or review the Rust export of an owned buffer or a borrowed
Swift input. It holds the executed rules, the borrowed-pointer precondition,
and the MSRV fallback for `Vec::into_raw_parts` (Rust 1.93).

Copy borrowed bytes before the Swift `withUnsafeBytes` closure returns unless
the call is fully synchronous. Never store the temporary Swift pointer in a
Rust handle or worker.

For text, define UTF-8 bytes as the wire format. Do not accept or return
null-terminated strings unless the product contract prohibits embedded null
bytes. Validate UTF-8 in Rust and return a typed invalid-input status.

## Return errors explicitly

Use a stable numeric code and an explicit error output. Do not encode errors as
null alone, a negative length, `errno`, a panic, or a thread-local message.

```c
struct rs_error {
    int32_t code;
    rs_buffer_t message_utf8;
};
```

Initialize every output on every path. A success sets `code` to zero and the
message to the empty buffer. A failure sets a stable non-zero code and a
user-safe UTF-8 message. The Swift error initializer takes ownership of the
message buffer and releases it after it copies the bytes. Keep diagnostic
chains, paths, and backtraces in Rust logs. Swift maps codes to its own
`Error` enum with an unknown-code case.

Contain unwinding at every export. The `rust-panic-safety` skill, when it is
installed, owns the guard, the abort rules, and the `panic` profile setting.
A panic that escapes an export ends the process, and Swift gets no error and
no cleanup. A fallible export returns the reserved internal-error code for a
caught panic, never a domain code. A `void` release or cancel export logs the
panic and returns. Keep destructor paths non-panicking. Keep the `extern "C"`
body to validation, the panic guard, and delegation.

## Callbacks and cancellation

Read `references/callbacks-and-cancellation.md` when the boundary passes a callback or a callback context, Rust calls Swift from a worker thread, or you design cancel and release for a long job.

## Bridge a callback to AsyncStream

Read [references/async-stream-bridge.md](references/async-stream-bridge.md)
when you wrap a C callback in `AsyncStream` or `AsyncThrowingStream`. Use
`bufferingPolicy: .bufferingNewest(1)` for progress, because the default
`.unbounded` buffer grows while the consumer is slow.
