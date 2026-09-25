# JNI review checklist

Apply this list to a diff that touches a native method, `JNI_OnLoad`, or a
binding class. Each item is a rule from [../SKILL.md](../SKILL.md) or a
reference it links; the reason for each rule is there.

- [ ] `jni` is 0.22.2 or later, or a deliberate 0.21.
- [ ] Methods bind through `native_method!` and `RegisterNatives`, or
      `#[jni_mangle]`. New 0.22 code has no hand-typed `Java_*` name. A 0.21
      hand-typed name matches the `llvm-nm -D` output.
- [ ] Every export body is one guard. `JNI_OnLoad` takes `*mut jni::sys::JavaVM`,
      is not `pub`, and returns `JNI_ERR` on any failure.
- [ ] No discarded `Err` from `call_method`, `throw*`, or
      `attach_current_thread*` followed by another JNI call. Throw, then return,
      is correct.
- [ ] Tasks and worker threads capture a `JavaVM` clone and a global reference,
      never an env or a local reference. No `Box::leak` or `transmute` near an env.
- [ ] Application-class lookups on Rust-created threads use the load-time cache
      or an explicit loader.
- [ ] On 0.21, every attach guard is bound to a name.
- [ ] Repeated callbacks on one worker thread do not use a scoped attach.
- [ ] New worker threads are named (`thread_name_fn` or `pthread_setname_np`),
      as [jni-threading-and-callbacks.md](jni-threading-and-callbacks.md)
      describes.
- [ ] Every loop that creates Java objects runs inside `with_local_frame`.
- [ ] Hot-path bytes do not cross as `JByteArray`.
- [ ] Session-handle calls are serialized on the JVM side, and blocking
      behaviour is unchanged.
- [ ] If the platform requires the JVM to act on a native socket (for example
      `VpnService.protect`), every affected socket passes that path before first
      use.
- [ ] The `cdylib` profile keeps `panic = "unwind"` if the caller needs a Java
      exception instead of an abort.
- [ ] The minified (R8) build keeps every class and member that native code
      reaches only by name.
- [ ] Structured string payloads keep contract tests on both sides.
- [ ] The device checks from the Verify table ran when the diff changes a
      registration, an export, a descriptor, an attach path, or R8 rules.
