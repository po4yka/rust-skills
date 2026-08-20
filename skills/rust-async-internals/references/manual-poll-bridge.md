# Manual Poll Bridge

Reference material for `SKILL.md`. Read it when you drive tokio streams from a
synchronous, step-driven loop, or when you drive an io_uring backend from that
loop.

## The pattern

Some designs pair a synchronous, step-driven engine (a userspace protocol
stack, a simulation tick loop, a hardware poll loop) with waker-driven tokio
tasks. The two schedulers do not share a waker. The bridge is a manual poll
with a no-op waker.

```rust
pub(super) struct NoopWaker;

impl std::task::Wake for NoopWaker {
    fn wake(self: Arc<Self>) {}
    fn wake_by_ref(self: &Arc<Self>) {}
}

pub(super) fn try_read_duplex(
    stream: &mut tokio::io::DuplexStream,
    buf: &mut [u8],
) -> Option<io::Result<usize>> {
    let waker = Waker::from(Arc::new(NoopWaker));
    let mut cx = Context::from_waker(&waker);
    let mut rb = ReadBuf::new(buf);
    match Pin::new(stream).poll_read(&mut cx, &mut rb) {
        Poll::Ready(Ok(())) => Some(Ok(rb.filled().len())),
        Poll::Ready(Err(e)) => Some(Err(e)),
        Poll::Pending => None, // the loop retries on the next tick
    }
}
```

## Why the waker does nothing

The `try_*` functions run inside the synchronous loop tick, not inside a tokio
task. A real waker would register a wake-up that points at a context which no
longer exists when the wake fires. That is safe, because the registration
holds a weak reference, but it is wasted work.

The trade-off is that `Poll::Pending` carries no progress information. The
loop decides when to re-poll, from its own timing, not from tokio wake
signals.

## Invariants

1. **Never call a no-op-waker poll helper from inside an async task.** Under a
   no-op waker, `Poll::Pending` means "no wake will ever arrive". The task
   stalls permanently. Call these helpers only from synchronous loop code.
2. **The stream must outlive the `Context`.** `Pin::new(&mut stream)` is sound
   here because `DuplexStream: Unpin`, and the helper's own stack frame owns
   the waker for the duration of the poll call.
3. **Cancellation is cooperative, not waker-driven.** The loop checks a
   `CancellationToken` between polling rounds. A read after the peer closes
   surfaces `Poll::Ready(Ok(()))` with no growth in `ReadBuf::filled()`: EOF.
   `poll_read` does not return a byte count. A write to a closed peer can
   surface `BrokenPipe`. Handle the read and write signals separately.

## Extend the bridge

- A new stream type must implement `AsyncRead + AsyncWrite + Unpin`.
- A read wrapper records `ReadBuf::filled().len()` before the poll. On
  `Poll::Ready(Ok(()))`, no increase means EOF. Translate EOF to
  `UnexpectedEof` only when the protocol requires more bytes. A write wrapper
  translates `Poll::Ready(Ok(0))` into `WriteZero` and handles `BrokenPipe` as
  peer closure.
- Do not add an `async fn` wrapper around these helpers. It stalls under the
  no-op waker.

## io_uring registered buffers

When the loop drives an io_uring backend with registered buffer pools for
zero-copy `SendZc` and `RecvFixed`, hold these invariants:

1. Register buffers once at startup and reference them by index in every SQE.
   Re-registration resets all in-flight operations.
2. SQE submission and CQE completion are not synchronized by tokio. The loop
   polls the ring and drains completions into per-consumer queues.
3. Every `unsafe` block that constructs an SQE carries a `// SAFETY:` comment
   that names the buffer-index validity and the fd lifetime. New SQE
   constructors must match. See `rust-unsafe`.
4. Cancel an in-flight operation with `IORING_OP_ASYNC_CANCEL`. Do not just
   drop the SQE. A fire-and-forget drop leaks the registered buffer until the
   kernel completes the operation.
