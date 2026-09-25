# Keep data valid when a panic passes through

Read this file when code inside a `catch_unwind` guard mutates shared state, holds a lock, or
runs a section that must not half-complete. `catch_unwind` returns control, so whatever the
closure touched is still alive. Panic safety of data is a separate problem from panic safety of
the boundary.

- **Lock poisoning.** `std::sync::Mutex` marks itself poisoned when a holder panics. State the
  policy at each lock (the `rust-discipline` skill owns it). `parking_lot` locks do not poison:
  you get no warning, so state the invariant in the type.
- **Restore the invariant with a guard.** Move the "put it back" step into a `Drop`
  implementation so unwinding runs it. Set the flag, create the guard, do the work.
- **Never panic in `Drop`.** A panic inside a `Drop` that runs during unwinding aborts with
  `panic in a destructor during cleanup`. A `Drop` implementation must be infallible: log the
  failure and continue.
- **Do not leave a `&mut` in a torn state.** If you split a value into parts and panic in the
  middle, the caller observes the parts. Build the new value first, then commit with a single
  assignment.
- **Force an abort where an unwind is unacceptable.** In a critical section that must not
  half-complete, arm a bomb and disarm it on success:

```rust
struct AbortOnUnwind {
    armed: bool,
}
impl Drop for AbortOnUnwind {
    fn drop(&mut self) {
        if self.armed {
            std::process::abort();
        }
    }
}

let mut bomb = AbortOnUnwind { armed: true };
// ... section that must complete or kill the process ...
bomb.armed = false;
```
