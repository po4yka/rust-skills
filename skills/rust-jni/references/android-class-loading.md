# Android class loading from Rust threads

Read this reference when Rust must resolve or call an application class from a
thread that Rust created. Thread attachment and detachment stay in
[jni-threading-and-callbacks.md](jni-threading-and-callbacks.md).

## Why `FindClass` fails

`FindClass` normally uses the loader of the managed method at the top of the
Java stack. A newly attached native thread has no application method on that
stack. Android uses the system class loader instead. The system loader cannot
see application classes.

`JNI_OnLoad` is the useful exception. Android resolves its `FindClass` calls in
the context of the loader that called `System.loadLibrary`. Load the library
from the application binding class or from the application initializer. Do not
defer required application-class lookup to the first worker callback.

The Android NDK documents this behavior in
[JNI tips](https://developer.android.com/ndk/guides/jni-tips#faq:-why-didnt-findclass-find-my-class).

## Build one complete startup cache

Use this order for stable base-application classes:

1. Get an env for `JNI_VERSION_1_6` inside `JNI_OnLoad`.
2. Resolve every required class with its internal slash name, such as
   `com/example/app/NativeListener`.
3. Promote each local class reference to a global reference.
4. Resolve every required method and field ID from the matching class.
5. Register all native methods.
6. Build the complete cache in a local value. Publish it only after all steps
   succeed.
7. Return `JNI_VERSION_1_6` only after publication. Return `JNI_ERR` on any
   error or panic.

Do not fill several process globals one at a time. A late error can otherwise
leave a partial cache visible to another callback. Store one cache value in
the same process-lifetime cell that the bridge already uses.

The cache can contain these values:

| Value | `jni` 0.21 | `jni` 0.22 | Rule |
|-------|------------|------------|------|
| JVM handle | `JavaVM` | `JavaVM` | Clone it for a worker. |
| Application class | `GlobalRef` | `Global<JClass<'static>>` | Keep the strong global reference for as long as any cached ID is used. |
| Instance method ID | `JMethodID` | `JMethodID` | Resolve it with `get_method_id`. Do not pair it with another class. |
| Static method ID | `JStaticMethodID` | `JStaticMethodID` | Resolve it with `get_static_method_id`. |
| Instance field ID | `JFieldID` | `JFieldID` | Resolve it with `get_field_id`. Do not use it for a static field. |
| Static field ID | `JStaticFieldID` | `JStaticFieldID` | Resolve it with `get_static_field_id`. |

Never store `JNIEnv`, `Env`, `EnvUnowned`, `JClass<'local>`, or another local
reference. An env belongs to one thread. A local class reference belongs to
one native frame. Neither becomes valid for a worker because it sits in a
static variable.

Method and field IDs stay valid while their defining class stays loaded. The
strong global class reference in the same cache keeps the class and its loader
alive. Drop or replace the cache before you permit that loader to unload.

### Version-specific lookup

On `jni` 0.21, use `JNIEnv::find_class`, `JNIEnv::new_global_ref`,
`JNIEnv::get_method_id`, and the matching instance or static ID lookup. The
stored class type is `GlobalRef`. Pass `&GlobalRef` to an API that expects
`Desc<JClass>`. Use `global.as_obj()` only when an API expects `JObject`.

On `jni` 0.22, use `Env::find_class`, `Env::new_global_ref`,
and the matching instance or static method or field ID lookup. The stored class
type is `Global<JClass<'static>>`. Keep the outer `catch_unwind` around
`JNI_OnLoad`; `EnvUnowned::with_env` is not available there.

`jni` 0.22 also provides `Env::load_class` and `LoaderContext`. These APIs can
consult a thread context loader. Do not treat that as proof that a newly
attached Rust thread has the application loader. Use
`LoaderContext::Loader` with the explicit cached loader when loader identity
matters.

## Dynamic features and custom loaders

Do not put a dynamic-feature class in the base `JNI_OnLoad` cache. The feature
can be absent when the base library loads, and a global class reference can
prevent its loader from being collected.

Choose one of these explicit contracts:

| Contract | Use when | Native action |
|----------|----------|---------------|
| Pass `Class<*>` to native initialization | One or a few feature classes are required | Promote the supplied `Class` to a global reference and resolve IDs from it. |
| Pass the feature `ClassLoader` | Rust must resolve several names owned by one loader | Promote the loader to a global reference and call `ClassLoader.loadClass` with dotted binary names. |
| Run `nativeInit` from the class static initializer | A loader can unload and later load the class again | Rebuild that loader's class and ID cache each time the managed class initializes. |

On `jni` 0.22, wrap the explicit loader with `LoaderContext::Loader` and call
`load_class`. On `jni` 0.21, invoke `ClassLoader.loadClass` through
`call_method`. Do not fall back to the system loader when the explicit loader
fails. Report the load error with the requested binary name and stop that
feature initialization.

Do not use a process-only `OnceLock` for a cache that must follow loader reload.
Define who replaces the cache and who proves that no callback still uses the
old IDs. If the application never unloads the loader, keep the simpler
process-lifetime cache.

## Preserve names through R8

R8 cannot infer a class, method, or field that native code reaches only by a
string. Add the narrowest keep rule for those exact classes and members. Put a
consumer rule in an AAR when the JNI library is distributed as an Android
library. Do not keep the whole application package.

Run the lookup test against an R8-enabled test build type. A normal debug test
does not prove that string-only members survive shrinking or obfuscation. Treat
a missing class, method, or field during `JNI_OnLoad` as a load failure. Do not
continue with a reduced cache.

## Test the supported worker path

Add one Android instrumentation test that executes the real release bridge:

1. Load the native library. Assert that load succeeds before the test starts a
   worker.
2. Pass a listener object to Rust. Promote it to a global reference.
3. Start a new `std::thread` or the real Rust worker path.
4. Attach that thread with the form required by the locked `jni` version.
5. Invoke a cached method ID on the listener, or resolve a second application
   class through the explicit cached loader and invoke it.
6. Signal a managed latch from the callback. Fail on timeout or on a pending
   Java exception.
7. Run with CheckJNI enabled on an emulator or device.

Create or reuse a build type that enables R8 and can run instrumentation. Set
the module `testBuildType` to its name. A usual name is `minified`; do not assume
that the non-debuggable or unsigned `release` build has an instrumentation task.
Discover the exact task, then run the task that Gradle reports:

```bash
./gradlew tasks --all | rg 'connected.*AndroidTest'
./gradlew connectedMinifiedAndroidTest
```

If the application uses a dynamic feature, install that feature before its
test and exercise the feature loader contract separately.

## Failure triage

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ClassNotFoundException` only on a Rust-created thread | Direct `FindClass` selected the system loader | Use the startup cache or an explicit application loader. |
| Library load fails after a package rename | `JNI_OnLoad` still uses the old internal class name | Update the lookup and managed declaration in one patch. Keep the early failure. |
| Release fails but debug passes | R8 removed or renamed a string-only class or member | Add a narrow keep rule and run the minified instrumentation test. |
| Callback calls the wrong overload | Cached descriptor does not match the managed declaration | Regenerate the descriptor and fail initialization when ID lookup fails. |
| Dynamic feature cannot unload | A process-lifetime global reference pins its class loader | Move that class to a feature-owned cache with explicit teardown or reload. |
| Intermittent crash after feature reload | A callback retained an ID from the old class | Stop old callbacks before replacing the class and ID cache. |
