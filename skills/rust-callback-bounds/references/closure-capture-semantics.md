# Closure Capture Semantics

Use this reference when `move`, a field projection, or a refactor changes the closure call
trait, lifetime, `Send` status, size, or cleanup timing.

## `move` does not mean `FnOnce`

The `move` keyword selects how the closure captures from its environment. It does not select the
call trait. The closure body selects the strongest implemented call trait:

| Body use of a capture | Call trait consequence |
| --- | --- |
| Read through a shared borrow | Can implement `Fn` |
| Mutate through a unique or mutable borrow | Can implement `FnMut` |
| Move or consume the captured value | Implements only `FnOnce` |

```rust,run
fn call_twice(f: impl Fn()) {
    f();
    f();
}

fn main() {
    let text = String::from("captured by value");
    call_twice(move || assert!(!text.is_empty()));
}
```

Do not add `clone`, `Box<dyn FnOnce>`, or a one-shot wrapper because a closure says `move`.
Compile it against the smallest required bound.

## Capture precision depends on the projection

Edition 2021 and later can capture disjoint fields instead of the complete owner. The exact
projection still matters.

| Expression shape | Review risk |
| --- | --- |
| Named struct field | The closure can capture only that field |
| Array or slice index | The closure can capture the complete array or slice owner |
| Field of a packed struct | The closure captures a safe prefix or the complete packed value to avoid an unaligned reference |
| Dereference through `Box<T>` | The compiler can capture the boxed field precisely |
| Dereference through `Rc<T>` or custom `Deref` | The closure captures the smart pointer, not an invented interior place |
| Raw-pointer dereference | Unsafe access and capture ownership are separate proofs |

This can change whether the closure is `Send` or `'static`. Inspect the captured owner, not only
the field type visible inside the body.

Use a compile probe at the real bound:

```rust
fn require_send_static(_: impl Send + 'static) {}

let owner = make_owner();
require_send_static(move || use_field(&owner.field));
```

If the probe fails, do not write `unsafe impl Send`. Reshape ownership so the closure captures a
safe owner.

## Do not depend on capture drop order

Locals, fields, and closure captures do not share one universal drop order. Precise by-value
captures can also cause parts of one owner to drop at different times. Do not encode lock order,
transaction order, or foreign-resource teardown in closure capture order.

When order matters:

1. Put the resources in one named owner.
2. Implement an explicit `close` or consuming finish method.
3. Keep `Drop` as an infallible fallback.
4. Test the visible cleanup order with a small event log.

## Edition review

A closure created in an edition 2018 crate can capture more of an owner than the same source in
an edition 2021 or 2024 crate. During migration, run the compatibility lint and recheck closure
size, `Send`, lifetime, and destructor-timing assertions.

## Checklist

- [ ] The required callable trait comes from actual body use, not from `move`.
- [ ] The exact captured place is known for every field, index, dereference, and packed access.
- [ ] `Send` and `'static` are checked against the captured owner.
- [ ] Cleanup correctness does not depend on capture drop order.
- [ ] Edition migration tests ownership and destructor timing.

## Authoritative references

- [Rust Reference closure expressions](https://doc.rust-lang.org/reference/expressions/closure-expr.html)
- [Rust Reference closure capture modes](https://doc.rust-lang.org/reference/types/closure.html#capture-modes)
- [Rust Reference call traits and coercions](https://doc.rust-lang.org/reference/types/closure.html#call-traits-and-coercions)
