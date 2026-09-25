# Network test seams

Test policy without a real public network. Use the smallest seam that exposes the behavior under
test.

| Behavior under test | Seam |
|---|---|
| Deadlines and backoff | Pause or inject monotonic time |
| Jitter | Pass a fixed jitter sample into the delay calculation |
| Partial writes, delayed headers, stalled bodies | Run a local listener |
| Multiple addresses, DNS failures | Inject a resolver result |
| TLS name and trust failures | Generate a test CA and a server certificate |
| Body replay | Use a counting body that fails if a retry reads it twice |
| Pool reuse, drain after a policy change | Expose pool-connect counts |
| Overload rejection | Hold a concurrency permit |
| Shutdown deadline | Keep one handler open; assert that the serve future returns within the shutdown deadline |
| Header-read timeout | Send a partial request header; assert that the server closes the connection after the header timeout |

## Sources

- [tokio time](https://docs.rs/tokio/latest/tokio/time/): timeout cancellation and paused clocks.
