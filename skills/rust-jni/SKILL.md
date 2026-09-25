---
name: rust-jni
description: Use when writing or reviewing Rust code that the JVM calls through JNI or that calls back into Java (jni crate, Kotlin external fun, RegisterNatives, JNI_OnLoad), choosing raw JNI or UniFFI, or triaging UnsatisfiedLinkError, JNI DETECTED ERROR IN APPLICATION, or a JNI-caused abort. Triggers on JNIEnv, EnvUnowned, AttachCurrentThread, DetachCurrentThread, GlobalRef, local reference table, FindClass, Android ClassLoader, native_method, jni_mangle, or a Java_ symbol name.
license: BSD-3-Clause
---

# Rust JNI

No compiler checks both sides of the JNI boundary. A wrong method name, an
unguarded panic, an unattached thread, or a leaked local reference fails at run
time on the device. Only a call from the JVM proves a binding; see
[Verify](#verify).

## Pin the jni crate version

The `jni` API changed at 0.22. Code for 0.21 does not compile on 0.22. Read the
locked version before you copy any snippet:

```bash
cargo tree --locked --target all -i jni --depth 0
```

Keep `--target all`: without it, `cargo tree` shows only host dependencies, and
prints nothing for a `jni` under `[target.'cfg(target_os = "android")'.dependencies]`.
An ambiguous-spec error means that the graph holds two `jni` versions. Find
them with `cargo tree --locked --target all -d`, and align them when you can.
The two copies do not share `JavaVM::singleton()` or attach state.

`jni` 0.22.0 and 0.22.1 are yanked; 0.22.2 has soundness fixes in `jni-macros`.
Declare `jni = "0.22.2"` or later (MSRV 1.85). If the lockfile still holds
0.22.0 or 0.22.1, run `cargo update -p jni`.

The snippets use 0.22 unless the text says 0.21. Read
[references/jni-versions.md](references/jni-versions.md) when the lockfile holds
0.21, or when you port code or a snippet between 0.21 and 0.22.

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `UnsatisfiedLinkError: No implementation found for ... (tried Java_... and Java_...__...)` | No export or registration matches the class, method, or descriptor | Compare the `tried` names with `llvm-nm -D` output. Check a Kotlin facade (`FooKt`) or `$` in the class name. Switch to `native_method!` with `RegisterNatives`, or `#[jni_mangle]` |
| `UnsatisfiedLinkError: dlopen failed: ...` | Wrong library name, missing ABI in the package, unresolved `DT_NEEDED`, or a page-alignment defect | Check the `System.loadLibrary` name and the packaged ABIs. See the `rust-android-build` skill |
| `JNI_ERR returned from JNI_OnLoad in "..."` | A class, ID, or registration failed, or `JNI_OnLoad` caught a panic | Log the failing lookup before you return `JNI_ERR`. Check class names and R8 keep rules |
| `Bad JNI version returned from JNI_OnLoad` | ART accepts only `JNI_VERSION_1_2`, `1_4`, or `1_6`, so `JNI_VERSION_1_8` and later fail | Return `JNI_VERSION_1_6` on success |
| `Native thread exited without calling DetachCurrentThread` | A thread attached through raw `AttachCurrentThread` exited attached | Attach through the crate API, or add a `pthread_key_create` destructor |
| Desktop or server JVM hangs at exit | A permanently attached Rust thread is a non-daemon Java thread, and `DestroyJavaVM` waits for it | Shut down the Rust runtime (`Runtime::shutdown_timeout`) and join the attached threads before `main` returns. Android is not affected |
| `JNI DETECTED ERROR IN APPLICATION` | Stale local reference, wrong signature string, or a JNI call with an exception pending | Re-check the descriptor. Propagate or clear every `Err(JavaException)` |
| Local reference table overflow abort (API < 26) | A loop created local references without a frame | Wrap the loop body in `with_local_frame` |
| `SIGABRT` right after a Rust panic message | A panic reached an export with no guard | Use `native_method!` or `with_env` at that export |
| Native abort with no exception, and the guard never runs | The `cdylib` profile sets `panic = "abort"` | Accept the abort, or build that profile with `panic = "unwind"` |
| Native crash with no Rust message in logcat | No logger or panic hook in the outermost Rust bootstrap | Initialize logging and the redacted hook there; see the `rust-panic-safety` skill |
| Crash in a callback long after the call returned | A local reference or an env was stored between calls | Store a global reference and a `JavaVM` clone |
| `ClassNotFoundException` only on a Rust-created thread | `FindClass` used the system loader | Use the `JNI_OnLoad` class cache, or a `Class` or `ClassLoader` from managed code |
| Corruption after passing a direct `ByteBuffer` | The Java buffer was collected while Rust held the slice | Hold a global reference to the buffer |
| `improper_ctypes_definitions` on `JNI_OnLoad` | `JavaVM` taken by value on 0.22 | Take `*mut jni::sys::JavaVM` and call `JavaVM::from_raw` |

## Verify

| Check | Command or action | Proves | Does not prove |
|-------|-------------------|--------|----------------|
| Crate version | `cargo tree --locked --target all -i jni --depth 0` | 0.22.2 or later, or a deliberate 0.21 | API use |
| Rust side | `cargo build --locked` for the Android target | Types, and descriptors that `native_method!` checks | That the Kotlin declaration matches |
| Exports | `llvm-nm -D --defined-only libexample_native.so \| rg 'Java_\|JNI_On'` (NDK `llvm-nm`) | The expected entry points exist | Registered names or descriptors |
| Binding | Instrumentation test that loads the library and calls each native method once | Name, descriptor, static or instance, and load order | Worker-thread paths |
| Callbacks | Instrumentation test that calls back from a Rust-created thread, with CheckJNI on | Attachment, class lookup, and reference use | R8 unless the test build is minified |

Run the device checks when the change touches a registration, an export, a
descriptor, an attach path, or R8 rules; a host `cargo test` is enough for pure
Rust logic behind the guard. CheckJNI is on by default on the emulator and in a
debuggable build. For a non-debuggable (R8) test build on a device, run
`adb shell setprop debug.checkjni 1` before the app starts; logcat then shows
`Late-enabling -Xcheck:jni`. Run the class-lookup test on an R8-enabled build
type ([references/android-class-loading.md](references/android-class-loading.md)).

## Bind a native method

### Default: RegisterNatives from JNI_OnLoad

Register every native method in `JNI_OnLoad`. A name or descriptor mismatch
then fails the library load (`JNI_ERR returned from JNI_OnLoad`), not the first
call. A static or instance mismatch still registers; the `abi_check` in
`native_method!` reports it at the first call, so the binding test must call
every method. `native_method!` checks the Rust types against the descriptor at
compile time and generates the panic guard and the error policy:

```rust
use std::ffi::c_void;
use std::panic::{AssertUnwindSafe, catch_unwind};

use jni::objects::{JObject, JString};
use jni::sys::{JNI_ERR, JNI_VERSION_1_6, jint, jlong};
use jni::{Env, JavaVM, NativeMethod, jni_str, native_method};

// Kotlin: `private external fun nativeCreate(configJson: String): Long`.
const NATIVE_CREATE: NativeMethod = native_method! {
    fn native_create(config_json: JString) -> jlong,
};

// The macro wraps this in `with_env(..).resolve::<ThrowRuntimeExAndDefault>()`.
fn native_create<'local>(
    env: &mut Env<'local>,
    _this: JObject<'local>,
    config_json: JString<'local>,
) -> jni::errors::Result<jlong> {
    let config: String = config_json.mutf8_chars(env)?.to_str().into_owned();
    Ok(create_session(&config))
}

fn create_session(_config: &str) -> jlong {
    todo!()
}

#[unsafe(no_mangle)]
extern "system" fn JNI_OnLoad(raw_vm: *mut jni::sys::JavaVM, _reserved: *mut c_void) -> jint {
    let init = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<()> {
        // SAFETY: the JVM passes a valid JavaVM pointer that stays valid for the process.
        let vm = unsafe { JavaVM::from_raw(raw_vm) };
        vm.with_local_frame(16, |env| -> jni::errors::Result<()> {
            let class = env.find_class(jni_str!("com/example/app/NativeBindings"))?;
            // SAFETY: `native_method!` built each entry from a Rust function whose
            // types match its descriptor, and each is an instance method of `class`.
            unsafe { env.register_native_methods(&class, &[NATIVE_CREATE])? };
            Ok(())
        })
    }));
    match init {
        Ok(Ok(())) => JNI_VERSION_1_6,
        Ok(Err(error)) => {
            // ART clears the pending exception after a failed load: log the lookup now.
            log::error!("JNI_OnLoad failed: {error}");
            JNI_ERR
        }
        // A payload's Drop can panic again. JNI_OnLoad runs once: leak it, never mem::forget.
        Err(payload) => {
            let _leaked = std::mem::ManuallyDrop::new(payload);
            JNI_ERR
        }
    }
}
```

This is the one `JNI_OnLoad` template. Its rules:

- Take the VM as `*mut jni::sys::JavaVM` and call `JavaVM::from_raw` once; it
  also seeds `JavaVM::singleton()`. On 0.22, `JavaVM` by value has no stable C
  layout, and `improper_ctypes_definitions` reports it (not the transparent
  `EnvUnowned`, `JObject`, or `JString` wrappers). Never allow the lint
  crate-wide: it is the check that finds this defect.
- Keep the raw `catch_unwind`. `EnvUnowned::with_env` is not available in
  `JNI_OnLoad` or `JNI_OnUnload`.
- Return `JNI_ERR` when any lookup or registration fails, so the load fails
  before any worker starts.

### Name-based exports

Use a name-based export only when the design needs a `Java_*` symbol. On 0.22,
never type the symbol name by hand: use `#[jni_mangle("pkg.Class")]`, or give
`native_method!` a `java_type` and the `extern` qualifier. Read
[references/java-symbol-names.md](references/java-symbol-names.md) when you
write a name-based export or debug a `No implementation found` error.

### Attributes, ABI, and panics

- A hand-written export uses `#[unsafe(no_mangle)]` (required in edition 2024,
  accepted since Rust 1.82) and `extern "system"`. `#![forbid(unsafe_code)]`
  rejects that attribute ("usage of the unsafe `#[no_mangle]` attribute") but
  passes the exports that `native_method!` or `#[jni_mangle]` generate, so the
  lint does not prove that a crate has no exports.
- Leave `pub` off an export that takes a raw pointer, such as `JNI_OnLoad`.
  `no_mangle` exports the symbol anyway, and clippy's deny-by-default
  `not_unsafe_ptr_arg_deref` rejects the `pub` form.
- `extern "system"` equals `extern "C"` on Android and 64-bit targets but differs
  on 32-bit Windows JVMs. Do not write `extern "C"` for JNI.
- A Rust panic that reaches an `extern "system"` function aborts the process
  (Rust 1.81+). `with_env` catches the panic, and `resolve` applies the error
  policy, for example `ThrowRuntimeExAndDefault`. On 0.21, wrap the whole body
  in `catch_unwind(AssertUnwindSafe(..))`. No guard catches anything when the
  `cdylib` profile sets `panic = "abort"` (see [Failure triage](#failure-triage)).
  The `rust-panic-safety` skill, when it is installed, owns the full policy and
  the 0.21 form.

### Java exceptions

A `call_*` method that leaves a Java exception pending returns
`Err(Error::JavaException)` on both versions. `throw_new` also returns it on
0.22; on 0.21 it returns `Ok`. The exception stays pending. Propagate it with
`?` to `resolve`, which hands it to the JVM, or on 0.22 call
`env.exception_catch()`, which clears it and returns
`Error::CaughtJavaException`. Never drop that `Err` with `let _ =` or `.ok()`
and then make more JNI calls: most JNI calls are illegal while an exception is
pending. Throw, then return at once. Call `env.exception_check()` after a raw
`jni::sys` call, and in a custom `ErrorPolicy` before it throws.

The default `ThrowRuntimeExAndDefault` policy copies the error's `Display` text
into the exception, which reaches app logs and bug reports. When that text can
carry input data or internal detail, set the `error_policy` property of
`native_method!`, or pass a fixed-message policy (the `rust-panic-safety` skill
has one) to `resolve`.

Convert a `JString` inside the env scope. Return `std::ptr::null_mut()` for a
`null` `String?`, not an empty string. A `ByteArray` parameter copies; see
[Hot-path data](#hot-path-data). Read
[references/types-and-exceptions.md](references/types-and-exceptions.md) when
you map any other Kotlin type or throw a specific exception class.

## The JVM side and session handles

- Serialize every call that touches a session handle unless the Rust side
  documents that handle as thread-safe: a use-after-free of a handle is a
  native abort.
- Make a `jlong` session handle an opaque generational registry key (a non-zero
  slot index plus a generation, checked under the registry lock on every call).
  Never expose a `Box::into_raw` pointer: a caller can forge any integer, and
  Rust cannot check that an address is live.
- The blocking behaviour of each method and every structured (JSON) payload are
  compatibility contracts. Change both sides in one patch, with contract tests
  on both sides.

Read [references/jvm-side.md](references/jvm-side.md) when you write the Kotlin
binding class (library loading, the `private external fun` layout) or design a
handle-based session surface.

## Add or rename a native method

The library file name and every registered or exported method are compatibility
boundaries. Change them only together with the JVM call sites, and do all steps
in one patch: a half-applied patch is a run-time linkage error.

1. Inventory the current surface from the source tree:

   ```bash
   rg -n 'native_method!|jni_mangle|fn Java_|JNI_OnLoad' --type rust
   rg -n 'external fun|\bnative\b[^;]*\(|System\.loadLibrary' --type kotlin --type java
   ```

2. Declare the `private external fun` on the binding class. Add a
   `native_method!` entry to the registration list (default), or a
   `#[jni_mangle]` export whose body is the guard expression.
3. Keep the blocking behaviour, the error surface (Java exceptions), and the
   synchronization model of the class on both sides.
4. Run the checks in [Verify](#verify).

## Thread attachment

A thread that Rust created (a tokio worker, a `std::thread`, a raw pthread)
must attach before it calls Java, and must be detached before it exits, or ART
aborts the process. The crate detaches every thread that attached through its
API (at guard drop, scope end, or thread exit), so do not add a second detach.
Only a thread that attached through raw `AttachCurrentThread` (C, C++,
`jni::sys`) needs its own `pthread_key_create` destructor.

Capture the `JavaVM` once at load, and make more handles with `vm.clone()` or,
on 0.22, `JavaVM::singleton()`. Call `from_raw` only on a raw pointer that the
host hands you: `JNI_OnLoad`, or `ndk_context` in a NativeActivity app. Never
rebuild a handle from `vm.get_raw()`.

- On 0.22, use `vm.attach_current_thread(|env| ..)` (stays attached) for a
  worker that calls back many times. Use `attach_current_thread_for_scope`
  (detaches when the closure returns) only for a one-off call: it pays the
  attach cost on every call. An attach call does not change an existing
  attachment.
- Every 0.22 attach call pushes a new local frame for the closure. An exception
  that the closure leaves pending is cleared and returned as
  `Error::CaughtJavaException`. Log or propagate that `Err`; never discard it.
- 0.22 has no daemon attachment, so the desktop or server JVM hang in
  [Failure triage](#failure-triage) applies: shut down the Rust runtime and
  join every attached thread before `main` returns.
- On 0.21, bind the guard to a name (`let _guard = vm.attach_current_thread()?;`):
  a bare statement or `let _ =` detaches before the next JNI call. Use
  `attach_current_thread_permanently` for a long-lived 0.21 worker.

Read [references/jni-threading-and-callbacks.md](references/jni-threading-and-callbacks.md)
when you write an attach call, wire a callback, build the load-time cache, or
ask the JVM to act on a native socket.

## Class lookup from attached threads

`FindClass` on a newly attached native thread uses the system class loader,
which cannot see application classes. Resolve stable application classes in
`JNI_OnLoad`, which runs in the loader context of `System.loadLibrary`. Promote
each class to a global reference, cache its method and field IDs with it, and
publish the cache only after every lookup and registration succeeds. Never
cache a local `jclass` or an env handle. For a dynamic feature or a custom
loader, pass a `Class` or a `ClassLoader` from managed code; a process-lifetime
global class reference pins its loader. Read
[references/android-class-loading.md](references/android-class-loading.md)
before you add an application-class lookup, cache a method or field ID, enable
R8 for a JNI surface, or test a callback from a Rust-created thread.

## Local reference frames

Each call that returns a Java object takes one local-reference slot, and the JNI
specification guarantees only 16 per frame. Android before 8.0 (API < 26) aborts
on overflow; later versions only grow memory. Wrap every loop that creates Java
objects in `env.with_local_frame(capacity, |env| ...)`, sized at the
per-iteration count plus a margin. A reference created inside the frame dies
when the frame pops: create a result that outlives the loop in the outer frame,
and promote an object that you keep between calls with `env.new_global_ref(obj)`.

## The env must not cross an await point

The env handle is `!Send + !Sync`. Holding it across `.await` in a `Send` future
does not compile. The danger is the "fix" that makes it compile:

```rust
// FORBIDDEN: leaks the env and lies about its lifetime.
let env_static: &'static mut JNIEnv = Box::leak(Box::new(env));

// FORBIDDEN: same lie, no allocation.
let env_static: &'static mut JNIEnv = unsafe { std::mem::transmute(env) };

// FORBIDDEN: captures the env in a task that another thread may run.
tokio::spawn(async move { env.call_method(/* ... */); });
```

Use the env synchronously, extract owned data, then spawn. The task captures a
`JavaVM` clone and a global reference, never an env or a local reference. A
JVM thread that calls a native method is not a Tokio runtime thread, so a bare
`tokio::spawn` panics there. Spawn through a `Handle` that the library keeps in
its load-time cache. Never `unwrap` a JNI error on a path that can run during
shutdown: the JVM may already be tearing the thread down. Read
[references/jni-threading-and-callbacks.md](references/jni-threading-and-callbacks.md)
when you spawn async work from a native method; it has the worked example.

## Hot-path data

`convert_byte_array` and `JByteArray` region reads copy bytes out of the JVM
heap. Array elements may be a copy or a pin, and must be released on every
path. Choose, best first: hand a file descriptor over once, as a `jint`, at
session start; a direct `ByteBuffer`, whose slice is valid only while the Java
buffer stays reachable; `JByteArray` only for control-plane payloads. Read
[references/hot-path-data.md](references/hot-path-data.md) when you map a
direct buffer, hand over a descriptor (it settles which side closes it), or
touch array elements.

## Choose raw JNI or UniFFI

Use the raw `jni` crate for a small, handle-based surface with a hot data path,
and UniFFI (`uniffi = "0.32.1"` or later) for a growing API with rich types or a
second platform. Do not mix both styles on one class. Read
[references/uniffi-vs-raw-jni.md](references/uniffi-vs-raw-jni.md) when you make
that choice.

## Review

Read [references/review-checklist.md](references/review-checklist.md) when you
review a diff that touches a native method, `JNI_OnLoad`, or a binding class.

## Related skills

Use these skills when they are installed:

- `rust-android-build`: NDK setup, per-ABI flags, 16 KB page alignment, and the
  exported-symbol gate. With `RegisterNatives`, the only JNI export that gate
  needs is `JNI_OnLoad`.
- `rust-debugging`: tombstones, symbolication, and logcat filtering.
- `rust-unsafe`: `SAFETY` comments and `from_raw` invariants for the `unsafe`
  calls at the boundary.
- `rust-crate-architecture`: where the `cdylib` shim sits in the crate graph.
- `rust-async-internals`: async work driven from a foreign thread.
- `ffi-error-progress-cancel`: progress and cancellation across the boundary.
