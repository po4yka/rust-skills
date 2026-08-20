# The JVM half of the boundary

The Kotlin class that declares the `external fun` is part of the same contract as the
Rust export. The symbol name is derived from this class character for character, so the
two files change together or the app fails at run time with `UnsatisfiedLinkError`.

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

Rules for this side:

- Load the library exactly once, from a `companion object` initializer or a
  shared loader object. A loader object is better when several binding classes
  share one `.so`.
- Keep the `external fun` declarations `private` and expose a plain interface.
  The interface is what tests fake; the `external fun` cannot be faked.
- Serialize every call that touches a session handle (`mutex.withLock`) unless
  the Rust side documents itself as thread-safe for that handle. A use-after-free
  of a handle is a native abort, not an exception.
