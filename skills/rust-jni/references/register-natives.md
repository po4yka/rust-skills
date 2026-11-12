# RegisterNatives from JNI_OnLoad: the template

Deep material for `rust-jni`, "Bind a native method". This is the one `JNI_OnLoad` template, for
`jni` 0.22. SKILL.md holds its rules; this file holds the code and the detail behind them.

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

/// # Safety
/// Only the JVM calls this, with a valid `JavaVM` pointer.
#[unsafe(no_mangle)]
pub unsafe extern "system" fn JNI_OnLoad(raw_vm: *mut jni::sys::JavaVM, _reserved: *mut c_void) -> jint {
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
        // A payload's Drop can panic again; JNI_OnLoad runs once, so leak it.
        Err(payload) => {
            let _leaked = std::mem::ManuallyDrop::new(payload);
            JNI_ERR
        }
    }
}
```

`JavaVM::from_raw` also seeds `JavaVM::singleton()`, so call it once, here.
