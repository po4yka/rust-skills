# The JVM half of the boundary

The Kotlin class that declares the `external fun` is part of the same contract
as the Rust side. The rules for it are in [../SKILL.md](../SKILL.md); this file
holds the worked class and the session-handle contract.

```kotlin
class NativeBindings : Bindings {
    companion object {
        init {
            System.loadLibrary("example_native")
        }
    }

    private val mutex = ReentrantLock()

    override fun create(configJson: String): Long = mutex.withLock { nativeCreate(configJson) }
    override fun start(handle: Long): Int = mutex.withLock { nativeStart(handle) }
    override fun destroy(handle: Long) = mutex.withLock { nativeDestroy(handle) }

    private external fun nativeCreate(configJson: String): Long
    private external fun nativeStart(handle: Long): Int
    private external fun nativeDestroy(handle: Long)
}
```

The class name, the package, and each method's parameter and return types form
the name and descriptor that the Rust side registers or exports. Change them in
the same patch as the Rust side.

- Load the library once, from a `companion object` initializer, or from one
  shared loader object when several binding classes share one `.so`.
- Keep `external fun` declarations `private` behind a plain interface
  (`Bindings` above). Tests fake the interface; they cannot fake an
  `external fun`.

## Session-handle lifecycle

The common raw-JNI surface is a handle-based session. Write the contract down,
because the blocking behaviour of each call is part of it:

| Function | Parameters | Returns | Contract |
|----------|------------|---------|----------|
| `nativeCreate` | config `String` (often JSON) | `jlong` handle, `0` on failure | Allocates native state. |
| `nativeStart` | handle, optional `jint` fd | `jint` status or void | State whether it blocks. Blocking versus non-blocking is a compatibility contract. |
| `nativeStop` | handle | void | Graceful shutdown. Safe to call twice. |
| `nativePoll*` | handle | `String?` or array | Returns `null` when nothing is pending. Never blocks. |
| `nativeDestroy` | handle | void | Frees native state. Every later call with that handle is a bug. |

Registry rules:

- Encode a non-zero slot index and a generation in the `jlong` key. On each
  call, check the slot bounds and the generation under the registry lock before
  you access the session. Return a Java exception or the documented
  invalid-handle status when either check fails.
- On `nativeDestroy`, remove the session and increment the slot generation
  before you reuse that slot. This rejects a stale handle even when a later
  session occupies the same slot. Never issue `0`; keep it as the failure value.
- Surface setup failures as Java exceptions, not as magic return values, unless
  the return value is already documented as a status code.

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

Read [jvm-side.md](jvm-side.md) when you write the Kotlin
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
4. Run the checks in [Verify](../SKILL.md#verify).
