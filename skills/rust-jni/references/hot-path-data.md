# Hot-path data across JNI

Deep material for moving bytes between the JVM and Rust. The decision rule is in
[../SKILL.md](../SKILL.md); this file holds the code and the safety arguments.

## Rank the options by copy count

| Option | Copies per payload | Use it for |
|--------|--------------------|------------|
| File-descriptor handoff | 0 | A stream that Rust owns for the life of the session. |
| DirectByteBuffer | 0 | Bytes that must transit, at a rate that makes a copy visible. |
| `JByteArray` | 1 each way | Control-plane payloads: configuration, a report, a command. |

## File-descriptor handoff

Transfer ownership of the descriptor once, as a `jint`, at session start. Rust
then reads and writes the device or the socket directly, and the payload never
crosses JNI again. This is the only option that removes the boundary from the
data path completely.

Rules:

- Duplicate the descriptor (for example with `nix::unistd::dup`) before you use
  it asynchronously. The JVM side can close or revoke the original.
- Document who closes the descriptor. A double close is a hard-to-attribute
  failure in an unrelated part of the process, because the number is reused.
- Do not send the same descriptor twice. Send it at create or at start, and
  make every later call use the handle instead.

## DirectByteBuffer

Allocate the buffer with `ByteBuffer.allocateDirect` on the JVM side, then map
the address in Rust:

```rust
use jni::objects::JByteBuffer;
use jni::Env;

// The accessor names are the same on 0.21 and 0.22. On 0.22 both are safe
// functions; only the slice construction needs an `unsafe` block.
fn map_direct_buffer<'a>(env: &Env<'_>, buf: &JByteBuffer<'_>) -> jni::errors::Result<&'a [u8]> {
    let ptr = env.get_direct_buffer_address(buf)?;
    let len = env.get_direct_buffer_capacity(buf)?;
    // SAFETY: ptr and len come from the JVM for a direct buffer whose Java-side
    // reference outlives this slice; no other thread writes it concurrently.
    Ok(unsafe { std::slice::from_raw_parts(ptr, len) })
}
```

The returned lifetime is unbounded, which is the whole hazard in one signature: nothing ties
the slice to the Java reference. Give the wrapper a lifetime that comes from an owner you
control before you expose it.

The memory belongs to the JVM. The slice is valid only while a Java reference to
that buffer is alive. If Rust holds the slice past the current call, hold a
global reference to the buffer for exactly as long as the slice lives, and drop
both together.

The `no other thread writes it concurrently` half of that SAFETY comment is a
contract with the JVM side, not something Rust can check. Write it down in the
binding class as well: state which side owns the buffer between calls.

## JByteArray

The byte-array accessors copy the whole array between the JVM heap and native
memory. That cost is irrelevant for a call that happens once per session and
decisive for a call that happens per packet.

```rust
use jni::objects::JByteArray;
use jni::Env;

// Acceptable for control-plane payloads. The accessor is the same on 0.21.
fn read_control_payload(env: &Env<'_>, array: &JByteArray<'_>) -> jni::errors::Result<()> {
    let bytes = env.convert_byte_array(array)?;
    process_config(&bytes);
    Ok(())
}

fn process_config(_bytes: &[u8]) {}
```

If a per-packet path already uses `JByteArray`, treat the change to a descriptor
handoff or a direct buffer as a throughput fix, not a style fix. The copy
couples throughput to the boundary.
