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
