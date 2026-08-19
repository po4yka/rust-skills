---
name: rust-event-loop-state
description: Use when you design or review an event loop, tick loop, or handler registry whose handlers all need &mut to one shared mutable state - a game loop, a TUI loop, or any god object every handler writes to. Covers the decision table that picks the structure from the shape of the handler set, why the loop must own the handler set and the state separately (E0499, E0502), state as a trait generic parameter instead of an associated type (E0207), capability bounds plus one Vec<Box<dyn Handler<App>>>, the blanket-impl one-way door (E0119), why DerefMut on a context wrapper destroys disjoint-field borrows, when an ECS-shaped dynamic world earns its run-time conflict panic, and why async fn(&mut State) and nightly coroutine resume arguments cannot express a suspendable routine over shared state. Triggers on "event loop", "tick loop", "handler registry", "shared mutable state", "god object", "ECS", "system and world", "Rc<RefCell> between handlers", "E0499 in my dispatch loop", or "coroutine resume".
license: BSD-3-Clause
---

# Rust event loop state

## Purpose

Decide which structure an event loop gets when every handler needs `&mut` to one shared
state. The reader arrives with `E0499` in a dispatch loop. The answer is almost never a
different line; it is a different owner. This skill picks the owner.

The one sentence not to get wrong: **the loop owns the handler set and the state as two
separate values, and passes one into the other.** Every other rule here follows from it.

This skill covers synchronous loops. Runtime behaviour under tokio — `select!`, `JoinSet`,
`FuturesUnordered`, waker plumbing, cancellation — belongs to `rust-async-internals`. Every
diagnostic below comes from rustc 1.97.0, edition 2024, on aarch64-apple-darwin; the nightly
ones from rustc 1.97.0-nightly (d7f14d3d8 2026-05-15).

## Pick the structure from the shape of the handler set

Read the left column first. Stop at the first row that describes your handler set. Each row
down costs something concrete, and you pay it whether or not you needed it.

| Shape of the handler set | Structure | What it costs |
| --- | --- | --- |
| Fixed at compile time. The state's fields are known to the crate that writes the loop | The loop holds `Vec<Box<dyn Handler>>` and `State` as two locals. Dispatch `h.handle(&mut state, &ev)` | Nothing. Start here |
| Handlers must be reused across applications that have different states | State is a trait parameter: `trait Handler<S>`. Each handler declares the capability traits it needs on `S`. The loop registers `Vec<Box<dyn Handler<App>>>` | Trait-solver error volume, and one unbounded blanket impl forecloses every later per-state impl on that type (E0119) |
| The component set is genuinely open at run time: plugins, scripting, save files, or a level editor decide it | An ECS-shaped dynamic world with type-erased components and systems | Aliasing detection stops being a compile error. It becomes a run-time panic the first time the schedule initialises that system |
| None of the above | Row 1. Do not reach further | Nothing. `Rc<RefCell<State>>` in every handler, `Arc<Mutex<State>>` inside one thread, and `async fn(&mut State)` as a suspendable routine each move a compile error to a panic, a deadlock, or an unfixable `E0499`. See [Do not do this](#do-not-do-this) |

Rows 2 and 3 are not a ladder you climb for elegance. Row 2 exists because handlers ship in
a different crate from the state; row 3, because the component set is not known when the
binary is built. If neither sentence is true of your program, row 1 is the answer.

## Route the symptom to a section

| Symptom or task | Section |
| --- | --- |
| `error[E0499]: cannot borrow *st as mutable more than once`, pointing at the dispatch argument | [The loop owns both, separately](#the-loop-owns-both-separately) |
| `error[E0502]: ... immutable borrow later used by call`, on `while let Some(ev) = ...front()` | [Drain the queue by value](#drain-the-queue-by-value) |
| `error[E0499] ... first borrow later used by call`, first borrow at handler construction | [A handler stores a key, never a borrow](#a-handler-stores-a-key-never-a-borrow) |
| `error[E0207]: the type parameter S is not constrained ...`, or `error[E0119]: conflicting implementations of trait Handler<App> for type X` | [State is a trait parameter](#state-is-a-trait-parameter-not-an-associated-type) |
| `E0499` on `&mut ctx.field` where `ctx` implements `DerefMut` | [Static plus dynamic state](#static-plus-dynamic-state-no-derefmut) |
| A run-time panic: `... conflicts with a previous system parameter` (an ECS library code such as `B0001`) | [ECS: the price of the dynamic world](#ecs-the-price-of-the-dynamic-world) |
| A routine must pause mid-work and continue next tick | [Suspendable routines](#suspendable-routines-over-shared-state) |
| `error: implementation of Coroutine is not general enough` | [The three escapes](#the-three-escapes-and-why-none-works) |
| Two futures over one state under a runtime | `rust-async-internals` |

## The loop owns both, separately

Put the handler collection inside the state and dispatch `&mut State` into the handlers, and
the call cannot type-check. The iterator holds a mutable borrow of `*st` for the whole loop
body, so the `&mut State` argument is a second mutable borrow of the same place:

```rust,compile_fail
struct Event(u32);
struct State { counter: u32, handlers: Vec<Box<dyn Handler>> }
trait Handler { fn handle(&mut self, st: &mut State, ev: &Event); }

fn tick(st: &mut State, ev: Event) {
    for h in st.handlers.iter_mut() {
        h.handle(st, &ev);
    }
}
```

```text
error[E0499]: cannot borrow `*st` as mutable more than once at a time
 9 |     for h in st.handlers.iter_mut() {
   |              ----------------------
   |              first mutable borrow occurs here / first borrow later used here
10 |         h.handle(st, &ev);
   |                  ^^ second mutable borrow occurs here
```

No interior mutability fixes this. Move the collection out. Two locals in the loop are two
independent owners, so the two borrows are provably disjoint:

```rust
struct Event(u32);
struct State { counter: u32, log: Vec<String> }
trait Handler { fn handle(&mut self, st: &mut State, ev: &Event); }

struct Count;
impl Handler for Count {
    fn handle(&mut self, st: &mut State, ev: &Event) { st.counter += ev.0; }
}
struct Trace;
impl Handler for Trace {
    fn handle(&mut self, st: &mut State, ev: &Event) { st.log.push(ev.0.to_string()); }
}

fn tick(handlers: &mut [Box<dyn Handler>], st: &mut State, ev: Event) {
    for h in handlers.iter_mut() { h.handle(st, &ev); }
}

fn main() {
    let mut handlers: Vec<Box<dyn Handler>> = vec![Box::new(Count), Box::new(Trace)];
    let mut st = State { counter: 0, log: Vec::new() };
    tick(&mut handlers, &mut st, Event(3));
    tick(&mut handlers, &mut st, Event(4));
    assert_eq!(st.counter, 7);
    assert_eq!(st.log, ["3", "4"]);
    println!("{} {:?}", st.counter, st.log);   // 7 ["3", "4"]
}
```

When an existing codebase cannot move the field yet, there are two repairs. Group the rest
of the state in a sub-struct, make the handler trait take that sub-struct, and dispatch
`&mut st.rest`. The handler field may stay where it is, because `st.handlers` and `st.rest`
are disjoint field borrows. Use `std::mem::take(&mut st.handlers)` for the tick only when a
handler must also mutate the handler set. The put-back is then the trap: a handler may
register a new handler during the tick, and a plain assignment drops it. Append the newcomers
first. The full migration example is in `references/state-partitioning.md`.

### The three diagnostics that mean "the handlers are inside the state"

| Diagnostic | What the code does | Fix |
| --- | --- | --- |
| `E0499`, first borrow at `iter_mut()`, second at the dispatch argument | The handler collection is a field of the state | Move the field out of `State`, dispatch a sub-struct field, or `mem::take` it for the tick |
| `E0502`, `immutable borrow later used by call` | The event being dispatched is borrowed out of a queue inside the state | Pop the event by value |
| `E0499`, `first borrow later used by call`, first borrow at handler construction | A handler holds a `&mut` into the state | Store an index or a generational key in the handler |

## Drain the queue by value

`front()` returns a reference tied to `*state`. NLL keeps it live across the dispatch call
because the reference is an argument, so the whole state stays borrowed. Peeking the queue
with `while let Some(ev) = st.queue.front()` and then calling `handle(st, ev)` gives:

```text
error[E0502]: cannot borrow `*st` as mutable because it is also borrowed as immutable
 9 |     while let Some(ev) = st.queue.front() {
   |                          -------- immutable borrow occurs here
10 |         handle(st, ev);
   |         ------^^^^^^^^
   |         mutable borrow occurs here / immutable borrow later used by call
```

`pop_front()` produces an owned `Event`, so no borrow of the state survives into the
handler, and a handler may push more events back:

```rust
use std::collections::VecDeque;

struct Event(u32);
struct State { counter: u32, queue: VecDeque<Event> }

fn handle(st: &mut State, ev: Event) {
    st.counter += ev.0;
    if ev.0 > 1 { st.queue.push_back(Event(ev.0 - 1)); }   // handlers may enqueue
}

fn main() {
    let mut st = State { counter: 0, queue: VecDeque::from([Event(3)]) };
    while let Some(ev) = st.queue.pop_front() { handle(&mut st, ev); }
    assert_eq!(st.counter, 6);
    println!("counter={}", st.counter);   // counter=6
}
```

A handler that enqueues on every event makes that `while let` spin forever. Read the length
first and drain exactly one batch per tick: `for _ in 0..st.queue.len() { let Some(ev) =
st.queue.pop_front() else { break }; handle(st, ev); }`.

## A handler stores a key, never a borrow

A handler built from a field of the state carries that borrow into every dispatch, and the
`&mut State` argument is then a second borrow. `struct Caching<'a> { cache: &'a mut Cache }`,
constructed as `Caching { cache: &mut st.caches[0] }` and then dispatched with
`h.handle(st)`, gives:

```text
error[E0499]: cannot borrow `*st` as mutable more than once at a time
10 |     let mut h = Caching { cache: &mut st.caches[0] };
   |                                       --------- first mutable borrow occurs here
11 |     h.handle(st);
   |       ------ ^^ second mutable borrow occurs here
   |       first borrow later used by call
```

Store the slot instead, and resolve it at the top of each call:
`struct Caching { slot: usize }`, then `st.caches[self.slot].hits += 1` inside `handle`.
Handler construction then does not touch the state at all, which is what makes one registry
usable across every tick; `references/state-partitioning.md` has the runnable version. A bare
`usize` goes stale when a slot is reused. Use a generational key when slots are freed.

## State is a trait parameter, not an associated type

A handler that must work against any state cannot use an associated type. The state then
appears only in the associated-type value, which does not constrain the impl:

```rust,compile_fail
struct Mouse;
struct Standalone;

trait Handler {
    type State;
    fn on_mouse(&mut self, st: &mut Self::State, m: &Mouse);
}
impl<S> Handler for Standalone {
    type State = S;
    fn on_mouse(&mut self, _st: &mut S, _m: &Mouse) {}
}
```

```text
error[E0207]: the type parameter `S` is not constrained by the impl trait, self type, or predicates
9 | impl<S> Handler for Standalone {
  |      ^ unconstrained type parameter
help: use the type parameter `S` in the `Standalone` type and use it in the type definition
```

Do not take that help. `struct Standalone<S>` makes one handler type per state and defeats
the point. Put the state on the trait instead. `Handler<S>` is a trait reference, so `S` is
constrained by construction, and the trait stays dyn compatible because the state is a trait
parameter and not a method type parameter:

```rust
struct Mouse;
trait TimeState { fn now(&mut self) -> u64; }
trait Handler<S> { fn on_mouse(&mut self, st: &mut S, m: &Mouse); }

struct Standalone;
impl<S> Handler<S> for Standalone {
    fn on_mouse(&mut self, _st: &mut S, _m: &Mouse) {}
}
struct Timed { last: u64 }
impl<S: TimeState> Handler<S> for Timed {
    fn on_mouse(&mut self, st: &mut S, _m: &Mouse) { self.last = st.now(); }
}

struct App { tick: u64 }
impl TimeState for App { fn now(&mut self) -> u64 { self.tick += 1; self.tick } }

fn main() {
    let mut app = App { tick: 0 };
    // Different bounds on S, one vtable type, one registry.
    let mut handlers: Vec<Box<dyn Handler<App>>> =
        vec![Box::new(Standalone), Box::new(Timed { last: 0 })];
    for h in handlers.iter_mut() { h.on_mouse(&mut app, &Mouse); }
    assert_eq!(app.tick, 1);
    println!("tick={}", app.tick);      // tick=1
}
```

Each handler names the slice of the god object it needs, and nothing else. The capability
traits are the documentation.

**The unbounded blanket impl is a one-way door.** `impl<S> Handler<S> for Standalone`
overlaps every concrete instantiation, and stable Rust has no specialisation. Adding
`impl Handler<App> for Standalone` later gives:

```text
error[E0119]: conflicting implementations of trait `Handler<App>` for type `Standalone`
 7 | impl<S> Handler<S> for Standalone {
   | ----------------------------------- first implementation here
11 | impl Handler<App> for Standalone {
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ conflicting implementation for `Standalone`
```

Write the unbounded form only for a handler that ignores the state forever. Give every other
handler a bound. Two blanket impls on **different** `Self` types with different bounds
coexist without error. `references/state-partitioning.md` has the three-handler registry, the
`?Sized` variant for a `dyn` state, and how to cut a god object into capability traits.

## Static plus dynamic state, no DerefMut

A context that carries a compile-time state next to a dynamic world invites a `DerefMut`, so
that `ctx.frame` reaches the static half. Do not add it. Auto-deref rewrites `&mut ctx.frame`
into `DerefMut::deref_mut(&mut ctx).frame`, which borrows all of `ctx`. Disjoint-field
reasoning is then gone, and one field borrow plus one accessor call is `E0499`:

```text
error[E0499]: cannot borrow `*ctx` as mutable more than once at a time
17 |     let f: &mut u64 = &mut ctx.frame;        // via DerefMut: borrows all of ctx
   |                            --- first mutable borrow occurs here
18 |     let w: &mut World = ctx.world_mut();
   |                         ^^^ second mutable borrow occurs here
```

Expose both halves as plain fields. Field access is a place expression, so `&mut
ctx.statics.frame` and `&mut ctx.world` are disjoint and the same body compiles. When the
split must sit behind a method, return both halves from one call:
`fn split(&mut self) -> (&mut S, &mut World)`. One accessor per half is the shape that
fails. `references/state-partitioning.md` has both versions in full, and `rust-discipline`
covers `Deref` on non-pointer types in general.

## ECS: the price of the dynamic world

An ECS-shaped world is the right answer when the component set is decided at run time. It is
a real trade, not a mistake. What you buy: components added without touching the loop,
systems written independently, and storage laid out for iteration. What you pay: the borrow
checker no longer sees the accesses. A system that asks for two overlapping mutable views of
one component type builds with zero errors. The library checks the access sets itself and
reports the conflict as a run-time panic.

Three consequences, and they are the whole cost:

1. **The check runs when the schedule initialises the system parameters, before the system
   body executes.** A run condition that returns false does not hide the conflict, and an
   empty world does not hide it. Only a schedule that never runs hides it. Run every schedule
   once in CI.
2. **The default message may name nothing.** Turn the library's debug feature on in the dev
   profile. The panic then names the system, the parameter, and the component.
3. **The repair is a parameter set, not a restructure.** Put the conflicting views in the
   library's parameter-set type and reach them one at a time, disjoint in time. A disjoint
   filter on the two views is the better repair when they cover different entities.

`references/state-partitioning.md` holds the full trade table, and a runnable reproduction
and repair against one named ECS crate.

## Suspendable routines over shared state

A routine that must pause mid-work and continue next tick does not need `async`. Give it a
trait whose step method takes the state. Every call takes a fresh reborrow by construction,
which is exactly the property the loop needs:

```rust
struct State { counter: u32 }
enum Step { Pending, Done }
trait Routine { fn resume(&mut self, st: &mut State) -> Step; }

struct Counting { left: u32 }
impl Routine for Counting {
    fn resume(&mut self, st: &mut State) -> Step {
        if self.left == 0 { return Step::Done; }
        self.left -= 1;
        st.counter += 1;
        Step::Pending
    }
}

fn main() {
    let mut st = State { counter: 0 };
    let mut routines: Vec<Box<dyn Routine>> = vec![Box::new(Counting { left: 5 })];
    let mut alive = true;
    while alive {
        alive = false;
        for r in routines.iter_mut() {
            if let Step::Pending = r.resume(&mut st) { alive = true; }
        }
    }
    assert_eq!(st.counter, 5);
    println!("counter={}", st.counter);   // counter=5
}
```

The cost is honest: you write the state machine by hand, as fields on the routine struct. No
`.await` sugar exists for this shape on any current toolchain.

### `Future` cannot express it

`Future::poll` takes `&mut Context<'_>` and nothing else. There is no slot for a
caller-supplied `&mut State`. An `async fn(&mut State)` captures the borrow at construction
and holds it for the whole life of the future, so two such routines over one state conflict
before any executor is involved:

```rust,compile_fail
struct State { counter: u32 }

async fn routine(st: &mut State) { st.counter += 1; }

async fn run(st: &mut State) {
    let a = routine(st);
    let b = routine(st);
    a.await;
    b.await;
}
```

```text
error[E0499]: cannot borrow `*st` as mutable more than once at a time
7 |     let a = routine(st);
  |                     -- first mutable borrow occurs here
8 |     let b = routine(st);
  |                     ^^ second mutable borrow occurs here
9 |     a.await;
  |     - first borrow later used here
```

Reserve `async` for routines that own everything they touch. When two futures must touch one
struct, hand each a `&mut` to a **different field** before the futures are created;
`rust-async-internals` owns that case and the runtime side.

### The three escapes, and why none works

| Escape | Verdict |
| --- | --- |
| Smuggle `*mut State` through `Waker::data()` | The pointer does not survive `FuturesUnordered`, or anything built on it, which substitutes its own per-future waker. Materialising two `&mut State` from it is undefined behaviour under both Miri borrow models. See `rust-async-internals` and `rust-unsafe` |
| `Context::ext()` on nightly | Carries a value only if the *executor* built the context with `ContextBuilder::ext()`. tokio uses `Context::from_waker`, so `ext()` is `()`, and every downcast returns `None` with no diagnostic. See `rust-async-internals` |
| Nightly coroutines with a resume argument | Does not work, and stabilisation would not change that. See below |

The coroutine row is worth stating in full, because coroutines are repeated as the coming
fix for exactly this problem. A `#[coroutine]` closure implements `Coroutine<&'x mut State>`
for **one** inferred lifetime. It is not higher-ranked over its resume argument. Asking for
the higher-ranked bound fails:

```rust,ignore
#![feature(coroutine_trait, coroutines, stmt_expr_attributes)]
use std::ops::Coroutine;

fn routine() -> impl for<'x> Coroutine<&'x mut State, Yield = (), Return = ()> {
    #[coroutine] |mut st: &mut State| {
        st.counter += 1;
        st = yield ();
        st.counter += 10;
    }
}
```

```text
error: implementation of `Coroutine` is not general enough
 7 |       #[coroutine] |mut st: &mut State| {
   |  __________________^
   | |_____^ implementation of `Coroutine` is not general enough
   = note: `{coroutine@src/main.rs:7:18: 7:38}` must implement `Coroutine<&'1 mut State>`,
     for any lifetime `'1`...
   = note: ...but it actually implements `Coroutine<&'2 mut State>`, for some specific
     lifetime `'2`
```

Accepting one lifetime — `fn routine<'x>() -> impl Coroutine<&'x mut State, ...>` — compiles
the definition and then fails at the only call site that matters, the loop:

```text
error[E0499]: cannot borrow `st` as mutable more than once at a time
19 |         match c.as_mut().resume(&mut st) {
   |               -                 ^^^^^^^ `st` was mutably borrowed here in the previous
   |                                         iteration of the loop
   |               first borrow used here, in later iteration of loop
```

The missing feature is a higher-ranked binder over the resume type, not stabilisation.
`for<...> impl Trait` is not even a spelling: it gives
``error: `for<...>` expected after `impl`, not before``.

The same limit applies to the stable generator crates that wrap an `async` block and expose
a `resume(value)` API. Their `Resume` is a plain type parameter on the constructor, bound at
the call site, and the higher-ranked bound in their `where` clause quantifies over the
yielder lifetime only. Requesting `impl for<'a> Generator<&'a mut State, ...>` from one gives
`error: implementation of Generator is not general enough`, and the fixed-lifetime version
gives the same `E0499` on the second loop iteration. Those crates are useful for yielded
values. They are not a route to `&mut State`.

Two smaller facts, in case a snippet written before 2023 reaches you: there is no
`std::ops::Generator` — `use std::ops::Generator;` is `E0432` and the trait is
`std::ops::Coroutine` — and a `gen { .. }` block is an `Iterator` only, with no resume
argument. `rust-iterator-impl` records both.

## Do not do this

| Move | What actually happens |
| --- | --- |
| `Rc<RefCell<State>>` cloned into every handler, re-borrowed during dispatch | The `E0499` becomes a `RefCell already borrowed` panic (`BorrowMutError`) the first time one handler calls another. The compile error told you the truth |
| `Arc<Mutex<State>>` inside one thread, re-locked during dispatch | The same failure as a deadlock instead of a panic. One thread that re-enters the lock hangs on the first nested `lock()`, with no output and no backtrace. Load is not needed |
| `unsafe { &mut *ptr }` to hand two handlers the state | Two live `&mut` to one place is undefined behaviour. Miri rejects it under Stacked Borrows and Tree Borrows. See `rust-unsafe` |
| `async fn(&mut State)` as a suspendable routine | `E0499` before any executor runs. No version of this works |
| An ECS taken for ergonomics, not for an open component set | You pay run-time conflict panics for a component set the compiler could have checked |

The first two rows are about re-entrant dispatch inside one synchronous loop. Under a runtime
the same shapes read differently: `Arc<Mutex<State>>` across separate tasks is a valid,
serializing choice. See `rust-async-internals`.

## Checklist

1. Are the handlers a field of the state? Move them out, dispatch a sub-struct field, or
   `mem::take` them for the tick.
2. Does the tick loop iterate a collection it also passes into the call? That is `E0499`.
3. Does dispatch borrow the event out of the state? Pop it by value.
4. Can a handler push events? Then drain one batch per tick, not `while let`.
5. Does any handler struct hold a `&` or `&mut` into the state? Replace it with a key.
6. Does the handler trait use `type State`? That is `E0207`. Make it `Handler<S>`.
7. Is there an `impl<S> Handler<S> for X` with no bound? That door does not reopen.
8. Does a context wrapper implement `DerefMut`? Delete it and use plain fields.
9. Is an ECS on the table? Name the run-time input that decides the component set. No such
   input, no ECS.
10. Using an ECS already? Every schedule runs once in CI, and the library's debug feature
    is on in dev.
11. Is a routine a `Future` so it can hold `&mut State` across a suspend point? Rewrite it
    as `fn resume(&mut self, st: &mut State) -> Step`.

## Related skills

| Skill | Boundary |
| --- | --- |
| `rust-async-internals` | This skill decides the structure of a synchronous loop. `rust-async-internals` owns everything under a runtime: `select!`, `JoinSet`, `FuturesUnordered`, waker plumbing, `Context::ext`, cancellation, and two futures over disjoint fields of one struct |
| `rust-compiler-errors` | This skill says which owner to change. `rust-compiler-errors` explains `E0499`, `E0502`, and `E0207` as diagnostics, with the general repairs |
| `rust-discipline` | This skill uses capability traits and keys. `rust-discipline` owns the API rules behind them: `Deref` on non-pointer types, blanket impls and semver including `E0119`, index against reference in a public signature |
| `rust-unsafe` | This skill rejects raw-pointer state sharing. `rust-unsafe` supplies the Miri reproduction and the aliasing rules that make it undefined behaviour |
| `rust-iterator-impl` | This skill stops at "coroutines cannot carry `&mut State`". `rust-iterator-impl` records the `Generator` to `Coroutine` rename, `gen` blocks, and `iter::from_fn` |
| `rust-crate-architecture` | This skill decides who owns state inside one binary. `rust-crate-architecture` decides which crate the handler trait and the state type live in |
