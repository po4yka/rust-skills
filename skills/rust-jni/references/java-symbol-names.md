# Name-based Java_ exports

Read this file when you write a name-based export, keep a hand-typed 0.21 name,
or debug `UnsatisfiedLinkError: No implementation found`. The default binding,
`RegisterNatives` from `JNI_OnLoad`, is in [../SKILL.md](../SKILL.md).

## Write the export

Use a name-based export only when the design needs a `Java_*` symbol. On 0.22,
never type the symbol name by hand: put `#[jni_mangle("pkg.Class")]` on the
function, or give `native_method!` a `java_type` and the `extern` qualifier.
The body of an export is one guard expression:

```rust
use jni::errors::ThrowRuntimeExAndDefault;
use jni::objects::JObject;
use jni::sys::jlong;
use jni::{EnvUnowned, jni_mangle};

// Exports Java_com_example_my_1app_NativeBindings_nativeDestroy.
#[jni_mangle("com.example.my_app.NativeBindings")]
pub fn native_destroy<'local>(mut env: EnvUnowned<'local>, _this: JObject<'local>, handle: jlong) {
    env.with_env(|_env| -> jni::errors::Result<()> {
        destroy_session(handle);
        Ok(())
    })
    .resolve::<ThrowRuntimeExAndDefault>()
}

fn destroy_session(_handle: jlong) {}
```

On 0.21, prefer `register_native_methods`. If a 0.21 export keeps a hand-typed
name, compare it with the `llvm-nm -D` output and with the `tried` names in the
`UnsatisfiedLinkError`.

## Name rules

These rules explain most linkage defects:

- JNI escapes `_` as `_1`, `;` as `_2`, `[` as `_3`, and every other
  non-alphanumeric UTF-16 unit as `_0xxxx`. A nested or companion class
  `Outer$Inner` becomes `Outer_00024Inner`.
- A Kotlin top-level `external fun` in `Foo.kt` belongs to the class `FooKt`,
  unless `@file:JvmName` renames it.
- An overloaded method adds `__` and the mangled argument descriptor.
- On HotSpot, a package, class, or method segment that starts with a digit `0`
  to `3` fails escaping (Java SE JNI spec) and cannot bind by name; use
  `RegisterNatives`. ART does not apply this rule.
- `javac -h` reads Java sources only. It cannot generate names for Kotlin.
