# Iterator style

Deep material for [SKILL.md](../SKILL.md).

## Pure xor mutability

Never mix a side effect and a pure expression in the same statement. Either compute a
value and return it, or declare a binding and then mutate it:

```rust
// Good. Pure computation.
let key = format!("{host}:{port}");

// Good. Mutation in its own statements.
let mut map = HashMap::new();
map.insert(key, value);

// Bad. A side effect hides inside an expression.
let result = map.entry(key).or_insert_with(|| {
    log::info!("cache miss"); // hidden side effect
    compute_value()
});
```

## Iterator combinators must be pure

A closure in a `.map()`, `.filter()`, or `.collect()` chain must have no side effect. Use
an explicit `for` loop when you need mutation or logging:

```rust
// Good. A pure combinator chain.
let names: Vec<_> = items.iter().filter(|i| i.active).map(|i| &i.name).collect();

// Good. A for loop for side effects.
for item in &items {
    if item.active {
        registry.register(&item.name);
    }
}

// Bad. A side effect inside a combinator.
items.iter().for_each(|i| registry.register(&i.name));
```

A `for` loop covers every side-effecting use of `.for_each()`, and it puts the effect in
plain sight. Ban `Iterator::for_each` through the `disallowed-methods` list in
`clippy.toml` so the rule holds without a reviewer. See `rust-lints` for the
configuration.

## Choose the collector by error contract

`Result<T, E>` implements `IntoIterator`, and it yields one item for `Ok` and zero for
`Err`. A `flat_map` or a `flatten` over a `Result` therefore deletes every failure with no
trace. The output type is `Vec<i32>`, not a `Result`, so no lint and no type error reports
the loss. Pick the collector from the contract the caller needs:

```rust
use std::num::ParseIntError;

let raw = ["1", "duck", "2"];

// Bad. `Err` yields zero items, so the failure disappears with no diagnostic.
let dropped: Vec<i32> = raw.iter().flat_map(|v| v.parse::<i32>()).collect();
assert_eq!(dropped, vec![1, 2]);

// Stop at the first error. `collect` short circuits and returns that `Err`.
let strict: Result<Vec<i32>, ParseIntError> =
    raw.iter().map(|v| v.parse::<i32>()).collect();
assert!(strict.is_err());

// Keep both sides. `partition` leaves the `Result` wrapper on each half.
let (ok, bad): (Vec<_>, Vec<_>) =
    raw.iter().map(|v| v.parse::<i32>()).partition(Result::is_ok);
let ok: Vec<i32> = ok.into_iter().flatten().collect();
let bad: Vec<ParseIntError> = bad.into_iter().filter_map(Result::err).collect();
assert_eq!(ok, vec![1, 2]);
assert_eq!(bad.len(), 1);
```

Unwrap the two halves with `flatten` and `filter_map(Result::err)`. `map(Result::unwrap)`
and `map(Result::unwrap_err)` produce the same values and add a panic path.

Drop the failures only when the drop is the intent, and write that drop as
`filter_map` with `.ok()`. `filter_map` reads as a filter, so the reviewer sees the
deletion. `flat_map` reads as a mapping, so nobody does.
