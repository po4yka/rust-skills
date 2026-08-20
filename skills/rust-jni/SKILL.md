---
name: rust-jni
description: Use when you export a Rust function to the JVM with the jni crate, write or change Kotlin external fun bindings, choose between raw JNI and UniFFI, or triage a JNI linkage error or a native crash on Android. Covers Java_package_class_method symbol naming, no_mangle plus extern system, panic containment at every export, AttachCurrentThread and DetachCurrentThread discipline for worker threads, 16-slot local-reference frames and with_local_frame, why JNIEnv must never cross an await point, JByteArray copies versus DirectByteBuffer and file-descriptor handoff on hot paths, Kotlin and Rust type mapping, Java exception throwing and exception_check, session-handle lifecycle contracts, and a triage table for UnsatisfiedLinkError, JNI DETECTED ERROR, and local-reference-table overflow. Triggers on JNI, external fun, no_mangle, JNIEnv, AttachCurrentThread, local ref, GlobalRef, FindClass, Android ClassLoader, UnsatisfiedLinkError, or native crash on Android.
license: BSD-3-Clause
---

# Rust JNI

## Purpose

Use this skill for every Rust function that the JVM calls directly, and for the
Kotlin or Java code that declares it. The JNI boundary has no compiler that
checks both sides. A wrong symbol name, an unguarded panic, an unattached
thread, or one local reference too many is a process abort at run time, not a
build error.

The rules below apply to any workspace. Derive the current export inventory
from the source tree before you change it. Do not trust a memory of which
symbols exist:

```bash
# Every JNI export in the workspace.
rg -n 'pub extern "system" fn Java_' --type rust

# Every native declaration on the JVM side.
rg -n 'external fun|System\.loadLibrary' --type kotlin
```

## When to consult

- You add, rename, or remove any `#[unsafe(no_mangle)] pub extern "system" fn Java_*` export.
- You add a callback from Rust back into Java that needs `JavaVM::attach_current_thread`.
- You resolve an application class from a Rust-created thread or diagnose why
  `FindClass` cannot see that class.
- You decide between the raw `jni` crate and UniFFI for a new binding surface.
- You review a diff that touches a `cdylib` crate or its Kotlin binding class.
- You triage `UnsatisfiedLinkError`, `JNI DETECTED ERROR IN APPLICATION`, or a
  native abort with no Rust panic message.

## jni crate API versions

The `jni` crate changed its API at 0.22. Code that compiles on 0.21 does not
compile on 0.22. Read the version from your `Cargo.toml` before you copy any
snippet:

```bash
cargo tree --invert jni
```

| Task | `jni` 0.21 | `jni` 0.22 |
|------|------------|------------|
| Env type inside a call | `JNIEnv<'local>` | `Env<'local>` |
| Env type in an export signature | `JNIEnv<'local>` | `EnvUnowned<'local>` |
| Panic guard | `std::panic::catch_unwind` | `env.with_env(..)` then `.resolve::<P>()` with an `ErrorPolicy` |
| Read a `JString` | `env.get_string(&s)?.into()` | `s.mutf8_chars(env)?.to_str().into_owned()` |
| Attach a thread | `let _guard = vm.attach_current_thread()?` (RAII guard) | `vm.attach_current_thread(closure)`; the thread-local guard detaches at thread exit |
| Attach for one call only | `attach_current_thread_as_daemon` keeps the thread attached | `vm.attach_current_thread_for_scope(closure)` detaches when the closure returns |
| Global reference | `GlobalRef` | `Global<JObject<'static>>` |
| Method name and signature | `&str` literals | `jni::jni_str!` and `jni::jni_sig!` macros |

The snippets below use 0.22 unless the text says 0.21. `catch_unwind` works on
both versions, and it is the only guard available in `JNI_OnLoad`.

## Choose raw JNI or UniFFI

|  | Raw `jni` crate | UniFFI |
|--|-----------------|--------|
| Control | Full | Framework-managed |
| Boilerplate | High: you write every signature | Low: generated from UDL or proc-macro |
| Error handling | Manual Java exception throwing | Automatic mapping to a typed error |
| Kotlin code | You write `external fun` by hand | Bindings are generated |
| Panic guard | You write it at every export | Generated scaffolding contains it |
| Best for | A few functions, performance-critical paths | Many functions, complex types |
| Crate | `jni = "0.22"` | `uniffi = "0.28"` |

Decision rule:

- **Small, handle-based surface** (create, start, stop, poll, destroy) with a
  hot data path: use the raw `jni` crate. The generated layer buys little when
  the payload is one `jlong` handle and one JSON string.
- **Growing API with rich types**, or a second target platform: use UniFFI. The
  cost of hand-writing and hand-testing dozens of signatures on both sides
  exceeds the cost of the generator.
- Do not mix both styles on one class. Pick per binding surface.

See [references/uniffi-vs-raw-jni.md](references/uniffi-vs-raw-jni.md) for the
UniFFI shape and the bindings-generation command, and the `uniffi-boundary`
skill for the full generated-boundary contract.

## The export shape

### Symbol naming

```text
Java_com_example_app_NativeBindings_nativeCreate
     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ^^^^^^^^^^^^
     mangled binary class name       mangled method name
```

Do not derive this name with dot-to-underscore replacement alone. JNI mangles
`/` as `_`, `_` as `_1`, `;` as `_2`, `[` as `_3`, and each other UTF-16 code
unit as lowercase `_0xxxx`. For overloaded native methods, append `__` and the
mangled parameter descriptor. The JVM tries the short name first and then the
long overload name.

Prefer `RegisterNatives` in `JNI_OnLoad` when class or method names contain
underscores or Unicode, or when native methods are overloaded. It binds the
Java name and descriptor explicitly and avoids hand-written linker-name
mangling. Check every registration result and return `JNI_ERR` from
`JNI_OnLoad` on failure. If you use exported `Java_*` names, generate them from
the JNI mangling rules and compare them with `javac -h` output.

A name or descriptor mismatch is `UnsatisfiedLinkError` at the first call,
never a Rust build failure.

### Attributes

Every export uses `#[unsafe(no_mangle)]` (Rust 2024 syntax; `#[no_mangle]` on
earlier editions) and `extern "system"`. Do not use `extern "C"` for JNI.

The rustc lint `improper_ctypes_definitions` fires on these signatures, because
the `jni` types carry lifetime parameters that the FFI-safety check cannot
prove. Allow the lint on the bridge crate or on the export. Do not change the
parameter types to silence it.

### Panic containment

**Severity: CRITICAL.** A Rust panic that reaches an `extern "system"` export
aborts the process on Rust 1.81 and later; before 1.81 it is undefined
behavior. The JVM reports a native crash, not a Rust panic. Guard every export:
keep the extern body to one delegation call, with the logic in a plain function:

```rust
use std::panic::{AssertUnwindSafe, catch_unwind};

use jni::errors::ThrowRuntimeExAndDefault;
use jni::objects::{JObject, JString};
use jni::sys::jlong;
use jni::EnvUnowned;

/// Outer guard. Catches a panic raised before or outside `with_env`.
pub fn ffi_boundary<T, F: FnOnce() -> T>(default_on_panic: T, f: F) -> T {
    catch_unwind(AssertUnwindSafe(f)).unwrap_or(default_on_panic)
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_example_app_NativeBindings_nativeCreate<'local>(
    env: EnvUnowned<'local>,
    _thiz: JObject<'local>,
    config_json: JString<'local>,
) -> jlong {
    ffi_boundary(0, move || create_entry(env, config_json))
}

pub(crate) fn create_entry<'local>(
    mut env: EnvUnowned<'local>,
    config_json: JString<'local>,
) -> jlong {
    env.with_env(|env| -> jni::errors::Result<jlong> {
        let config: String = config_json.mutf8_chars(env)?.to_str().into_owned();
        Ok(create_session(&config))
    })
    .resolve::<ThrowRuntimeExAndDefault>()
}

fn create_session(_config: &str) -> jlong { todo!() }
```

`with_env` is the inner guard on `jni` 0.22: it catches the panic and returns a
`#[must_use]` `EnvOutcome`. `resolve` rebuilds an `Env` and runs an
`ErrorPolicy` over the error and the caught panic, so it is the only place an
exception can be thrown. `into_outcome` gives the raw tri-state instead; take it
only when the exit does not throw. On `jni` 0.21 wrap the whole body in
`catch_unwind(AssertUnwindSafe(|| { ... }))` and throw in the `Err` arm.

Raw `catch_unwind` is also the only choice in `JNI_OnLoad` and `JNI_OnUnload`,
where `EnvUnowned` is not available.

`catch_unwind` catches nothing when the profile that builds the `cdylib` sets
`panic = "abort"`. The process aborts at the panic site instead. That is still
defined behavior, but the Java caller gets a native abort and no exception. If
you need the exception, keep `panic = "unwind"` for that profile.

When you export many functions, generate the extern layer with a macro so no
hand-written body can drift from the pattern. See the `rust-unsafe` skill for
that macro and for the ownership rules of `JString::from_raw` and friends.

### Throwing a Java exception

An `ErrorPolicy` throws for you. Inside `with_env`, and on `jni` 0.21, throw
with `env.throw_new` and return a default value in the same arm. The exception
becomes visible to the JVM only after the native function returns.
After you call any Java method from Rust, check `env.exception_check()` before
you use the result; a pending exception makes most later JNI calls illegal.

Strip internal detail from the exception message in release builds. The message
crosses into the app and can reach a log or a bug report.

See [references/types-and-exceptions.md](references/types-and-exceptions.md) for
the `throw_new` form of each crate version, the pending-exception helpers, and
the full Kotlin-to-Rust type table.

## The JVM side

The binding class is half of the contract, and three rules decide whether it holds:

- Load the library exactly once, from a `companion object` initializer or a shared
  loader object. A loader object is better when several binding classes share one `.so`.
- Keep the `external fun` declarations `private` and expose a plain interface. The
  interface is what tests fake; an `external fun` cannot be faked.
- Serialize every call that touches a session handle unless the Rust side documents
  itself as thread-safe for that handle. A use-after-free of a handle is a native
  abort, not an exception.

The worked Kotlin class is in [references/jvm-side.md](references/jvm-side.md).

## Add a new export

Do these steps in one patch. A half-applied patch is a run-time linkage error,
not a build failure.

1. Declare the `external fun` on the binding class. Keep it `private`.
2. Register the method name and descriptor with `RegisterNatives`, or implement
   the exact JNI symbol in the `cdylib` crate with
   `#[unsafe(no_mangle)] pub extern "system" fn Java_<package>_<Class>_<method>`.
   For an overloaded native method, include the mangled parameter descriptor.
   Generate the name with `javac -h`; do not replace punctuation by hand.
3. Wrap the body in the panic guard. Add nothing else to the extern body.
4. Keep the session semantics of the surrounding class: blocking calls stay
   blocking, non-blocking calls stay non-blocking, and setup failures surface
   as Java exceptions.
5. If the new function touches shared session state, apply the existing
   synchronization model on both sides.
6. Build the library and confirm the symbol is present before you run the app:

   ```bash
   nm -D --defined-only libexample_native.so | grep Java_
   ```

## Session-handle lifecycle

The common raw-JNI surface is a handle-based session. Keep the contract
explicit, because the blocking behaviour of each call is part of it:

| Function | Parameters | Returns | Contract |
|----------|-----------|---------|----------|
| `nativeCreate` | config `String` (often JSON) | `jlong` handle, `0` on failure | Allocates native state. `0` means failure. |
| `nativeStart` | handle, optional `jint` fd | `jint` status or void | State whether it blocks. Blocking versus non-blocking is a compatibility contract. |
| `nativeStop` | handle | void | Graceful shutdown. Must be safe to call twice. |
| `nativePoll*` | handle | `String?` or array | Returns `null` when there is nothing pending. Must never block. |
| `nativeDestroy` | handle | void | Frees native state. Every later call with that handle is a bug. |

Additional rules:

- A `jlong` handle is an opaque generational registry key. Never expose a
  `Box::into_raw` pointer as a handle. A caller can forge any integer, and Rust
  cannot validate whether an arbitrary address is live before dereferencing it.
- Encode a non-zero slot index and generation in the key. On each call, check
  the slot bounds and generation under the registry lock before you access the
  session. Return a Java exception or the documented invalid-handle status when
  either check fails.
- On `nativeDestroy`, remove the session and increment the slot generation
  before you reuse that slot. This rejects stale handles even when a later
  session occupies the same slot. Never issue `0`; keep it as the failure value.
- If a JNI string payload carries a structured document (JSON), that document
  is a compatibility boundary: field removal and field rename are breaking
  changes. Keep contract tests on both sides and update both in one patch.
- Setup failures surface as Java exceptions, not as magic return values, unless
  the return value is already documented as a status code.

## Type mapping

The full table is in
[references/types-and-exceptions.md](references/types-and-exceptions.md). The
three that cause most defects:

- A `String` parameter is a `JString`. Convert it inside the env scope, never
  after it.
- A nullable return is `std::ptr::null_mut()`, not an empty string. Return a new
  Java string with `env.new_string(text)?.into_raw()`.
- A `ByteArray` parameter copies. See the hot-path rules below.

## Thread attachment

A thread that Rust created (a tokio worker, a `std::thread::spawn` thread, a
raw pthread) is not a JVM thread. It must attach before it calls any Java
method, and it must detach before it exits. A thread that exits while attached
makes the JVM log:

```text
JNI WARNING: native thread exiting without DetachCurrentThread
```

On Android this warning is upgraded to a fatal abort under some combinations of
`android:debuggable` and API level. Treat it as fatal always.

To attach, a thread needs the `JavaVM`. `JavaVM` is `Clone + Send + Sync` and
stays valid for the life of the process, so capture it once at library load and
duplicate it with `vm.clone()`. The handle is one pointer and has no `Drop`, so
a clone can never reach `DestroyJavaVM`, and an `Arc` around it buys nothing.
Do not rebuild it with `unsafe { JavaVM::from_raw(vm.get_raw()) }`: that is an
`unsafe` call for what the safe `Clone` impl already does.

On `jni` 0.22 you attach with a closure. The crate installs the thread-local
guard, so the detach cannot be forgotten:

```rust
// Long-lived worker that calls back many times: attach once, stay attached.
// The thread-local guard detaches at thread exit.
let result: Result<i32, jni::errors::Error> =
    vm.attach_current_thread(|env| -> jni::errors::Result<i32> {
        let text = env.new_string(&payload)?;
        env.call_method(
            &listener,
            jni::jni_str!("onUpdate"),
            jni::jni_sig!("(Ljava/lang/String;)I"),
            &[jni::objects::JValue::Object(&text)],
        )?
        .i()
    });
```

Use `vm.attach_current_thread_for_scope(closure)` instead when the thread makes
one call and then does other work: that form detaches when the closure returns,
so the thread is never left attached. Do not use it in a hot loop; a scoped
attach on a reused thread pays the attach cost every call. `jni` 0.22 has no
daemon variant.

On `jni` 0.21 you bind an RAII guard instead:
`let _guard = vm.attach_current_thread()?;`. The trap there is an unbound guard.
`vm.attach_current_thread()?;` with no binding, and `let _ = ...`, both drop the
guard at the end of that statement and detach before the next JNI call runs.
Always bind to a named `let _guard`.

Attachment costs roughly 5-15 microseconds on Android. That is acceptable for
control-plane calls and unacceptable per packet or per flow. See
[references/jni-threading-and-callbacks.md](references/jni-threading-and-callbacks.md)
for the attach-form decision table, the 0.21 daemon attachment, the
`pthread_key_create` destructor for pure pthread workers, callback wiring from
an async task, and thread naming.

## Class lookup from attached threads

`FindClass` does not use the application loader on a newly attached native
thread. No managed application method exists on that thread's Java stack, so
Android falls back to the system class loader. That loader cannot see
application classes.

Resolve stable application classes in `JNI_OnLoad`. That call runs in the
loader context that loaded the native library. Promote every cached `jclass`
to a global reference. Cache the required method and field IDs with it. Publish
the cache only after all lookups and `RegisterNatives` calls succeed. Return
`JNI_ERR` if any required lookup fails, so the library load fails before a
worker starts.

Never cache a local `jclass` or any env handle. For a dynamic feature or a
custom loader, pass a managed `Class` argument or cache that feature's
`ClassLoader` and call `loadClass`. A process-lifetime global class reference
pins its loader, so do not use the base-app cache for classes that must unload
or reload.

Read [references/android-class-loading.md](references/android-class-loading.md)
before you add an application-class lookup, cache a method or field ID, enable
R8 for a JNI surface, or test a callback from a Rust-created thread. It gives
the separate `jni` 0.21 and 0.22 forms.

## Local reference frames

Every `env.find_class`, `env.get_field`, `env.new_string`, and `env.call_method`
that returns a `JObject` consumes a local-reference slot. The JNI specification
guarantees only 16 per frame, and Android aborts the process when its table
overflows. Wrap every loop that creates JNI objects in
`env.with_local_frame(capacity, |env| ...)`, sized at the element count plus a
margin. A reference created inside the frame dies when the frame pops, so build
anything that must outlive the loop in the outer frame. To keep a Java object
between calls, promote it with `env.new_global_ref(obj)`.

[references/jni-threading-and-callbacks.md](references/jni-threading-and-callbacks.md) has the
loop pair, the single-object forms, and the global-reference ownership rules.

## The env must not cross an await point

The env handle (`JNIEnv<'a>` on `jni` 0.21, `Env<'a>` on 0.22) is
`!Send + !Sync`. Holding one across `.await` in a `Send` future (the default for
`tokio::spawn`) does not compile. The danger is the "fix" that an unsafe escape
hatch makes compile:

```rust
// FORBIDDEN: leaks the env and lies about its lifetime.
let env_static: &'static mut JNIEnv = Box::leak(Box::new(env));

// FORBIDDEN: same lie, no allocation.
let env_static: &'static mut JNIEnv = unsafe { std::mem::transmute(env) };

// FORBIDDEN: captures the env in a task that another thread may run.
tokio::spawn(async move { env.call_method(/* ... */); });
```

Correct pattern: use the env synchronously, extract owned data, then spawn. The
task captures a `JavaVM` clone and a global reference, never an env and never
a local reference, and attaches its own thread when it needs to call back:

```rust
// jni 0.22.
fn handle(env: &mut Env<'_>, vm: JavaVM, listener: Global<JObject<'static>>) {
    let payload = extract_payload(env); // synchronous use of env

    tokio::spawn(async move {
        do_async_work(&payload).await;
        let _ = vm.attach_current_thread_for_scope(|env| -> jni::errors::Result<()> {
            env.call_method(&listener, jni::jni_str!("onComplete"), jni::jni_sig!("()V"), &[])?;
            Ok(())
        });
    });
}
```

Never `unwrap` a JNI error on a path that can run during shutdown. The JVM may
already be tearing the thread down.

See the `rust-async-internals` skill for driving async work from a foreign
thread with `block_on`, and `ffi-error-progress-cancel` for reporting progress
and cancellation back across the boundary.

## Hot-path data: JByteArray versus DirectByteBuffer

`env.convert_byte_array` and `env.get_byte_array_region` copy bytes out of the
JVM heap. `GetByteArrayElements` and the `jni` 0.21 elements guard may return a
copy or pin the array. The VM reports which choice it made through `isCopy`.
Release elements on every path; use `JNI_ABORT` for read-only access and mode
`0` when writes must be copied back. Do not hold elements across `.await` or a
blocking call.

Three options, best first:

1. **Do not move the bytes at all.** Hand the file descriptor over once, as a
   `jint`, at session start. The payload never crosses JNI again.
2. **DirectByteBuffer** when bytes must transit and a copy is too expensive.
   The memory belongs to the JVM, so the slice is valid only while the Java
   reference to that buffer is alive.
3. **`JByteArray`** for control-plane payloads only: configuration, a report, a
   command. Copy or pin overhead is irrelevant when the call is rare.

[references/hot-path-data.md](references/hot-path-data.md) has the direct-buffer
mapping code with its SAFETY argument, the file-descriptor handoff rules, and
why a duplicated fd is required for asynchronous use.

## Native library and build boundaries

- Never edit a `.so` file. It is built from source by the Cargo build that the
  module build runs before packaging.
- The library file name and every exported JNI symbol are compatibility
  boundaries. Change them only in a patch that changes the JVM call sites too.
- Keep the NDK version and the ABI filter list in one place (a properties file
  read by the build convention), never duplicated in per-module build scripts.
- Keep linker flags, including 16 KB page-alignment flags, in the workspace
  `.cargo/config.toml`.

See the `rust-android-build` skill for `.so` size, the exported-symbol
allowlist, and page alignment.

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `UnsatisfiedLinkError: No implementation found for ...` | Symbol name does not match package, class, or method | Rebuild the name from the declaring class. Confirm the symbol is present: `nm -D libexample_native.so \| grep Java_` |
| `UnsatisfiedLinkError` while the library itself loads | Missing `#[unsafe(no_mangle)]`, `extern "C"` instead of `extern "system"`, or the symbol was hidden or stripped by the linker | Restore the attributes; check the exported-symbol allowlist |
| `UnsatisfiedLinkError: dlopen failed` | Wrong library name, missing ABI in the packaged output, or an unresolved dependency | Check the `System.loadLibrary` name against the built artifact and the ABI list |
| `JNI WARNING: native thread exiting without DetachCurrentThread` | 0.21: the attach guard was not bound, or dropped early. 0.22: the thread was attached outside any attach closure | 0.21: bind `let _guard = vm.attach_current_thread()?` for the whole call scope. 0.22: make every JNI call inside `attach_current_thread` or `attach_current_thread_for_scope` |
| `JNI DETECTED ERROR IN APPLICATION` | Stale local reference, wrong method signature string, or a JNI call made with an exception pending | Re-check the signature; call `env.exception_check()` after every Java call |
| Local reference table overflow abort | A loop created local refs without a frame | Wrap the loop body in `with_local_frame`. Create outliving objects in the outer frame |
| `SIGABRT` right after a Rust panic message | The panic unwound into the JVM | Add the panic guard at that export |
| Native crash with no Rust message in logcat | No Android logger installed | Initialize logging and the panic hook in `JNI_OnLoad` |
| Crash inside a callback long after the call returned | A local reference or an env handle was stored between calls | Store a global reference plus a `JavaVM` clone instead |
| `ClassNotFoundException` only on a Rust-created thread | `FindClass` selected the system loader because no application frame exists | Use the global class cache populated in `JNI_OnLoad`, or pass the correct `Class` or `ClassLoader` from managed code |
| Corruption after passing a DirectByteBuffer | The Java-side reference was collected while Rust held the slice | Hold a global reference for the buffer |
| Native abort with no exception, and `catch_unwind` never runs | The profile that builds the `cdylib` sets `panic = "abort"` | Accept the abort, or build that profile with `panic = "unwind"` |
| `improper_ctypes_definitions` warning on an export | The `jni` types carry lifetime parameters | Allow the lint on the bridge crate. Do not change the parameter types |

For tombstones, symbolication, and logcat filtering, use the `rust-debugging`
skill. For the panic hook and `Drop` hazards, use `rust-panic-safety`.

## Review checklist

Apply to every diff that touches a JNI export or its binding class.

- [ ] Every new `Java_*` export uses `#[unsafe(no_mangle)]` and `extern "system"`.
- [ ] Every export body is `EnvUnowned::with_env` plus `resolve`, or
      `catch_unwind`. No bare extern body.
- [ ] The symbol name matches the declaring class, character for character.
- [ ] Every callback from an async task or worker thread captures a `JavaVM`
      clone plus a global reference, never an env handle or a local reference.
- [ ] Every application-class lookup on a Rust-created thread uses a cached
      global class, a managed `Class`, or an explicit application
      `ClassLoader`. It does not call `FindClass` directly.
- [ ] Required classes and method or field IDs resolve before `JNI_OnLoad`
      returns success. The minified release build keeps string-only JNI members.
- [ ] Every attachment detaches: a bound named guard on `jni` 0.21, an attach
      closure on 0.22.
- [ ] Repeated callbacks on one worker thread do not use a scoped attach.
- [ ] Every loop that calls `find_class`, `new_string`, or `call_method` is
      wrapped in `with_local_frame`.
- [ ] No `Box::leak`, `mem::transmute`, or other escape hatch near an env handle.
- [ ] Every Java call from Rust is followed by an `exception_check` before the
      result is used.
- [ ] New worker threads are named (`thread_name_fn` or `pthread_setname_np`).
- [ ] Hot-path bytes do not cross as `JByteArray`. Use fd transfer or a
      DirectByteBuffer.
- [ ] Calls that touch a session handle are serialized on the JVM side.
- [ ] Blocking versus non-blocking behaviour of each export is documented and
      unchanged.
- [ ] Structured string payloads keep contract tests on both sides in the same patch.
- [ ] The `cdylib` profile is `panic = "unwind"` if the design needs a Java
      exception instead of an abort.
- [ ] No `JavaVM::from_raw`. A second handle comes from `vm.clone()`.
- [ ] If the platform requires the JVM to act on a native socket (for example
      `VpnService.protect`), every affected socket passes through that path
      before first use.

## References

- [references/jni-threading-and-callbacks.md](references/jni-threading-and-callbacks.md)
  — attachment lifetime, pthread destructors, callback wiring, file-descriptor
  handoff over a Unix socket, thread naming.
- [references/android-class-loading.md](references/android-class-loading.md) —
  application class lookup, loader ownership, cache initialization, R8 rules,
  and an attached-thread integration test.
- [references/uniffi-vs-raw-jni.md](references/uniffi-vs-raw-jni.md) — the
  UniFFI shape, UDL and proc-macro forms, and bindings generation.
- [references/hot-path-data.md](references/hot-path-data.md) — file-descriptor
  handoff, direct-buffer mapping, and the copy costs of each byte path.
- [references/types-and-exceptions.md](references/types-and-exceptions.md) — the
  full type table, `throw_new` per crate version, and pending-exception
  handling.

## See also

- `rust-unsafe` — `catch_unwind`, `JString::from_raw`, the export macro, symbol
  collision in `cdylib` crates.
- `rust-panic-safety` — panic policy, panic hooks, `Drop` and double-panic hazards.
- `rust-async-internals` — driving async from a foreign thread, `block_on` rules.
- `rust-debugging` — tombstones, symbolication, logcat, native crash triage.
- `rust-android-build` — `.so` size, symbol allowlist, ABI list, page alignment.
- `uniffi-boundary` — the generated-boundary contract.
- `ffi-error-progress-cancel` — errors, progress, and cancellation across FFI.
- `rust-crate-architecture` — where the `cdylib` shim sits in the crate graph.
