# jni 0.21 and 0.22 side by side

Read this file when the lockfile holds `jni` 0.21, or when you port code or a
snippet between 0.21 and 0.22. The snippets in [../SKILL.md](../SKILL.md) use
0.22. Code for 0.21 does not compile on 0.22.

| Task | `jni` 0.21 | `jni` 0.22 |
|------|------------|------------|
| Owned VM handle for a worker | `Arc<JavaVM>`; clone the `Arc` | `JavaVM`; clone the handle |
| Env type inside a call | `JNIEnv<'local>` | `Env<'local>` |
| Env type in an export signature | `JNIEnv<'local>` | `EnvUnowned<'local>` |
| Bind a native method | `env.register_native_methods` with hand-built `NativeMethod` entries, or a hand-written `Java_*` export | `native_method!` plus `register_native_methods`, or `#[jni_mangle("pkg.Class")]` |
| Panic guard | `std::panic::catch_unwind` | `env.with_env(..).resolve::<P>()`; `native_method!` generates it |
| Read a `JString` | `env.get_string(&s)?.into()` | `s.mutf8_chars(env)?.to_str().into_owned()` |
| Stay attached for the thread's life | `vm.attach_current_thread_permanently()?` | `vm.attach_current_thread(closure)` |
| Attach for one scope only | `let mut guard = vm.attach_current_thread()?` | `vm.attach_current_thread_for_scope(closure)` |
| Global reference | `GlobalRef` | `Global<JObject<'static>>` |
| Pending Java exception | `call_*` returns `Err(JavaException)`; `throw_new` returns `Ok` | `throw*` also returns `Err(JavaException)`; lookups map it to a typed error; attach returns an exception that its closure leaves pending as `CaughtJavaException` |
| Method name and signature | `&str` literals | `jni_str!` and `jni_sig!` |
| `jboolean` | `u8` | `bool` |

## Owned handles on 0.21

`JavaVM` on 0.21 is `Send + Sync`, but not `Clone`. Put the captured handle in
an `Arc` before workers share it. Calling `clone()` on `&JavaVM` only copies
the reference; it does not make an owned handle:

```rust
use std::sync::Arc;

fn worker_handle(vm: &Arc<jni::JavaVM>) -> Arc<jni::JavaVM> {
    Arc::clone(vm)
}
```

This block type-checks against jni 0.21. It does not attach a thread or prove
that the JVM outlives a worker. Join attached workers before JVM shutdown.
On 0.22, `JavaVM::clone()` supplies an owned handle directly.

Keep one `jni` version in the crate graph. Two copies do not share
`JavaVM::singleton()` or attach state.

The 0.21 attach-guard mistakes are in
[jni-threading-and-callbacks.md](jni-threading-and-callbacks.md). The 0.21
hand-typed export name check is in
[java-symbol-names.md](java-symbol-names.md). The `rust-panic-safety` skill,
when it is installed, has the 0.21 panic-guard form: `catch_unwind(AssertUnwindSafe(..))`
around the whole export body.
