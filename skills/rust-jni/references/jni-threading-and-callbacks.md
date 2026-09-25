# JNI threading and callbacks

Deep material for calling from Rust threads back into the JVM. The summary
rules are in [../SKILL.md](../SKILL.md).

Contents:

- Build the load-time cache
- Attach and detach
- Threads attached outside the crate
- Callback from an async task
- Ask the JVM to act on a native socket
- Local reference frames
- Name every thread

## Build the load-time cache

The env handle (`Env` on `jni` 0.22, `JNIEnv` on 0.21) is per-thread and
frame-scoped. `JavaVM` is process-wide, `Clone + Send + Sync`, one pointer wide,
and has no `Drop`. Store it in the same immutable cache as the global classes
and IDs, and publish that cache once:

```rust
use std::sync::OnceLock;

use jni::{
    Env, JavaVM, NativeMethod, jni_sig, jni_str, native_method,
    objects::{Global, JClass, JMethodID},
    sys::jint,
};

struct JniCache {
    vm: JavaVM,
    listener_class: Global<JClass<'static>>,
    on_update: JMethodID,
}

static JNI_CACHE: OnceLock<JniCache> = OnceLock::new();

const PING_METHOD: NativeMethod = native_method! {
    static fn native_ping() -> jint,
};

fn native_ping<'local>(
    _env: &mut Env<'local>,
    _class: JClass<'local>,
) -> jni::errors::Result<jint> {
    Ok(1)
}

fn build_cache(vm: &JavaVM) -> jni::errors::Result<JniCache> {
    vm.with_local_frame(16, |env| {
        let listener = env.find_class(jni_str!("com/example/app/NativeListener"))?;
        let on_update = env.get_method_id(
            &listener,
            jni_str!("onUpdate"),
            jni_sig!("(I)V"),
        )?;
        let listener_class = env.new_global_ref(&listener)?;

        let bindings = env.find_class(jni_str!("com/example/app/NativeBindings"))?;
        // SAFETY: `native_method!` checked the descriptor, and nativePing is a
        // static method of NativeBindings.
        unsafe { env.register_native_methods(&bindings, &[PING_METHOD])? };

        Ok(JniCache {
            vm: vm.clone(),
            listener_class,
            on_update,
        })
    })
}

fn publish_cache(vm: &JavaVM) -> jni::errors::Result<()> {
    let cache = build_cache(vm)?;
    // `set` fails only when the library loads twice in one process: fail that load.
    JNI_CACHE
        .set(cache)
        .map_err(|_| jni::errors::Error::FieldAlreadySet("JNI_CACHE".to_owned()))
}
```

Use the `JNI_OnLoad` template in [../SKILL.md](../SKILL.md). Replace the
`vm.with_local_frame(..)` expression in its closure with `publish_cache(&vm)`.
The template then logs a failed lookup, returns `JNI_ERR` for any error or
panic, and returns `JNI_VERSION_1_6` only after the cache is published.

Build all global references and IDs in a local `JniCache`. Register all native
methods. Run any fallible logger or process setup in the same builder. Call
`OnceLock::set` once, check its result, and return success only after it
succeeds. An error before publication drops the local cache and its global
references.

Other code gets a VM handle from the cache with `vm.clone()`, or from
`JavaVM::singleton()` on 0.22.

## Attach and detach

The API differs by crate version. Pick the form that matches your lockfile.

### jni 0.22: attach with a closure

```rust
let vm = &JNI_CACHE.get().expect("JNI_OnLoad must populate JNI_CACHE").vm;

// Long-lived worker: attach once. The crate detaches at thread exit, and later
// calls take the cheap "already attached" path.
let updated: Result<(), jni::errors::Error> =
    vm.attach_current_thread(|env| -> jni::errors::Result<()> {
        env.call_method(
            &listener,
            jni::jni_str!("onUpdate"),
            jni::jni_sig!("(I)V"),
            &[jni::objects::JValue::Int(update)],
        )?
        .v()
    });

// One-shot caller: detach as soon as the closure returns.
let ok: Result<bool, jni::errors::Error> =
    vm.attach_current_thread_for_scope(|env| -> jni::errors::Result<bool> {
        env.call_method(&service, jni::jni_str!("isReady"), jni::jni_sig!("()Z"), &[])?.z()
    });
```

Choose between the two by call rate:

| Worker shape | Form | Reason |
|--------------|------|--------|
| Dedicated thread, many callbacks | `attach_current_thread` | One attach for the life of the thread. |
| Occasional one-shot callback on a thread you do not reuse | `attach_current_thread_for_scope` | The thread is never left attached, so it cannot block JVM exit. |
| Occasional callback on a pooled thread that keeps running | `attach_current_thread` | A scoped attach on a reused thread pays attach and detach every call. |

Each 0.22 attach call pushes a new local frame for the closure, so references
that the closure creates do not pile up in the thread's base frame. An exception
that the closure leaves pending is cleared and returned as
`Error::CaughtJavaException`. `jni` 0.22 has no daemon attachment, so a
permanent attachment can block `DestroyJavaVM` on a desktop or server JVM. The
`java` launcher calls `DestroyJavaVM` after `main` returns, and it waits for
every non-daemon thread. Shut down the Rust runtime
(`Runtime::shutdown_timeout`) and join every attached thread before `main`
returns. Android never destroys the VM.

### jni 0.21: bind the RAII guard

```rust
let vm = &JNI_CACHE.get().expect("JNI_OnLoad must populate JNI_CACHE").vm;
let _guard = vm.attach_current_thread()?;   // RAII guard
let env = _guard.deref_mut();               // &mut JNIEnv
env.call_method(&listener, "onUpdate", "(I)V", &[update.into()])?;
// Drop of `_guard` calls DetachCurrentThread.
```

| Mistake | Result |
|---------|--------|
| `vm.attach_current_thread()?;` with no binding | The temporary guard drops at the end of the statement. The thread is detached before the next JNI call. |
| `let _ = vm.attach_current_thread()?;` | Same. `let _` drops immediately; it is not a binding. |
| A scoped guard per call in a hot loop | Each call pays attach and detach. Attach once for the life of the worker instead. |

For a long-lived worker on 0.21, use `attach_current_thread_permanently`. The
crate detaches that thread at exit. Do not use `attach_current_thread_as_daemon`:
0.22 removed it because its semantics are poorly defined. A move from daemon to
permanent attachment can make a desktop or server JVM hang at exit; apply the
exit rule above.

## Threads attached outside the crate

Both crate versions detach a thread that attached through the crate's API. Do
not add a second detach for those threads.

ART logs these lines at exit for a thread that is still attached:

```text
Native thread exiting without having called DetachCurrentThread (maybe it's going to use a pthread_key_create destructor?)
Native thread exited without calling DetachCurrentThread
```

The first line is a warning: a thread-local destructor can still detach the
thread after it. The second line is `FATAL` and aborts the process on every
Android configuration.

A thread that C or C++ code attached through raw `AttachCurrentThread` must
detach itself. If that code cannot control the thread's exit path, it registers
a `pthread_key_create` destructor that calls `DetachCurrentThread`, and sets a
non-null key value on each attached thread so that the destructor runs. This is
the pattern the Android JNI tips describe. Prefer the crate API for every thread
that Rust owns.

## Callback from an async task

Use the env synchronously, extract owned data, then spawn. A JVM thread that
calls a native method is not a Tokio runtime thread, so spawn through a
`Handle` that the load-time cache holds. The task captures a `JavaVM` clone and
a global reference:

```rust
use jni::objects::{Global, JObject};
use jni::{Env, JavaVM};
use tokio::runtime::Handle;

fn handle(env: &mut Env<'_>, rt: &Handle, vm: JavaVM, listener: Global<JObject<'static>>) {
    let payload = extract_payload(env); // synchronous use of env

    rt.spawn(async move {
        do_async_work(&payload).await;
        // Tokio reuses worker threads: attach permanently, once per worker.
        let result = vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            env.call_method(&listener, jni::jni_str!("onComplete"), jni::jni_sig!("()V"), &[])?;
            Ok(())
        });
        if let Err(error) = result {
            log::warn!("onComplete callback failed: {error}");
        }
    });
}

fn extract_payload(_env: &mut Env<'_>) -> String {
    todo!()
}

async fn do_async_work(_payload: &str) {}
```

Log the callback error; do not `unwrap` it. The JVM may already be tearing the
thread down during shutdown. Rules for the global reference:

- Create it on the JVM thread that received the listener object, with
  `env.new_global_ref(obj)`. A local reference is invalid outside its frame.
- Drop it when the session is destroyed. A leaked global reference pins the Java
  object for the life of the process.
- Wrap a raw global-reference handle in a type that is not `Copy`. A `Copy`
  wrapper lets safe code call `DeleteGlobalRef` twice.
- Wrap the callback in a local frame if it creates JNI objects in a loop.

## Ask the JVM to act on a native socket

Some platform APIs can only be called from Java, but the file descriptor lives
in Rust. `VpnService.protect(fd)` on Android is the common case: every socket
that must bypass the tunnel has to be handed to the JVM first. Two wirings both
work. Choose by call rate.

### Option A: pass the fd over a Unix socket with SCM_RIGHTS

Preferred when many sockets need the operation. The JVM side listens on a known
abstract socket name. Rust connects, sends the fd as ancillary data, and reads a
one-byte status reply. No JNI call and no thread attachment on the Rust path.

```rust
use nix::sys::socket::*;

fn protect_socket(uds: &mut UnixStream, fd: RawFd) -> io::Result<()> {
    let cmsg = [ControlMessage::ScmRights(&[fd])];
    sendmsg::<UnixAddr>(
        uds.as_raw_fd(),
        &[IoSlice::new(b"P")],
        &cmsg,
        MsgFlags::empty(),
        None,
    )?;
    let mut reply = [0u8; 1];
    uds.read_exact(&mut reply)?;
    if reply[0] == b'1' {
        Ok(())
    } else {
        Err(io::Error::other("protect denied"))
    }
}
```

The JVM side reads the descriptor, performs the platform call, and replies `'1'`
on success. An abstract socket name has no filesystem permission, so any local
process can connect to it. Before it calls `protect`, the JVM side accepts only
a peer with `socket.peerCredentials.uid == android.os.Process.myUid()` and
closes every other connection.

### Option B: direct JNI callback

Simpler when the operation is rare, for example one resolver socket or one
outbound connection per session.

```rust
// jni 0.22. A scoped attach: this thread is not left attached after the call.
fn protect_socket(
    vm: &JavaVM,
    service: &Global<JObject<'static>>,
    fd: RawFd,
) -> io::Result<()> {
    let result = vm.attach_current_thread_for_scope(|env| -> jni::errors::Result<bool> {
        env.call_method(
            service,
            jni::jni_str!("protect"),
            jni::jni_sig!("(I)Z"),
            &[jni::objects::JValue::Int(fd)],
        )?
        .z()
    });

    match result {
        Ok(true) => Ok(()),
        Ok(false) => Err(io::Error::new(io::ErrorKind::PermissionDenied, "protect returned false")),
        Err(error) => Err(io::Error::other(error.to_string())),
    }
}
```

A scoped attach pays attach and detach on every call. That is acceptable for
control-plane sockets. Measure it before you use it for per-flow sockets.

## Local reference frames

Every `env.find_class`, `env.get_field`, `env.new_string`, and `env.call_method`
that returns a `JObject` consumes a local-reference slot. The JNI specification
guarantees only 16 slots per frame. Android before 8.0 (API < 26) caps the table
and aborts on overflow; Android 8.0 and later has no cap, so a leak shows as
memory growth. Do not assume the current frame holds more than 16; push your own
frame with the capacity you need.

```rust
// BAD: one local ref per iteration, all held until the native method returns.
for client in &clients {
    let s = env.new_string(&client.host)?;
    notify_listener(env, s)?;
}

// GOOD: each iteration gets its own frame; refs drop when the frame exits.
for client in &clients {
    env.with_local_frame::<_, (), jni::errors::Error>(32, |env| {
        let s = env.new_string(&client.host)?;
        notify_listener(env, s)?;
        Ok(())
    })?;
}
```

Wrap every loop that creates JNI objects. When the loop fills an array or an
object that must outlive the loop, create that object in the outer frame and
wrap only the loop body; a reference created inside the frame dies when the
frame pops. Size the frame at the number of local references that one iteration
creates, plus a small margin for the references the JNI calls allocate
internally.

For a single object with a short scope, `obj.auto()` (`jni` 0.22),
`env.auto_local(obj)` (0.21), or an explicit `delete_local_ref` is enough.

## Name every thread

An unnamed worker appears as `Thread-42` in logcat and in a tombstone. That
makes a native crash much harder to attribute. Name threads at creation:

```rust
use std::sync::atomic::{AtomicUsize, Ordering};

let runtime = tokio::runtime::Builder::new_multi_thread()
    .worker_threads(2)
    .thread_name_fn(|| {
        static N: AtomicUsize = AtomicUsize::new(0);
        format!("example-tokio-{}", N.fetch_add(1, Ordering::Relaxed))
    })
    .enable_all()
    .build()?;
```

For threads you spawn yourself, use `std::thread::Builder::new().name("...")`.
For a thread created outside Rust, set the name with `pthread_setname_np` on
Linux and Android. The Linux limit is 15 characters plus the terminator; a
longer name is rejected, so keep the prefix short.
