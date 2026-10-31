# Negative routing cases

A phrase in this table must not appear in the description of the skill in the second column.
Each row records a collision between two skills that was settled once: the third column owns the
phrase, and the second column must not claim it again. `scripts/validate-skills.py` enforces every
row on every run.

The check ignores a `Not for ...` sentence. A boundary clause such as "Not for loom, proptest; use
rust-test-tools" names the phrase to send it away, and it is the intended fix for a collision.

Add a row when a misroute report or an evaluation run shows two descriptions competing for one
phrase, in the same change that settles the owner. A phrase is matched case-insensitively as a
substring, so keep it specific: `E0499` alone would also match `E0499 in a dispatch loop`.

| Phrase | Must not appear in | Owner | Collision |
| --- | --- | --- | --- |
| loom | rust-tdd | rust-test-tools | loom models are a test tool, not part of the test-first cycle |
| proptest | rust-tdd | rust-test-tools | property tests are a test tool, not part of the test-first cycle |
| cargo-fuzz | rust-tdd | rust-test-tools | fuzz targets are a test tool |
| unsafe impl Send | rust-send-sync | rust-unsafe | a manual auto-trait impl is an unsafe proof obligation |
| unsafe impl Sync | rust-send-sync | rust-unsafe | a manual auto-trait impl is an unsafe proof obligation |
| E0382 | rust-event-loop-state | rust-compiler-errors | a plain borrow-checker error outside a dispatch loop |
| borrow checker | rust-event-loop-state | rust-compiler-errors | a plain borrow-checker error outside a dispatch loop |
| does not live long enough | rust-event-loop-state | rust-compiler-errors | a plain lifetime error outside a dispatch loop |
| dispatch loop | rust-compiler-errors | rust-event-loop-state | E0499 and E0502 inside a handler loop are a state-ownership design |
| handler trait | rust-compiler-errors | rust-event-loop-state | E0207 on a generic handler trait is a state-ownership design |
| AsyncFn | rust-callback-bounds | rust-async-internals | `Send` bounds on an async callback belong to the future mechanics |
| async closure | rust-callback-bounds | rust-async-internals | `Send` bounds on an async callback belong to the future mechanics |
| HRTB | rust-async-internals | rust-callback-bounds | a higher-ranked bound on a plain callback |
| sort_by_key | rust-async-internals | rust-callback-bounds | a key projection is a plain callback bound |
