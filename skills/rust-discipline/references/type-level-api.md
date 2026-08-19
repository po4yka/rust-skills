# Type-level API techniques

Ways to move a check from run time to compile time. Each entry states what the technique buys,
what it costs, and when the cost is not worth paying. Every example compiles on rustc 1.97,
edition 2024.

The order is by how often the technique is the right answer. Read the first two before the rest;
they cover most cases, and the later ones are easy to over-apply.

## Newtype for an invariant

The cheapest technique, and the one that is nearly always right. A validated value gets its own
type, the constructor is the only way in, and no later code repeats the check.

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Port(u16);

impl Port {
    /// Returns `None` for port 0, which cannot be bound.
    pub fn new(value: u16) -> Option<Self> {
        (value != 0).then_some(Self(value))
    }

    pub fn get(self) -> u16 {
        self.0
    }
}
```

Keep the field private. A `pub struct Port(pub u16)` proves nothing: any code can build an
invalid one, and the type is then only a comment. See the `rust-serde` skill for the
`#[serde(try_from = "..")]` form that applies the same rule at a deserialization boundary.

## `#[non_exhaustive]` on anything a downstream crate matches

Marks a struct or an enum as open to future additions. Downstream code cannot construct the
struct with a literal, and cannot write a match without a wildcard arm, so adding a variant or a
field later is not a breaking change.

```rust
#[non_exhaustive]
#[derive(Debug)]
pub enum Error {
    NotFound,
    PermissionDenied,
}

#[non_exhaustive]
#[derive(Debug, Default)]
pub struct Options {
    pub retries: u32,
}
```

Apply it to every public error enum and every public options struct, from the first release. It
is free before publication and a breaking change to add afterwards. Do not apply it to a type
whose whole purpose is exhaustive matching inside one crate; the wildcard arm it forces then
hides a missing case.

## Sealed trait

A trait a downstream crate can name but cannot implement. Use it when the trait exists to
enumerate a closed set, or when a blanket impl would otherwise be a semver hazard.

```rust
mod sealed {
    pub trait Sealed {}
}

pub trait Codec: sealed::Sealed {
    fn name(&self) -> &'static str;
}

pub struct Json;
impl sealed::Sealed for Json {}
impl Codec for Json {
    fn name(&self) -> &'static str {
        "json"
    }
}
```

`sealed::Sealed` is public inside a private module, so a downstream crate can neither name it nor
implement it, and therefore cannot implement `Codec`. Going from sealed to open later is free.
Going from open to sealed is a breaking change, so seal by default when the set is meant to be
closed.

## Typestate

Encodes a state machine in the type, so an invalid transition does not compile. The states are
zero-sized, so it costs nothing at run time.

```rust
use std::marker::PhantomData;

pub struct Closed;
pub struct Open;

pub struct Door<S> {
    _state: PhantomData<S>,
}

impl Door<Closed> {
    pub fn new() -> Self {
        Door { _state: PhantomData }
    }

    pub fn open(self) -> Door<Open> {
        Door { _state: PhantomData }
    }
}

impl Door<Open> {
    // Only exists on an open door. Calling it on a closed one is a type error.
    pub fn walk_through(&self) {}

    pub fn close(self) -> Door<Closed> {
        Door { _state: PhantomData }
    }
}
```

The cost is real, so weigh it:

- Every transition consumes `self`, so the value cannot be stored in a field that outlives one
  state, and it cannot be held behind an `Arc`.
- The state cannot be chosen at run time. A value whose state depends on input needs an enum
  wrapper, which puts the run-time check back.
- The type name appears in every signature that touches it, including the caller's.

Use typestate for a builder that must not be finished twice, or a protocol handshake inside one
function. Do not use it for a long-lived object stored in a collection.

## `const fn` and const generics

`const fn` lets a computation run at compile time. Const generics let a length be part of the
type.

```rust
pub const fn header_len(payload: usize) -> usize {
    payload + 8
}

pub struct Frame<const N: usize> {
    bytes: [u8; N],
}

impl<const N: usize> Frame<N> {
    pub const CAPACITY: usize = header_len(N);

    pub fn new() -> Self {
        Frame { bytes: [0; N] }
    }

    pub fn capacity(&self) -> usize {
        Self::CAPACITY
    }
}
```

`const fn` is nearly free: mark a function `const` when its body allows it, and callers gain the
option of using it in a constant. It is not a breaking change to add, and it is a breaking change
to remove.

Const generics are the opposite. A `const N: usize` parameter propagates into every signature
that touches the type, and each distinct `N` is a separate monomorphization. Use them for a
fixed-size buffer whose size the caller genuinely knows at compile time. For a size the caller
learns at run time, use a slice and check the length once. See the `rust-performance` skill for
the monomorphization cost.

## Assert an invariant at compile time

When a layout or a size assumption is load bearing, state it where it will fail the build:

```rust
#[repr(C)]
pub struct Header {
    kind: u32,
    length: u32,
}

// Fails to compile if the layout ever changes.
const _: () = assert!(std::mem::size_of::<Header>() == 8);
const _: () = assert!(std::mem::align_of::<Header>() == 4);
```

This costs nothing at run time and needs no dependency. Put one next to every type whose size or
alignment another language depends on. See the `rust-unsafe` skill for the layout rules these
assertions protect.

## Let the compiler narrow control flow

Two forms that remove a nesting level and make the failure path explicit.

```rust
// let-else: bind, or leave. The else block must diverge.
pub fn parse_port(text: &str) -> u16 {
    let Ok(value) = text.parse::<u16>() else {
        return 0;
    };
    value
}

// let chains (edition 2024): bind and test in one condition, no nesting.
pub fn difference(left: Option<u32>, right: Option<u32>) -> u32 {
    if let Some(a) = left
        && let Some(b) = right
        && a > b
    {
        a - b
    } else {
        0
    }
}
```

Let chains need edition 2024. Under edition 2021 the same code fails with `let chains are only
allowed in Rust 2024 or later`, so a crate that has not migrated must keep the nested form.

## When not to reach for any of these

A run-time check is the right answer when the value is decided at run time, when the state must
be stored, or when the invariant is local to one function. The techniques above trade
flexibility for a compile-time guarantee. Spend that trade on an invariant that is genuinely
load bearing across a module boundary, not on one a single `assert!` already covers.

## Related

- [type-and-trait-traps.md](type-and-trait-traps.md) — blanket impls, lifetime laundering, and
  reference cycles
- [SKILL.md](../SKILL.md) — the API design rules these techniques implement
