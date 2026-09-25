# Deadline phases and retry delay

## Phase caps

Each cap bounds one failure mode. The operation deadline bounds all of them together. Give each
phase `min(configured phase cap, operation deadline - monotonic now)`.

| Control | Starts | Ends | Protects against |
|---|---|---|---|
| DNS cap | Before lookup | Address set returned | Resolver stall |
| Connect cap | Before socket or proxy connect | Secure connection ready | Route, proxy, TCP, or TLS stall |
| Write idle cap | After write starts | Request body complete | Peer that stops reading |
| First-byte cap | After request complete | Response headers arrive | Slow handler or upstream |
| Read idle cap | After body starts | Each body chunk | Peer that stops sending |
| Operation deadline | At API entry | Body consumed or discarded | All cumulative work |

## Full-jitter delay

Keep the delay calculation pure. Pass the random sample in, so a test can fix it. For retry number
`n`, starting at zero, the function selects a delay in `0 ..= min(maximum, base * 2^n)`. The shift
and the multiplication saturate, so a large retry number gives at most `maximum` and does not
overflow.

```rust,run
use std::time::Duration;

fn full_jitter_delay(
    base: Duration,
    maximum: Duration,
    retry_number: u32,
    sample: u64,
) -> Duration {
    let factor = 1_u128.checked_shl(retry_number).unwrap_or(u128::MAX);
    let cap = base.as_millis().saturating_mul(factor);
    let cap = cap.min(maximum.as_millis()).min(u128::from(u64::MAX)) as u64;
    Duration::from_millis(if cap == u64::MAX {
        sample
    } else {
        sample % (cap + 1)
    })
}

fn main() {
    let (base, maximum) = (Duration::from_millis(100), Duration::from_secs(2));
    assert!(full_jitter_delay(base, maximum, 3, 900) <= Duration::from_millis(800));
    // A large retry number saturates at `maximum` instead of overflowing.
    assert!(full_jitter_delay(base, maximum, 200, u64::MAX) <= maximum);
}
```

Apply `Retry-After` to the result. Take the larger of the valid server delay and this delay. If
that delay and one more attempt do not fit in the time left before the operation deadline, do not
retry. Return the original failure.

## Sources

- [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html): idempotent methods, `408`, `Retry-After`.
- [RFC 6585](https://www.rfc-editor.org/rfc/rfc6585.html): `429 Too Many Requests`.
- [tower retry budget](https://docs.rs/tower/latest/tower/retry/budget/index.html): process-wide
  retry limits.
