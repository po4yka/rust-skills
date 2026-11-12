---
name: rust-jni
description: Use when writing or reviewing Rust code that the JVM calls through JNI or that calls back into Java (jni crate, Kotlin external fun, RegisterNatives, JNI_OnLoad), choosing raw JNI or UniFFI, or triaging UnsatisfiedLinkError, JNI DETECTED ERROR IN APPLICATION, or a JNI-caused abort. Triggers on JNIEnv, EnvUnowned, AttachCurrentThread, DetachCurrentThread, GlobalRef, local reference table, FindClass, Android ClassLoader, native_method, jni_mangle, or a Java_ symbol name.
license: BSD-3-Clause
---

# Rust JNI

No compiler checks both sides of the JNI boundary. A wrong method name, an
unguarded panic, or an unattached thread fails at run time on the device. Only a call from the JVM proves a binding ([Verify](#verify)).

## Pin the jni crate version

The `jni` API changed at 0.22. Code for 0.21 does not compile on 0.22. Read the
locked version before you copy any snippet:

```bash
cargo tree --locked --target all -i jni --depth 0
```

Keep `--target all`: without it, a target-specific `jni` prints `warning:
nothing to print.` (cargo 1.99.1). An ambiguous-spec error means two `jni`
versions, which do not share `JavaVM::singleton()` or attach state; find them
with `cargo tree --locked --target all -d` and align them.

`jni` 0.22.0 and 0.22.1 are yanked; 0.22.2 has soundness fixes in `jni-macros`.
Declare `jni = "0.22.2"` or later (MSRV 1.85). If the lockfile still holds
0.22.0 or 0.22.1, run `cargo update -p jni`.

Read [references/jni-versions.md](references/jni-versions.md) when the lockfile
holds 0.21 or you port code between 0.21 and 0.22.

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `UnsatisfiedLinkError: No implementation found for ... (tried Java_... and Java_...__...)` | No export or registration matches the class, method, or descriptor | Compare the `tried` names with `llvm-nm -D` output. Check a Kotlin facade (`FooKt`) or `$` in the class name. Switch to `native_method!` with `RegisterNatives`, or `#[jni_mangle]` |
| `UnsatisfiedLinkError: dlopen failed: ...` | Wrong library name, missing ABI in the package, unresolved `DT_NEEDED`, or a page-alignment defect | Check the `System.loadLibrary` name, the packaged ABIs, and 16 KiB LOAD alignment with `llvm-readelf -lW` (the `rust-android-build` skill) |
| `JNI_ERR returned from JNI_OnLoad in "..."` | A class, ID, or registration failed, or `JNI_OnLoad` caught a panic | Log the failing lookup before you return `JNI_ERR`. Check class names and R8 keep rules |
| `Bad JNI version returned from JNI_OnLoad` | ART accepts only `JNI_VERSION_1_2`, `1_4`, or `1_6` | Return `JNI_VERSION_1_6` on success |
| `Native thread exited without calling DetachCurrentThread` | A thread attached through raw `AttachCurrentThread` exited attached | Attach through the crate API, or add a `pthread_key_create` destructor |
| Desktop or server JVM hangs at exit | A permanently attached Rust thread is a non-daemon Java thread that `DestroyJavaVM` waits for | Shut down the Rust runtime (`Runtime::shutdown_timeout`) and join the attached threads before `main` returns |
| `JNI DETECTED ERROR IN APPLICATION` | Stale local reference, wrong signature string, or a JNI call with an exception pending | Re-check the descriptor. Propagate or clear every `Err(JavaException)` |
| Local reference table overflow abort (API < 26) | A loop created local references without a frame | Wrap the loop body in `with_local_frame` |
| `SIGABRT` right after a Rust panic message | A panic reached an export with no guard | Use `native_method!` or `with_env` at that export |
| Native abort with no exception, and the guard never runs | The `cdylib` profile sets `panic = "abort"` | Accept the abort, or build that profile with `panic = "unwind"` |
| Native crash with no Rust message in logcat | No logger or panic hook in the outermost Rust bootstrap | Initialize logging and the redacted `std::panic::set_hook` there (the `rust-panic-safety` skill) |
| Crash in a callback long after the call returned | A local reference or an env stored between calls | Store a global reference and a `JavaVM` clone |
| `ClassNotFoundException` only on a Rust-created thread, or on `jni` 0.22 `Err(Error::NoClassDefFound { .. })` from `Env::find_class` (the crate clears the exception) | `FindClass` used the system loader | Use the `JNI_OnLoad` class cache, or a `Class` or `ClassLoader` from managed code |
| Corruption after passing a direct `ByteBuffer` | The Java buffer was collected while Rust held the slice | Hold a global reference to the buffer |
| `improper_ctypes_definitions` on `JNI_OnLoad` | `JavaVM` taken by value on 0.22 | Take `*mut jni::sys::JavaVM` and call `JavaVM::from_raw` |

## Hard rules

- Attach a Rust-created thread before it calls Java (`vm.attach_current_thread`).
  A thread that attached through raw `AttachCurrentThread` must detach before it
  exits, or ART aborts.
- Never hold an env or a local reference across `.await`, in a spawned task, or
  between calls. Keep a `JavaVM` clone and a global reference instead.
- Never expose a `Box::into_raw` pointer as a `jlong` handle: Java can pass any
  integer. Use a generational registry key.
- Serialize the calls on one session handle unless Rust documents it as
  thread-safe. A call that races destroy is a use-after-free.
- Wrap every loop that creates Java objects in `env.with_local_frame(n, ..)`.
  JNI guarantees 16 local references per frame; Android before 8.0 aborts on
  overflow.

## Verify

| Check | Command or action | Proves | Does not prove |
|-------|-------------------|--------|----------------|
| Crate version | `cargo tree --locked --target all -i jni --depth 0` | 0.22.2 or later, or a deliberate 0.21 | API use |
| Rust side | `cargo build --locked` for the Android target | Types, and descriptors that `native_method!` checks | That the Kotlin declaration matches |
| Exports | `llvm-nm -D --defined-only libexample_native.so \| rg 'Java_\|JNI_On'` (NDK `llvm-nm`) | The expected entry points exist | Registered names or descriptors |
| Binding | Instrumentation test that loads the library and calls each native method once | Name, descriptor, static or instance, and load order | Worker-thread paths |
| Callbacks | Instrumentation test that calls back from a Rust-created thread, with CheckJNI on | Attachment, class lookup, and reference use | R8 unless the test build is minified |

Run the device checks when the change touches a registration, an export, a
descriptor, an attach path, or R8 rules. CheckJNI is on by default on the
emulator and in a debuggable build; for a non-debuggable (R8) build, run `adb
shell setprop debug.checkjni 1` before the app starts. Run the class-lookup test
on an R8-enabled build type
([references/android-class-loading.md](references/android-class-loading.md)).

## Bind a native method

### Default: RegisterNatives from JNI_OnLoad

Register every native method in `JNI_OnLoad`. A name or descriptor mismatch
then fails the library load, not the first call. A static or instance mismatch
still registers and fails only at the first call, so the binding test must call
every method. `native_method!` checks the Rust types against the descriptor at
compile time and generates the panic guard.

Read [references/register-natives.md](references/register-natives.md) before you write or change
`JNI_OnLoad`: it has the one template. Its rules:

- Take the VM as `*mut jni::sys::JavaVM` and call `JavaVM::from_raw` once. On
  0.22, `JavaVM` by value has no stable C layout; never allow
  `improper_ctypes_definitions` crate-wide, because it finds this defect.
- Keep a raw `catch_unwind`: `with_env` is not available in `JNI_OnLoad` or
  `JNI_OnUnload`.
- Return `JNI_ERR` when any lookup or registration fails, so the load fails
  before any worker starts.

### Name-based exports

Use a name-based export only when the design needs a `Java_*` symbol. On 0.22,
never type the symbol name by hand: use `#[jni_mangle("pkg.Class")]`, or give
`native_method!` a `java_type` and the `extern` qualifier. Read
[references/java-symbol-names.md](references/java-symbol-names.md) when you
write a name-based export or debug a `No implementation found` error.

### Attributes, ABI, and panics

- A hand-written export uses `#[unsafe(no_mangle)]` (edition 2024) and
  `extern "system"`. `#![forbid(unsafe_code)]` rejects that attribute but
  passes the exports that `native_method!` or `#[jni_mangle]` generate, so it
  does not prove that a crate has no exports.
- Declare an export that takes a raw pointer `unsafe extern "system" fn` with a
  `# Safety` section; do not drop `pub` to silence `not_unsafe_ptr_arg_deref`.
- Do not write `extern "C"` for JNI: it equals `extern "system"` on Android and
  64-bit targets but differs on 32-bit Windows JVMs.
- A Rust panic that reaches an `extern "system"` function aborts the process
  (Rust 1.81+). `with_env` catches it, and `resolve` applies the error policy.
  The `rust-panic-safety` skill, when it is installed, owns the full policy; on
  0.21, wrap the body in `catch_unwind(AssertUnwindSafe(..))`.

### Java exceptions

A `call_*` method that leaves a Java exception pending returns
`Err(Error::JavaException)`, and the exception stays pending. Propagate it with
`?` to `resolve`, which hands it to the JVM, or clear it with
`env.exception_catch()` (0.22). Never drop that `Err` with `let _ =` or `.ok()`
and then make more JNI calls: most JNI calls are illegal while an exception is
pending. Throw, then return at once. Call `env.exception_check()` after a raw
`jni::sys` call.

The default `ThrowRuntimeExAndDefault` policy copies the error's `Display` text
into the exception, which reaches app logs. When that text can carry input
data, set `error_policy` on `native_method!`, or pass a fixed-message policy to
`resolve`.

Return Java `null` for a `null` `String?`, not an empty string. Read
[references/types-and-exceptions.md](references/types-and-exceptions.md) when
you map a Kotlin type, return a nullable string, throw a specific exception
class, or port exception handling between 0.21 and 0.22.

## Detail by task

- Read `references/jvm-side.md` when you write the Kotlin binding class; add,
  rename, or remove a native method; change the library name, a blocking
  behaviour, or a JSON payload; or design a `jlong` session surface.
- Read `references/jni-threading-and-callbacks.md` when a Rust-created thread
  calls Java, a native method starts async work, an env is near `.await`, a loop
  creates Java objects, or you build the load-time cache.
- Read `references/android-class-loading.md` when a Rust-created thread looks up
  an application class, or before you cache a method or field ID, enable R8 for
  a JNI surface, or test a callback.

## Hot-path data and binding choice

A `ByteArray` parameter and `JByteArray` region reads copy bytes out of the JVM
heap. Release array elements on every path. Prefer a file descriptor handed over
once as a `jint`, then a direct `ByteBuffer` (valid only while the Java buffer
stays reachable), and `JByteArray` only for control-plane payloads. Use raw
`jni` for a small handle-based surface with a hot data path, and UniFFI for a
growing API or a second platform. Do not mix both styles on one class.

- Read [references/hot-path-data.md](references/hot-path-data.md) when you map
  a direct buffer, hand over a descriptor, or touch array elements.
- Read [references/uniffi-vs-raw-jni.md](references/uniffi-vs-raw-jni.md) when
  you choose between raw JNI and UniFFI.
- Read [references/review-checklist.md](references/review-checklist.md) when
  you review a JNI diff.

The `ffi-error-progress-cancel` skill, when it is installed, owns progress and cancellation.
