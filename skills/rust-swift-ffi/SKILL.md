---
name: rust-swift-ffi
description: Use when designing, reviewing, or fixing the ownership, threading, or lifecycle contract of a hand-written Swift FFI, where Swift calls Rust through a C ABI and a C header without UniFFI. Triggers on a string that reaches Swift as garbage, an abort at a Rust export, an opaque Rust handle in Swift, a Rust-owned buffer returned to Swift, @MainActor Rust callback, AsyncStream over a C callback, or SWIFT_DEFAULT_ACTOR_ISOLATION. Not for UniFFI-generated Swift (use uniffi-boundary) or XCFramework packaging (use rust-ios-build).
license: BSD-3-Clause
---

# Rust Swift FFI

This skill owns the contract between a hand-written C ABI and its Swift
wrapper. Keep the C surface small, and keep domain behavior out of it.

When UniFFI generates the Swift API, the `uniffi-boundary` skill owns it; never
keep a second hand-written ABI for it. The `ffi-error-progress-cancel` skill
owns mobile errors, progress, and cancellation.

## First decide whether a hand-written ABI is necessary

Use UniFFI when Kotlin and Swift consume the same object model. Use a
hand-written C ABI only when at least one condition is true:

- The public product is an existing C-compatible SDK.
- The Swift wrapper must preserve a fixed ABI across independent releases.
- The surface uses a C library convention that UniFFI cannot represent.
- The project needs a very small leaf interface and accepts manual ownership.

Do not pick a hand-written ABI only to skip a generator step: the manual path
owns every destructor, callback race, and error conversion.

## Completion evidence

Prove the boundary with the artifact that ships: a Rust test, a header, or a
clean archive link does not prove that Swift can use it.

| Claim | Check | Run it when |
| --- | --- | --- |
| The header matches the exports | Regenerate with the pinned `cbindgen`, then `git diff --exit-code -- <header>` | An exported item changes |
| Clang accepts the header | `printf '#include "<header>"\n' \| xcrun clang -fsyntax-only -Werror -I <dir> -x c -`, and `-x objective-c` | The header changes |
| The archive defines each header function | `nm -gU <lib>.a` shows a `T _rs_...` line for every declared function | Before packaging |
| Swift imports and calls the real artifact | The consumer test below, with the app target's `SWIFT_VERSION`, `SWIFT_DEFAULT_ACTOR_ISOLATION`, and `SWIFT_APPROACHABLE_CONCURRENCY`, and in Swift 6 mode | The boundary changes |
| Swift code that Rust reaches is not main-actor code | Review that each declaration Rust reaches is `nonisolated`; a clean build proves nothing | A wrapper or callback changes |
| Callbacks and cancellation are race-free | The consumer test under Thread Sanitizer: `swift test --sanitize=thread`, or `xcodebuild test -enableThreadSanitizer YES` | A callback or cancel path changes |
| The Swift use of Rust memory has no memory error | The consumer test under `swift test --sanitize=address`, or `xcodebuild test -enableAddressSanitizer YES` | A buffer, handle, or release path changes |
| Rust buffer and handle code is sound | `cargo +nightly miri test --locked` with a Rust test callback that dereferences the context pointer; without the `miri` component, report it as not checked | Unsafe boundary code changes |
| Every shipped slice works | A smoke test on each supported Apple slice, after `nm -gU` shows the symbol on each (`rust-ios-build` owns the lanes) | Before release |

Keep a small Swift consumer test outside the generated artifact directory. It
uses the application's import path and runs against the real release library or
XCFramework. Only that test proves the cross-language lifetime: the Xcode
sanitizers check no Rust memory access, and Miri sees only Rust. Read
[references/consumer-test.md](references/consumer-test.md) when you write or
extend the consumer test (its required operations) or read a sanitizer result.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Swift imports no functions | Modulemap name, header path, or visibility is wrong | Compile the header with Clang and inspect the packaged modulemap |
| Duplicate or missing symbol | Header and archive from different builds | Regenerate both from one release build |
| Crash in `deinit` | The pointer was copied or released twice | One non-copyable owner class that releases once |
| Heap corruption after returning bytes | Swift freed Rust memory, or Rust rebuilt the `Vec` with the wrong capacity | Copy, then call the Rust release function with the unchanged buffer |
| Rust reads freed bytes after a call returns | Rust kept the temporary `withUnsafeBytes` pointer | Copy the bytes before the closure returns |
| Crash after several progress events | The callback used `takeRetainedValue()` | Use `takeUnretainedValue()` and release only in the release callback |
| Crash or corrupt state when an Objective-C API raises in a callback | An `NSException` unwound into an `extern "C"` Rust frame, which is UB | Call the API through an `@try`/`@catch` shim, or keep it out of the callback |
| A `main actor-isolated` diagnostic, a `dispatch_assert_queue` trap, a UI hang in an async wrapper, or a race in a context box | Default MainActor isolation, a wrong actor hop, or a non-`Sendable` box | The triage table in `references/swift-isolation.md` |
| Newer library breaks an older app's `switch` | The status is an `enum_extensibility(closed)` C enum, so Swift has no unknown case | Map codes through an unknown case, or use an `int32_t` status or an open enum |
| Owner stays alive after the job | Owner, job, and callback form a cycle | Weak owner; release the callback at terminal state |
| Callback arrives after cancellation | Cancel treated as synchronous completion | Stop, drain callbacks, then release the context |
| Cancellation freezes the UI | Cancel or release joins a worker | Make cancel non-blocking and let the worker own its final reference |
| `failed to join thread: Resource deadlock avoided (os error 11)` | Swift dropped the last job reference inside `release_context`, and release joins the worker | Make release non-blocking and call `release_context` with no lock held |
| Progress stream memory grows | `AsyncStream` default `.unbounded` buffer | `bufferingPolicy: .bufferingNewest(1)` |
| Error text turns into invalid bytes | Implicit string encoding or ownership | Owned UTF-8 bytes and one Rust release function |
| App aborts with no Swift error | A Rust panic reached an `extern "C"` boundary | Catch it in the export and return the reserved internal-error code |
| Works in a Rust test but not the app | The test did not use the packaged module | Call it from the Swift consumer test |

## Freeze a C ABI and make the header the contract

Export only `extern "C"` functions and C-compatible values. Do not export a
Rust struct layout, trait object, reference, `String`, `Vec`, `Result`, enum
with data, or unwinding function. Swift imports the Clang module name, not a
bridging header with a second copy of the declarations.

Read [references/c-header-contract.md](references/c-header-contract.md) when
you choose the C shape or width of a value, generate, review, or
compile-check the header, or write the modulemap.

Keep the `#[unsafe(no_mangle)]` exports in one boundary crate, and keep
`#![forbid(unsafe_code)]`, which rejects that attribute, on every crate with no
hand-written `unsafe`; the `rust-unsafe` skill owns this policy.

Use an `int32_t` status with named constants, or an open enum, never a plain or
closed C enum, as the compatibility guard. Reserve an unknown status value and
map it to an `unexpected` Swift error.

## Use one opaque type per handle kind

Declare each handle as a different incomplete C type
(`typedef struct rs_engine rs_engine_t;`). Do not use `void *` for all handles:
C then accepts a job for an engine.

Use one exact create and release pair. The create function returns one owned
reference, and the release function consumes it. Make release accept null, and
document that a second release of the same non-null pointer is invalid. Hide the
pointer in one non-copyable Swift class that releases it once in `deinit`; never
make it public or the wrapper a copyable struct. Never join from `deinit` or the
main actor: an active worker holds its own Rust reference until it stops.

Mark the wrapper `@unchecked Sendable` only when the Rust type behind the handle
is `Send + Sync` and every export that takes it is safe to call concurrently;
state that invariant next to the conformance. Read [references/handle-ownership.md](references/handle-ownership.md)
for the header declarations and the Swift owner class.

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
`rs_buffer_release` once, never to `free`, `deallocate`, or a Foundation release
function: the release function cannot validate pointer provenance.

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
Swift input, or need an MSRV below 1.93 (`Vec::into_raw_parts`).

Copy borrowed bytes before the Swift `withUnsafeBytes` closure returns unless
the call is fully synchronous. Never store the temporary Swift pointer in a
Rust handle or worker.

For text, use UTF-8 bytes as the wire format, not null-terminated strings
unless the contract prohibits embedded nulls. Validate UTF-8 in Rust and return
a typed invalid-input status.

## Return errors explicitly

Use a stable numeric code and an explicit error output. Do not encode errors as
null alone, a negative length, `errno`, a panic, or a thread-local message.

```c
struct rs_error {
    int32_t code;
    rs_buffer_t message_utf8;
};
```

Initialize every output on every path: success sets `code` to zero and an empty
message; failure sets a stable non-zero code and a user-safe UTF-8 message,
which the Swift error initializer copies and releases. Keep diagnostic chains,
paths, and backtraces in Rust logs. Swift maps codes to its own `Error` enum
with an unknown-code case.

Contain unwinding at every export with `std::panic::catch_unwind` (the
`rust-panic-safety` skill, when it is installed, owns the guard policy). A
fallible export returns the reserved internal-error code for a caught panic,
never a domain code; a `void` release or cancel export logs it and returns.
Keep destructor paths non-panicking, and keep the `extern "C"` body to validation, the panic guard, and delegation.

## Callbacks, cancellation, and AsyncStream

- Read `references/callbacks-and-cancellation.md` when the boundary passes a
  callback or a callback context, Rust calls Swift from a worker thread, or you
  design cancel and release for a long job.
- Read [references/async-stream-bridge.md](references/async-stream-bridge.md)
  when you wrap a C callback in `AsyncStream` or `AsyncThrowingStream`. Use
  `bufferingPolicy: .bufferingNewest(1)` for progress (triage table).
