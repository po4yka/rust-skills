# JNI threading and callbacks

Deep material for calling from Rust threads back into the JVM. The summary
rules are in [../SKILL.md](../SKILL.md); this file holds the lifetimes, the
destructor pattern, and the two callback wirings.

## Capture the JavaVM once

The env handle (`Env` on `jni` 0.22, `JNIEnv` on 0.21) is per-thread and
frame-scoped. `JavaVM` is process-wide and `Clone + Send + Sync`. Store the `JavaVM` at
library load time and derive an env from it on every thread that needs one:

```rust
use std::sync::OnceLock;
use jni::{JavaVM, sys::{jint, JNI_VERSION_1_6}};

static JVM: OnceLock<JavaVM> = OnceLock::new();

#[unsafe(no_mangle)]
#[allow(improper_ctypes_definitions)]
pub extern "system" fn JNI_OnLoad(vm: JavaVM, _reserved: *mut std::ffi::c_void) -> jint {
    match std::panic::catch_unwind(|| {
        let _ = JVM.set(vm);
        install_panic_hook();
        init_logging();
        JNI_VERSION_1_6
    }) {
        Ok(version) => version,
        Err(_) => jni::sys::JNI_ERR,
    }
}
```

`JNI_OnLoad` receives a `JavaVM`, not an env handle, so `EnvUnowned::with_env`
is not available there. Use raw `catch_unwind`. A panic that escapes this
function aborts the process, exactly like any other panic that reaches an
`extern "system"` export.

Do the one-time setup here: store the `JavaVM`, install the panic hook,
initialize logging, and apply any process-wide signal setup (`SIGPIPE`, for
example).

If another part of the crate needs its own handle, call `vm.clone()`.
`jni::JavaVM` is `Clone + Send + Sync`, it is one pointer wide, and it has no
`Drop`, so a clone can never reach `DestroyJavaVM`. Do not rebuild the handle
with `unsafe { JavaVM::from_raw(vm.get_raw()) }`: the safe `Clone` impl already
does it, and an `Arc` around a pointer-sized handle only adds an indirection.

## Attach and detach

The API differs by crate version. Pick the form that matches your lockfile.

### jni 0.22: attach with a closure

```rust
let vm = JVM.get().expect("JNI_OnLoad must populate JVM");

// Long-lived worker: attach once. The thread-local guard detaches at thread
// exit, and later calls take the cheap "already attached" path.
let count: Result<i32, jni::errors::Error> =
    vm.attach_current_thread(|env| -> jni::errors::Result<i32> {
        env.call_method(
            &listener,
            jni::jni_str!("onUpdate"),
            jni::jni_sig!("(I)I"),
            &[jni::objects::JValue::Int(update)],
        )?
        .i()
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
| Occasional one-shot callback | `attach_current_thread_for_scope` | The thread is never left attached, so it cannot block JVM teardown. |
| Occasional callback on a pooled thread that keeps running | `attach_current_thread` | A scoped attach on a reused thread pays the attach cost every call. |

`jni` 0.22 has no daemon attach variant.

### jni 0.21: bind the RAII guard

```rust
let vm = JVM.get().expect("JNI_OnLoad must populate JVM");
let _guard = vm.attach_current_thread()?;   // RAII guard
let env = _guard.deref_mut();               // &mut JNIEnv
env.call_method(&listener, "onUpdate", "(I)V", &[update.into()])?;
// Drop of `_guard` calls DetachCurrentThread.
```

Failure modes:

| Mistake | Result |
|---------|--------|
| `vm.attach_current_thread()?;` with no binding | The temporary guard drops at the end of the statement. The thread is detached before the next JNI call. |
| `let _ = vm.attach_current_thread()?;` | Same. `let _` drops immediately; it is not a binding. |
| Thread exits while attached | `JNI WARNING: native thread exiting without DetachCurrentThread`, and a fatal abort on some Android configurations. |
| Attaching per call in a hot loop | Roughly 5-15 microseconds each on Android. Attach once for the life of the worker instead. |

For a long-lived worker that makes many JNI calls on 0.21, use
`attach_current_thread_as_daemon`. A daemon attachment does not block JVM
shutdown while the thread is still running.

## Pure pthread workers

If a worker is a raw pthread that you do not own the exit path of, register a
thread-local destructor that detaches:

```rust
// Once at startup.
let mut key: libc::pthread_key_t = 0;
unsafe { libc::pthread_key_create(&mut key, Some(detach_destructor)) };
// `detach_destructor` calls vm.detach_current_thread().
```

Set a non-null value for that key on each worker thread after it attaches, so
the destructor runs at thread exit.

Tokio worker threads do not need this. On 0.22 the attach closure owns the
detach; on 0.21 bind the `AttachGuard` inside the task or the worker closure and
let `Drop` do the work.

## Callback from an async task

The task must not capture an env handle. It captures a `JavaVM` clone and a
global reference, and attaches when it is ready to report:

```rust
// jni 0.22.
fn handle(env: &mut Env<'_>, vm: JavaVM, listener: Global<JObject<'static>>) {
    let payload = extract_payload(env); // synchronous use of env

    tokio::spawn(async move {
        do_async_work(&payload).await;
        let _ = vm.attach_current_thread_for_scope(|env| -> jni::errors::Result<()> {
            env.call_method(&listener, jni::jni_str!("onComplete"), jni::jni_sig!("()V"), &[])?;
            Ok(())
        });
    });
}
```

Rules:

- Create the global reference on the JVM thread that received the listener
  object, with `env.new_global_ref(obj)`. A local reference is invalid outside
  its frame.
- Drop the global reference when the session is destroyed. A leaked global
  reference pins the Java object for the life of the process.
- Wrap the global-reference handle in a type that is not `Copy`. A `Copy`
  wrapper lets safe code drop `DeleteGlobalRef` twice.
- Wrap the callback in a local frame if it creates JNI objects in a loop.
- Never `unwrap` a JNI error in a path that can run during shutdown. The JVM may
  already be detaching the thread.

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
on success.

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

Cost: the attachment alone is roughly 5-15 microseconds on Android. Acceptable
for control-plane sockets. Unacceptable for per-flow socket creation at scale.

## Name every thread

An unnamed worker appears as `Thread-42` in logcat and in a tombstone. That
makes a native crash much harder to attribute. Name threads at creation:

```rust
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
