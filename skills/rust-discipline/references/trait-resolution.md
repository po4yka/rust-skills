# Method resolution and trait coherence

Read this file when a diff adds a `Deref` impl, an extension trait, a `downcast_ref` chain, or
a second conversion impl between the same two types. Every trap here is a resolution decision
the compiler makes for you. Two of them are silent: the code compiles and calls the wrong
method. The rest are hard build breaks that arrive in downstream code.

Each item states a severity, the rule, the failing shape with its exact error, and the working
shape. Measured on rustc 1.97.0, edition 2024.

---

## Method lookup walks the deref chain; trait solving does not

**Severity: WARNING**

A dot call and a trait bound use two different algorithms. Do not reason about one from the
other.

`receiver.method()` builds the autoderef chain: the receiver type, then each `Deref::Target`
after it. At every step the compiler tries inherent methods first, then the methods of traits
in scope. The first step that supplies one candidate wins. A trait method at step 0 therefore
beats an inherent method at step 1.

```rust
use std::ops::Deref;

struct Inner;
impl Inner {
    fn who(&self) -> &'static str { "Inner inherent" }
}

struct Wrapper(Inner);
impl Deref for Wrapper {
    type Target = Inner;
    fn deref(&self) -> &Inner { &self.0 }
}

trait Who { fn who(&self) -> &'static str; }
impl Who for Wrapper {
    fn who(&self) -> &'static str { "Wrapper trait" }
}

fn main() {
    // Step 0 is `Wrapper`. It has no inherent `who`, but `Who` applies at step 0,
    // so the trait method wins over the inherent method at step 1.
    assert_eq!(Wrapper(Inner).who(), "Wrapper trait");
    // Force step 1 with an explicit deref.
    assert_eq!((*Wrapper(Inner)).who(), "Inner inherent");
}
```

Trait-bound solving does not walk that chain. `Wrapper: Speak` holds for the exact type or it
does not hold. Unsizing to `dyn Speak` does not walk it either.

```rust
use std::ops::Deref;

struct Inner;
trait Speak { fn speak(&self) -> &'static str; }
impl Speak for Inner { fn speak(&self) -> &'static str { "inner" } }

struct Wrapper(Inner);
impl Deref for Wrapper {
    type Target = Inner;
    fn deref(&self) -> &Inner { &self.0 }
}

fn takes_inner(i: &Inner) -> &'static str { i.speak() }

fn main() {
    let w = Wrapper(Inner);
    assert_eq!(w.speak(), "inner");        // method lookup walks the chain
    assert_eq!(takes_inner(&w), "inner");  // deref coercion to a named type
}
```

Both lines below fail on the same types, with
`error[E0277]: the trait bound 'Wrapper: Speak' is not satisfied`:

```rust,compile_fail
use std::ops::Deref;
struct Inner;
trait Speak { fn speak(&self) -> &'static str; }
impl Speak for Inner { fn speak(&self) -> &'static str { "inner" } }
struct Wrapper(Inner);
impl Deref for Wrapper {
    type Target = Inner;
    fn deref(&self) -> &Inner { &self.0 }
}

fn generic<T: Speak>(t: &T) -> &'static str { t.speak() }

fn main() {
    let _ = generic(&Wrapper(Inner));      // E0277: `Wrapper: Speak` not satisfied
    let _d: &dyn Speak = &Wrapper(Inner);  // E0277: `Wrapper: Speak` not satisfied
}
```

Rule: when a wrapper must satisfy a bound, write the impl on the wrapper and delegate in the
body. Never expect `Deref` to supply it.

---

## `Deref` gives method reuse, never substitutability

**Severity: WARNING**

`Deref` makes a wrapper feel like its target at exactly two sites: a dot call, and a coercion
that names the target type. It never makes the wrapper a subtype. Rust has no subtyping between
data types.

These three sites keep failing after you add `Deref`:

| Site | Result |
|------|--------|
| `fn f<T: Trait>(t: &T)` with `impl Trait for Target` | E0277, the bound names the wrapper |
| `let d: &dyn Trait = &wrapper;` | E0277, unsizing needs a real impl |
| `Vec<Wrapper>` passed where `Vec<Target>` is expected | E0308, no coercion inside a generic |

Rule: implement `Deref` only on a smart pointer, as
[`type-and-trait-traps.md`](type-and-trait-traps.md) states. When you want a wrapper to carry
the target's trait impls, write delegating impls, or generate them with a macro. Count the
delegating impls before you commit: if the target has 30 trait impls, `Deref` looks cheap and
still gives you none of them at a bound.

---

## An extension trait shadows silently in both directions

**Severity: CRITICAL**

An extension trait adds a method to a type you do not own. Method lookup then gives that method
a fixed priority against every other candidate, and the priority can change under you with no
warning and no error.

Direction 1: your extension method loses to a new inherent method. This block resolves
`b.len()` to `Measure::len`:

```rust
// The extension trait supplies `len`. Every call site resolves to it.
struct Buf(Vec<u8>);
trait Measure { fn len(&self) -> usize; }
impl Measure for Buf {
    fn len(&self) -> usize { self.0.len() }
}

fn main() {
    assert_eq!(Buf(vec![1, 2, 3]).len(), 3);
}
```

The owner of `Buf` then adds an inherent `len`. The build stays clean, no lint fires, and every
`b.len()` in your crate changes meaning:

```rust
struct Buf(Vec<u8>);
impl Buf {
    fn len(&self) -> usize { 999 }
}
trait Measure { fn len(&self) -> usize; }
impl Measure for Buf {
    fn len(&self) -> usize { self.0.len() }
}

fn main() {
    assert_eq!(Buf(vec![1, 2, 3]).len(), 999);       // the inherent method now
    assert_eq!(Measure::len(&Buf(vec![1, 2, 3])), 3); // UFCS reaches the trait
}
```

Direction 2: your extension method wins over an inherent method that the caller expects. An
extension trait implemented on a wrapper takes step 0 of the deref chain, so it beats the
target's inherent method of the same name. That is the first section of this file.

Rule: give an extension-trait method a name that no inherent method on the type, and no
inherent method on any type in its deref chain, already uses. When the name must collide, call
it through UFCS (`Measure::len(&b)`) at every site, and add a test that asserts the value the
extension returns.

---

## Two traits with one method name kill the dot call

**Severity: CRITICAL**

Rust has no method overloading. Two traits in scope that both define `render` for the same type
make `id.render()` ambiguous. The call fails with `error[E0034]: multiple applicable items in
scope`, and it names every candidate:

```rust,compile_fail
struct Id(u64);

trait Pretty { fn render(&self) -> String; }
impl Pretty for Id { fn render(&self) -> String { format!("#{}", self.0) } }

trait Debugish { fn render(&self) -> String; }
impl Debugish for Id { fn render(&self) -> String { format!("Id({})", self.0) } }

fn main() {
    let id = Id(7);
    println!("{}", id.render()); // error[E0034]: multiple `render` found
}
```

rustc suggests `Debugish::render(&id)` and `Pretty::render(&id)`. Both compile. Neither is a
fix you can apply to code you do not own.

This makes a new method on a published extension trait a downstream build break. The consumer
does not have to call the new method. It only has to have another trait of the same method name
in scope on the same type.

Rule: treat a method name on a published trait as part of the public API. Do not add a method
with a common name — `len`, `id`, `name`, `render`, `parse`, `into_parts` — to a trait that
downstream crates implement or import. Where an ambiguity already exists, remove one of the two
methods; do not push UFCS onto every caller.

---

## A downcast chain is a match with the exhaustiveness check removed

**Severity: CRITICAL**

A chain of `if let Some(x) = obj.downcast_ref::<Concrete>()` arms is a hand-rolled match. The
compiler checks nothing about it. Add a fourth implementor and the chain still compiles, still
runs, and silently skips the new type. Measured with three implementors and two downcast arms:
the build emits no warning about the chain, and the program handles 2 of 3 values.

When code downcasts a trait object, two facts hold at once: the set of types is closed, and the
code needs the concrete data back. That is an enum.

```rust
// The set is closed and the code needs the concrete data. An enum gets an
// exhaustiveness check; a downcast chain does not.
enum Shape {
    Sq(f64),
    Circle(f64),
    Tri(f64, f64),
}

fn area(s: &Shape) -> f64 {
    match s {
        Shape::Sq(a) => a * a,
        Shape::Circle(r) => std::f64::consts::PI * r * r,
        Shape::Tri(b, h) => 0.5 * b * h,
    }
}

fn main() {
    let v = [Shape::Sq(2.0), Shape::Circle(1.0), Shape::Tri(3.0, 4.0)];
    let total: f64 = v.iter().map(area).sum();
    assert!(total > 13.0);
}
```

Delete one arm from that `match` and the build fails with
`error[E0004]: non-exhaustive patterns: '&Shape::Tri(_, _)' not covered`.

The swap is not free. `Box<dyn Shape>` is 16 bytes plus one heap allocation per element. The
three-variant enum above is 24 bytes inline, sized by its widest variant, so one large variant
grows every element. Keep `dyn Trait` when a downstream crate supplies implementors, because no
downstream crate can add a variant to your enum.

When you must keep `dyn Trait` and still need the concrete type back, make `Any` a supertrait.
Do not write a `fn as_any(&self) -> &dyn Any` method on every impl: the compiler upcasts
`&dyn Shape` to `&dyn Any` for you.

```rust
use std::any::Any;

// `Any` as a supertrait. No `fn as_any(&self) -> &dyn Any` on every impl.
trait Shape: Any {
    fn area(&self) -> f64;
}

struct Sq(f64);
impl Shape for Sq {
    fn area(&self) -> f64 { self.0 * self.0 }
}

fn main() {
    let shapes: Vec<Box<dyn Shape>> = vec![Box::new(Sq(2.0))];
    for s in &shapes {
        let any: &dyn Any = s.as_ref(); // trait upcast, built in
        if let Some(sq) = any.downcast_ref::<Sq>() {
            assert_eq!(sq.area(), 4.0);
        }
    }
}
```

`Any` adds a `'static` bound to the trait, so no implementor can hold a non-`'static`
reference. Check that first.

---

## `impl From<X> for Y` forecloses `impl TryFrom<X> for Y` for ever

**Severity: CRITICAL**

`core` ships `impl<T, U: Into<T>> TryFrom<U> for T`. Your `From` impl therefore already
generates a `TryFrom` impl with `Error = Infallible`. A hand-written `TryFrom` for the same
pair collides with it:

```rust,compile_fail
struct Celsius(f64);
struct Kelvin(f64);

impl From<Celsius> for Kelvin {
    fn from(c: Celsius) -> Kelvin { Kelvin(c.0 + 273.15) }
}

impl TryFrom<Celsius> for Kelvin {
    type Error = &'static str;
    fn try_from(c: Celsius) -> Result<Kelvin, Self::Error> { todo!() }
}

fn main() {}
// error[E0119]: conflicting implementations of trait `TryFrom<Celsius>` for type `Kelvin`
//   = note: conflicting implementation in crate `core`:
//           - impl<T, U> TryFrom<U> for T where U: Into<T>;
```

There is no escape. The blanket impl lives in `core`, so you cannot remove it, and you cannot
add a negative bound. Removing your own `From` impl is a breaking change for every caller that
writes `.into()`.

Rule: decide once, before the impl lands, whether the conversion can fail. Write `From` only
when it is total for every value of `X`. Write `TryFrom` when any input is rejected. When a
mostly-total conversion needs one guarded variant, keep `From` and add a named constructor:

```rust
struct Celsius(f64);
struct Kelvin(f64);

// One conversion, one direction, one trait. `From` gives `Into` and a
// `TryFrom` with `Error = Infallible` for free.
impl From<Celsius> for Kelvin {
    fn from(c: Celsius) -> Kelvin { Kelvin(c.0 + 273.15) }
}

// The fallible constructor is a named method, not a second trait impl.
impl Kelvin {
    fn from_celsius_checked(c: Celsius) -> Result<Kelvin, &'static str> {
        if c.0 < -273.15 { Err("below absolute zero") } else { Ok(Kelvin::from(c)) }
    }
}

fn main() {
    let k: Kelvin = Celsius(0.0).into();
    assert!((k.0 - 273.15).abs() < 1e-9);
    let k2 = Kelvin::try_from(Celsius(0.0)).unwrap(); // Error = Infallible
    assert!((k2.0 - 273.15).abs() < 1e-9);
    assert!(Kelvin::from_celsius_checked(Celsius(-300.0)).is_err());
}
```

Find both impls on one pair:

```bash
rg "impl (Try)?From<" --type rust -n | sort -k2
```
