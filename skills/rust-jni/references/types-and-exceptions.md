# JNI types and Java exceptions

Lookup material for the Kotlin-to-Rust boundary. The rules that decide a review
are in [../SKILL.md](../SKILL.md).

## Type mapping

| Kotlin / Java | JNI type | Rust with the `jni` crate | Rust with UniFFI |
|---------------|----------|---------------------------|------------------|
| `Int` | `jint` | `jint` (`i32`) | `i32` |
| `Long` | `jlong` | `jlong` (`i64`) | `i64` |
| `Boolean` | `jboolean` | `jboolean` (`u8`) | `bool` |
| `String` | `jstring` | 0.22: `s.mutf8_chars(env)?.to_str()`; 0.21: `env.get_string(&s)?` | `String` |
| `String?` | `jstring` | return `std::ptr::null_mut()` for `None` | `Option<String>` |
| `ByteArray` | `jbyteArray` | `JByteArray` -> `Vec<u8>`; 0.21 uses `env.convert_byte_array` | `Vec<u8>` |
| `LongArray` | `jlongArray` | `JLongArray` | `Vec<i64>` |
| `Array<String>` | `jobjectArray` | `JObjectArray<JString>`, one element per `set_element` | `Vec<String>` |

Return a new Java string with `env.new_string(text)?.into_raw()`. The raw
`jstring` is what the extern function returns; `null_mut()` is the Java `null`.

Version note: `jni` 0.22 moved several helpers from the env onto the object
types (`JString::mutf8_chars` replaces `env.get_string`, for example). Confirm
the method against the docs of the version in your lockfile.

## Throw a Java exception

```rust
use jni::strings::JNIString;

// jni 0.22: the class name and the message are JNIString values.
let class = JNIString::new("java/io/IOException");
let message = JNIString::new(&err.to_string());
match env.throw_new(class.borrowed(), message.borrowed()) {
    Ok(()) | Err(jni::errors::Error::JavaException) => {}
    Err(other) => log::error!("failed to throw IOException: {other}"),
}

// jni 0.21: both arguments accept &str.
let _ = env.throw_new("java/io/IOException", err.to_string());
```

Return a default value in the same arm. The exception becomes visible to the
JVM only after the native function returns. After you call any Java method from
Rust, check `env.exception_check()` before you use the result; a pending
exception makes most later JNI calls illegal. To read and clear a pending
exception, use `env.exception_occurred()` and `env.exception_clear()`.

Strip internal detail from the message in release builds. An exception message
crosses into the app and can reach a log or a bug report:

```rust
fn user_message(detail: &str, user_message: &str) -> String {
    if cfg!(debug_assertions) {
        format!("{user_message}: {detail}")
    } else {
        user_message.to_string()
    }
}
```

