---
name: rust-swift-ffi
description: Use when Swift calls Rust through a C ABI without UniFFI and you must design or review the Swift-specific ownership, threading, and lifecycle contract. Covers a hand-written Swift FFI, a modulemap for a Rust static library, an opaque Rust handle in Swift, allocator symmetry, pointer and length pairs, explicit errors, callbacks from Rust threads, an @MainActor Rust callback, Sendable isolation, cancellation, and real Swift link tests. Triggers on Swift calls Rust through a C ABI, hand-written Swift FFI, opaque Rust handle in Swift, modulemap for a Rust static library, @MainActor Rust callback, Unmanaged.passRetained, or AsyncStream over a C callback.
license: BSD-3-Clause
---

# Rust Swift FFI

Use this skill for a hand-written C ABI that Swift consumes. Use it when the
project deliberately does not use UniFFI.

Keep these boundaries:

- Use `uniffi-boundary` when UniFFI generates the Swift API. Do not maintain a
  second hand-written ABI for the same surface.
- Use `rust-native-linking` for `build.rs`, `cbindgen`, linker inputs, static
  archives, modulemaps, and XCFramework assembly.
- Use `rust-unsafe` for raw-pointer soundness, layout proofs, and unsafe API
  review.
- Use `rust-panic-safety` for the full unwind audit and panic-hook policy.
- Use `ffi-error-progress-cancel` for a shared mobile error, progress, and job
  cancellation model.

This skill owns the contract between the stable C surface and the Swift
wrapper. Keep the exported C surface small. Put domain behavior in ordinary
Rust code and idiomatic Swift types outside the boundary.

## Completion evidence

Prove the boundary with the artifact that ships:

1. Build the exact Rust target and release profile.
2. Generate or verify the public C header.
3. Compile a Swift consumer against that header and the real archive or
   XCFramework.
4. Create a handle, call one fallible operation, and destroy the handle.
5. Exercise one callback from a Rust-created thread.
6. Cancel one active job and prove that no callback arrives after release.
7. Run the smoke test on every supported Apple platform slice.

Do not accept a Rust unit test, a generated header, or a successful archive
link as proof that Swift can use the boundary.

## First decide whether a hand-written ABI is necessary

Use UniFFI when Kotlin and Swift consume the same object model, records, errors,
and async operations. Use a hand-written C ABI only when at least one condition
is true:

- The public product is an existing C-compatible SDK.
- The Swift wrapper must preserve a fixed ABI across independent releases.
- The surface uses a C library convention that UniFFI cannot represent.
- The project needs a very small leaf interface and accepts manual ownership.

Do not select a hand-written ABI only to avoid one generator step. The manual
path owns every destructor, callback race, error conversion, and Swift
concurrency annotation.

## Freeze a C ABI, not a Rust ABI

Export only `extern "C"` functions and C-compatible values. Do not export a
Rust struct layout, trait object, reference, `String`, `Vec`, `Result`, enum
with data, or unwinding function.

Use these boundary shapes:

| Rust meaning | C ABI shape | Swift wrapper |
| --- | --- | --- |
| Stateful object | Pointer to an incomplete handle type | `final class` that releases once |
| Borrowed bytes | `const uint8_t *` plus `size_t` | `Data.withUnsafeBytes` |
| Rust-owned bytes | Pointer, length, capacity, and one Rust free function | Copy to `Data`, then free |
| Optional pointer | Nullable pointer with a documented null rule | Swift optional |
| Fallible call | Stable status code plus explicit output | `throws` |
| Long job | Opaque job handle plus non-blocking cancel | Task or stream wrapper |
| Callback state | `void *context` plus callback and release functions | Retained callback box |

Use fixed-width integers for persistent values and serialized fields. Use
`size_t` only for the size of memory in the current process. Represent Boolean
values as `uint8_t` with `0` and `1` unless the header and both compilers agree
on a C `_Bool` contract.

Do not expose a C enum as the only compatibility guard. Swift can make the
imported enum exhaustive. Reserve an unknown status value and map it to an
`unexpected` Swift error.

## Make the header the public contract

Generate the header with the pinned `cbindgen` version when Rust declarations
are the source of truth. Check the generated header into the SDK only when the
release process verifies that regeneration produces no diff.

Restrict generation to the boundary module. Do not publish declarations for
internal Rust types. Review the header as C, not as Rust source:

- Every public symbol has a stable prefix.
- Every handle is an incomplete type.
- Every integer has the intended width.
- Every pointer states nullability and ownership in a comment.
- Every returned allocation names its matching release function.
- No Cargo package path or private type name appears.

Use a Clang modulemap next to the public header:

```text
module RustCore {
    header "rust_core.h"
    export *
}
```

Swift must import the module name, not a bridging header with a second copy of
the declarations. Compile the header as both C and Objective-C in CI. This
catches a declaration that cbindgen emits but Clang cannot import into Swift.

## Use one opaque type per handle kind

Declare each handle as a different incomplete C type:

```c
typedef struct rs_engine rs_engine_t;
typedef struct rs_job rs_job_t;
typedef struct rs_error rs_error_t;

rs_engine_t * _Nullable rs_engine_create(rs_error_t * _Nonnull error_out);
void rs_engine_release(rs_engine_t * _Nullable engine);
```

Do not use `void *` for all handles. Swift can otherwise pass a job to an
engine function and the C compiler accepts it.

Use one exact create and release pair. The create function returns one owned
reference. The release function consumes that reference. Make release accept
null when this simplifies Swift `deinit`, but document that repeated release
of the same non-null pointer is invalid.

The Swift owner releases once:

```swift
final class Engine {
    private var raw: OpaquePointer?

    init() throws {
        var error = rs_error_t()
        guard let raw = rs_engine_create(&error) else {
            throw EngineError(taking: &error)
        }
        self.raw = raw
    }

    deinit {
        rs_engine_release(raw)
        raw = nil
    }
}
```

Do not make the raw pointer public. Do not make the wrapper a copyable struct.
Do not call a blocking join from `deinit` or from the main actor. Let an active
worker hold its own Rust reference until it stops.

## Keep allocator ownership symmetric

Prefer caller-owned output for small fixed-size values. Use a size query plus
a caller buffer only when the second call can report a changed size and retry,
or when the Rust object holds a stable snapshot.

Use an explicit Rust buffer for variable output:

```c
typedef struct rs_buffer {
    uint8_t * _Nullable ptr;
    size_t len;
    size_t capacity;
} rs_buffer_t;

void rs_buffer_release(rs_buffer_t buffer);
```

The Rust allocator creates the buffer. Pass only the exact, unchanged tuple
back to `rs_buffer_release`, and pass it once. The release function cannot
validate pointer provenance. For a non-empty allocation, it reconstructs and
drops that allocation. Swift must not call `free`, `deallocate`, or a
Foundation release function on it. Swift copies the bytes to `Data` before it
calls `rs_buffer_release`.

Treat the empty buffer as one canonical value: null pointer, zero length, and
zero capacity. Make `rs_buffer_release` return without calling
`Vec::from_raw_parts` for this value. Call `Vec::from_raw_parts` only for the
original non-null pointer, length, and capacity. Reject these invalid shapes
before constructing a Rust slice:

- null pointer with non-zero length,
- length greater than capacity for an owned buffer,
- a size that exceeds the operation limit,
- a pointer whose required alignment is not valid.

For borrowed Swift input, accept pointer plus length. Permit a null pointer
only when length is zero. Map that pair to `&[]` without calling
`slice::from_raw_parts`. For a non-null pointer, require one live allocation
that contains `len` initialized bytes and a range no larger than `isize::MAX`.
Code cannot validate this provenance, so make it a caller precondition. Copy
the bytes before the Swift `withUnsafeBytes` closure returns unless the call is
fully synchronous. Never store the temporary Swift pointer in a Rust handle or
worker.

For text, define UTF-8 bytes as the wire format. Do not accept or return
null-terminated strings unless embedded null bytes are prohibited by the
product contract. Validate UTF-8 in Rust and return a typed invalid-input
status.

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
message to the canonical empty buffer. A failure sets a stable non-zero code
and a user-safe UTF-8 message. The Swift error initializer takes ownership of
the message buffer and releases it after copying.

Keep diagnostic chains, paths, and backtraces in Rust logs. Swift maps codes
to its own `Error` enum. Preserve an unknown-code case so a newer library does
not crash an older wrapper.

Contain unwinding at every exported function. In a fallible export, convert a
caught panic to the reserved internal-error code. Do not reuse a domain error
code for a panic. In a `void` release or cancel export, catch the panic, log it,
and return. Keep all destructor paths non-panicking. A `panic = "abort"`
profile cannot catch a panic. Choose and document process abort, or use an
unwind profile for containment. Keep the `extern "C"` body to validation, the
panic guard, and delegation to ordinary Rust code. Load `rust-panic-safety`
for the guard implementation and profile decision.

## Give every callback one retained context

Represent a callback registration as three C values:

```c
typedef void (*rs_progress_fn)(void * _Nonnull context,
                               uint64_t completed,
                               uint64_t total);
typedef void (*rs_context_release_fn)(void * _Nonnull context);

rs_job_t * _Nullable rs_engine_start(
    rs_engine_t * _Nonnull engine,
    void * _Nonnull context,
    rs_progress_fn _Nonnull progress,
    rs_context_release_fn _Nonnull release_context,
    rs_error_t * _Nonnull error_out);
```

Swift passes one retained callback box:

```swift
let context = Unmanaged.passRetained(callbackBox).toOpaque()
```

The callback uses `takeUnretainedValue()`. The release callback uses
`Unmanaged<CallbackBox>.fromOpaque(context).release()` exactly once. Do not
use `takeRetainedValue()` in the progress callback. It consumes the reference
on the first event and leaves later events with a dangling pointer.

The release callback can run on a Rust worker. Keep `CallbackBox.deinit`
thread-independent. Do not perform UI or main-actor cleanup from that
destructor. Schedule such cleanup before the terminal callback instead.

Rust owns the retained context after `rs_engine_start` succeeds. Rust calls
`release_context` exactly once after all of these facts are true:

- The job completed or observed cancellation.
- No callback is running.
- No future callback can start.
- Rust removed the registration from every queue.

If start fails, Swift still owns the context and must release it. State this
transfer point next to the function declaration. Do not make both sides guess
which one releases on a partial failure.

Break reference cycles. The callback box can hold a weak reference to the
Swift owner. The Swift owner holds the job. Rust holds the callback box only
until the job reaches its terminal state.

## Treat callbacks as concurrent and non-main-thread calls

Assume Rust invokes every callback from an arbitrary worker thread. Never
touch UIKit, AppKit, SwiftUI state, or a main-actor object directly in the C
callback.

The C trampoline must copy scalar values and borrowed bytes before it returns.
Then it schedules the copied event on the main actor:

```swift
let deliver: @Sendable (Progress) -> Void = { [weak owner] progress in
    Task { @MainActor in
        owner?.receive(progress)
    }
}
```

Mark a callback box `@unchecked Sendable` only when all mutable state is actor
isolated or protected by a lock. Write that invariant next to the conformance.
Do not add `@unchecked Sendable` only to silence Swift 6 diagnostics.

Keep callback work bounded. Copy the event, schedule delivery, and return. Do
not wait synchronously for `MainActor.run`; a Rust worker can hold a lock that
the UI call needs and deadlock the process.

When a callback on a Rust-created thread constructs Foundation or Objective-C
temporary objects, wrap that synchronous callback body in
`autoreleasepool { ... }`. Copy all values that must outlive the pool. A task
scheduled onto an Apple executor uses that executor's pool and usually does
not need a second one.

## Make cancellation and release separate operations

Expose cancel as idempotent and non-blocking. It only marks the job cancelled
and wakes its worker. It does not join the worker and does not release callback
state.

The terminal path has one order:

1. Stop producing callback events.
2. Wait for any in-flight callback to return.
3. Mark the job terminal.
4. Call `release_context` once.
5. Release the worker's job reference.

Swift cancels when its `Task` or stream terminates. The wrapper can release its
job handle immediately if Rust workers hold their own reference. The callback
context stays valid until Rust calls the release function.

Do not use a Swift Boolean alone to prevent callbacks after owner destruction.
It cannot protect a context pointer from a concurrent Rust call. Enforce the
no-callback-after-release rule in Rust, and use the weak Swift owner only to
drop already-scheduled UI delivery.

## Test the consumer, not only the producer

Keep a small Swift test consumer outside the generated artifact directory. It
must use the same import path as the application.

The test must do these operations against the real release library:

- Import the Clang module.
- Create and release every handle kind.
- Pass empty and non-empty `Data`.
- Receive empty and non-empty Rust-owned buffers, then release them.
- Map one known error and one unknown error code.
- Receive a callback from a Rust-created thread.
- Cancel during a callback and during idle work.
- Drop the Swift owner while work runs.
- Assert that context release occurs once and that no later callback arrives.

Run the Swift test under Thread Sanitizer for callback and cancellation
changes. Run the Rust core tests under the applicable sanitizers or Miri, with
foreign calls replaced by a test callback. Sanitizer success on only one side
does not prove the cross-language lifetime.

In release CI, also compare the generated header, inspect exported symbols,
and link the packaged XCFramework. Do not link directly to a Cargo target file
when the application ships a different archive.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Swift imports no functions | Modulemap name, header path, or visibility is wrong | Compile the header with Clang and inspect the packaged modulemap |
| Duplicate or missing symbol | The header and archive came from different builds | Regenerate both from one release build and inspect exported symbols |
| Crash in `deinit` | The pointer was copied or released twice | Hide it in one non-copyable class and consume it once |
| Heap corruption after returning bytes | Swift used its allocator on Rust memory | Copy, then call the matching Rust release function |
| Crash after several progress events | The callback used `takeRetainedValue()` | Use `takeUnretainedValue()` and release only in the release callback |
| UI isolation warning or crash | Rust called a main-actor value directly | Copy the event and schedule it with `Task { @MainActor in ... }` |
| Owner stays alive after the job | Swift owner, job, and callback form a cycle | Use a weak owner and release the callback at terminal state |
| Callback arrives after cancellation | Cancel was treated as synchronous completion | Stop, drain callbacks, then release the context |
| Cancellation freezes the UI | Cancel or release joins a worker | Make cancel non-blocking and let the worker own its final reference |
| Error text changes into invalid bytes | String encoding or ownership is implicit | Use owned UTF-8 bytes and one Rust release function |
| Works in a Rust test but not the app | The test did not consume the packaged module | Compile, link, and call from the Swift integration fixture |

## Review checklist

- [ ] UniFFI was considered and rejected for a concrete requirement.
- [ ] The exported surface contains only C-compatible declarations.
- [ ] The public header and modulemap come from the shipping build.
- [ ] Each handle has one type and one create or release pair.
- [ ] Every pointer documents nullability, ownership, and lifetime.
- [ ] Rust allocations return only to the Rust allocator.
- [ ] Every output is initialized on success and failure.
- [ ] Every exported function contains panic containment.
- [ ] Swift maps stable codes and preserves an unknown case.
- [ ] Callback ownership transfers at one documented point.
- [ ] The callback context is released once after callbacks drain.
- [ ] Rust-thread callbacks schedule copied values onto the correct actor.
- [ ] `@unchecked Sendable` has a stated synchronization invariant.
- [ ] Cancel is idempotent and non-blocking.
- [ ] Swift compiles, links, calls, cancels, and releases the real artifact.
