---
name: rust-event-loop-state
description: Use when designing or reviewing an event loop, tick loop, or handler registry whose handlers all need &mut to one shared mutable state, such as a game loop, a TUI loop, or a god object. Also for E0499 in a dispatch loop, E0502 on a queue peek, E0207 or E0119 on a generic Handler trait, Rc RefCell between handlers, an ECS system and world, and coroutine resume or async fn as a suspendable routine over that state. Not for async runtime scheduling; use rust-async-internals.
license: BSD-3-Clause
---

# Rust event loop state

**The loop owns the handler set and the state as two separate values, and passes one into
the other.** Every rule below follows from this sentence. `E0499` in a dispatch loop almost
never needs a different line. It needs a different owner.

This skill covers synchronous loops. For runtime behavior under tokio (`select!`, `JoinSet`,
`FuturesUnordered`, wakers, cancellation), use the `rust-async-internals` skill when it is
installed. The diagnostics below are from rustc 1.98.1, edition 2024.

## Pick the structure from the shape of the handler set

Read the left column first. Stop at the first row that describes your handler set. Each row
down costs something concrete, and you pay it whether or not you needed it.

| Shape of the handler set | Structure | What it costs |
| --- | --- | --- |
| Fixed at compile time. The state's fields are known to the crate that writes the loop | The loop holds `Vec<Box<dyn Handler>>` and `State` as two locals. Dispatch `h.handle(&mut state, &ev)` | Nothing. Start here |
| Handlers must be reused across applications that have different states | State is a trait parameter: `trait Handler<S>`. Each handler declares the capability traits it needs on `S`. The loop registers `Vec<Box<dyn Handler<App>>>` | Trait-solver error volume, and a blanket impl forecloses a later per-state impl on that type for every state that meets its bounds (`E0119`) |
| The component set is open at run time: plugins, scripting, save files, or a level editor decide it | An ECS-shaped dynamic world with type-erased components and systems | Aliasing detection stops being a compile error. It becomes a run-time panic the first time the schedule initializes that system |
| None of the above | Row 1. Do not reach further | Nothing. The shortcuts in [Do not do this](#do-not-do-this) each move a compile error to a panic, a deadlock, or an unfixable `E0499` |

## Triage

| Symptom | Cause | Fix | Section |
| --- | --- | --- | --- |
| `E0499: cannot borrow *st as mutable more than once`, first borrow at `iter_mut()`, second at the dispatch argument | The handler collection is a field of the state | Move the field out of `State`, dispatch a sub-struct field, or `mem::take` it for the tick | [The loop owns both](#the-loop-owns-both-separately) |
| `E0502 ... immutable borrow later used by call` on `while let Some(ev) = st.queue.front()` | The event is borrowed out of a queue inside the state | Pop the event by value | [Drain the queue](#drain-the-queue-by-value) |
| `E0499 ... first borrow later used by call`, first borrow at handler construction | A handler holds a `&mut` into the state | Store an index or a generational key | [Store a key](#a-handler-stores-a-key-never-a-borrow) |
| `E0207: the type parameter S is not constrained` | The handler trait has `type State` | Make it `trait Handler<S>` | [State is a trait parameter](#state-is-a-trait-parameter-not-an-associated-type) |
| `E0119: conflicting implementations of trait Handler<App>` | A blanket `impl<S: ...> Handler<S> for X` whose bounds `App` satisfies. An unbounded one covers every state | Keep one impl. Delete the per-state impl and move its behavior behind a capability-trait method, or replace the blanket impl with per-state impls. A bound removes the overlap only when `App` does not satisfy it | [State is a trait parameter](#state-is-a-trait-parameter-not-an-associated-type) |
| `E0499` on `&mut ctx.field` where `ctx` implements `DerefMut` | Auto-deref borrows the whole wrapper | Plain fields, or one `split()` method | [No DerefMut](#static-plus-dynamic-state-no-derefmut) |
| Run-time panic `... conflicts with a previous system parameter` (an ECS code such as `B0001`) | Two overlapping mutable views in one system | A parameter set or a disjoint filter | [ECS](#ecs-the-price-of-the-dynamic-world) |
| `RefCell already borrowed` or `RefCell already mutably borrowed` panic, or a hang on a nested `lock()` | Shared state behind `Rc<RefCell<_>>` or `Arc<Mutex<_>>`, re-entered during dispatch | Row 1 of the structure table | [Do not do this](#do-not-do-this) |
| A routine must pause mid-work and continue next tick | - | A `resume(&mut self, &mut State)` trait | [Suspendable routines](#suspendable-routines-over-shared-state) |
| `implementation of Coroutine is not general enough` | A coroutine resume argument is not higher-ranked | Same as the row above | [Suspendable routines](#suspendable-routines-over-shared-state) |

## Do not do this

| Move | What actually happens |
| --- | --- |
| `Rc<RefCell<State>>` cloned into every handler, re-borrowed during dispatch | The `E0499` becomes a `RefCell already borrowed` or `RefCell already mutably borrowed` panic the first time one handler calls another. The compile error told you the truth |
| `Arc<Mutex<State>>` inside one thread, re-locked during dispatch | The nested `lock()` never returns. std leaves the outcome unspecified: it can deadlock or panic. A deadlock gives no output and no backtrace, and it needs no load to happen |
| `unsafe { &mut *ptr }` to hand two handlers the state | Two live `&mut` to one place are undefined behavior. Miri rejects it under Stacked Borrows and Tree Borrows |
| `async fn(&mut State)` as a suspendable routine | `E0499` before any executor runs. No version of this works |
| An ECS taken for ergonomics, not for an open component set | You pay run-time conflict panics for a component set the compiler could have checked |
| `std::mem::take(&mut st.handlers)`, then `st.handlers = hs` | Every handler registered during the tick is silently dropped. Call `hs.append(&mut st.handlers)` first |
| A bare `usize` slot key when slots are removed or reused | The key names a different slot, or an out-of-bounds slot, with no error. Use a generational key |

The first two rows are about re-entrant dispatch inside one synchronous loop. Under a runtime
the same shapes read differently: `Arc<Mutex<State>>` across separate tasks is a valid,
serializing choice.

## Verify

The change is complete when every row that applies to it is green.

| Claim | Check | What a green result does not prove |
| --- | --- | --- |
| The loop, handlers, and state borrow correctly (structure rows 1 and 2) | `cargo check --locked --all-targets` on the crate | Nothing about a `RefCell` or `Mutex` that remains, or about ECS access |
| No re-entrant `RefCell` or `Mutex` path remains | `rg -e 'Rc<RefCell<' -e 'Arc<Mutex<'` over the state and handler types. Then a test that dispatches one event through every handler, including a handler that triggers another, under the timeout below | Paths the test does not reach. A cell behind a type alias |
| A handler that enqueues cannot stall the tick | A test with a handler that enqueues on every event. Run one tick under the timeout below | Handlers that enqueue only on some events |
| No ECS access conflict | A test that initializes and runs every real schedule once against an empty world | Systems added to a schedule at run time |
| Dispatch that still contains `unsafe` does not alias | When a nightly toolchain with the `miri` component is installed, `cargo +nightly miri test --locked` on the dispatch tests. Otherwise report the dispatch as not checked by Miri | Paths the tests do not reach |

The `rust-sanitizers-miri` skill, when it is installed, owns the Miri flags and the Stacked
Borrows and Tree Borrows policy.

A re-locked `Mutex` usually fails as a hang (std may also panic), and an always-enqueuing
`while let` drain fails as a hang. libtest warns after 60 seconds and never ends the test.
Build the state and run one tick inside `std::thread::spawn`. Send `()` on a
`std::sync::mpsc` channel when the tick returns. Assert
`rx.recv_timeout(Duration::from_secs(5)).is_ok()`. A panic in the thread drops the sender, so
the same assert also catches a `RefCell` panic. If cargo-nextest is installed,
`slow-timeout = { period = "5s", terminate-after = 1 }` under `[profile.default]` in
`.config/nextest.toml` also ends a hung test.

Read `references/review-checklist.md` when you review an existing loop. It asks one question
per defect class in this skill.

## The loop owns both, separately

Put the handler collection inside the state and dispatch `&mut State` into the handlers, and
the call cannot type-check. The iterator holds a mutable borrow of `*st` for the whole loop
body, so the `&mut State` argument is a second mutable borrow of the same place:

```rust,compile_fail,E0499
struct Event(u32);
struct State { counter: u32, handlers: Vec<Box<dyn Handler>> }
trait Handler { fn handle(&mut self, st: &mut State, ev: &Event); }

fn tick(st: &mut State, ev: Event) {
    for h in st.handlers.iter_mut() {
        h.handle(st, &ev);
    }
}
```

No interior mutability fixes this. Move the collection out. Two locals in the loop are two
independent owners, so the two borrows are provably disjoint:

```rust,run
struct Event(u32);
struct State { counter: u32 }
trait Handler { fn handle(&mut self, st: &mut State, ev: &Event); }

struct Add;
impl Handler for Add {
    fn handle(&mut self, st: &mut State, ev: &Event) { st.counter += ev.0; }
}
struct Double;
impl Handler for Double {
    fn handle(&mut self, st: &mut State, _ev: &Event) { st.counter *= 2; }
}

fn tick(handlers: &mut [Box<dyn Handler>], st: &mut State, ev: Event) {
    for h in handlers.iter_mut() { h.handle(st, &ev); }
}

fn main() {
    let mut handlers: Vec<Box<dyn Handler>> = vec![Box::new(Add), Box::new(Double)];
    let mut st = State { counter: 0 };
    tick(&mut handlers, &mut st, Event(3));   // (0 + 3) * 2
    tick(&mut handlers, &mut st, Event(4));   // (6 + 4) * 2
    assert_eq!(st.counter, 20);
    println!("counter={}", st.counter);       // counter=20
}
```

When an existing codebase cannot move the field yet, use one of two repairs:

- Group the rest of the state in a sub-struct, make the handler trait take that sub-struct,
  and dispatch `&mut st.rest`. `st.handlers` and `st.rest` are disjoint field borrows, so the
  handler field can stay.
- Use `std::mem::take(&mut st.handlers)` for the tick only when a handler must also mutate the
  handler set. The put-back is the trap: a handler that registers a new handler during the
  tick puts it into the empty field, and a plain assignment drops it. Append the newcomers
  first. Read the "Migration" section of `references/state-partitioning.md` for the runnable
  version and its panic limit.

## Drain the queue by value

`front()` returns a reference tied to `*st`. The reference is an argument of the dispatch
call, so NLL keeps it live across the call, and the whole state stays borrowed (`E0502`).
`pop_front()` produces an owned `Event`, so no borrow of the state survives into the
handler, and a handler can push more events back:

```rust,run
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
`&mut State` argument is then a second borrow. `Caching { cache: &mut st.caches[0] }`
followed by `h.handle(st)` is `E0499`, "first borrow later used by call". Store the slot
instead, `struct Caching { slot: usize }`, and resolve it at the top of each call:
`st.caches[self.slot].hits += 1`. Handler construction then does not touch the state, so one
registry serves every tick. A handler that needs two slots at once resolves both keys in one
call with `st.caches.get_disjoint_mut([a, b])` (Rust 1.86+). An overlapping or out-of-range
pair is an `Err`, not a panic.

A bare `usize` goes stale with no error when a slot is removed or reused. Use a generational
key when slots are freed. Read the "Key-holding handler" section of
`references/state-partitioning.md` for the diagnostic, the runnable version, and the
staleness rules.

## State is a trait parameter, not an associated type

A handler that must work against any state cannot use an associated type. The state then
appears only in the associated-type value, which does not constrain the impl:

```rust,compile_fail,E0207
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
8 | impl<S> Handler for Standalone {
  |      ^ unconstrained type parameter
help: use the type parameter `S` in the `Standalone` type and use it in the type definition
```

Do not take that help. `struct Standalone<S>` makes one handler type per state and defeats
the point. Put the state on the trait: `trait Handler<S> { fn on_mouse(&mut self, st: &mut S,
m: &Mouse); }`. `Handler<S>` is a trait reference, so `S` is constrained by construction. The
trait stays dyn compatible, because the state is a trait parameter and not a method type
parameter. Each handler bounds `S` by the capability traits it needs,
`impl<S: TimeState> Handler<S> for Timed`, and the bounds are the documentation.

**A blanket impl is a one-way door.** Stable Rust has no specialization.
`impl<S> Handler<S> for Standalone` overlaps every concrete state, so a later
`impl Handler<App> for Standalone` is `E0119`. A bounded blanket impl,
`impl<S: TimeState> Handler<S> for Standalone`, closes the same door for every state that
satisfies its bounds. Write a blanket impl only when one body serves every state that meets
its bounds. Write the unbounded form only for a handler that ignores the state forever. Put
behavior that differs per state behind a capability-trait method, not in a second impl. Two
blanket impls on **different** `Self` types with different bounds coexist without error.

Read the "Capability traits" section of `references/state-partitioning.md` when you write the
registry, cut a god object into capability traits, or pass a `&mut dyn Capability` state
(`S: ?Sized`). It holds the runnable registry and the `E0119` diagnostic.

## Static plus dynamic state, no DerefMut

A context that carries a compile-time state next to a dynamic world invites a `DerefMut`, so
that `ctx.frame` reaches the static half. Do not add it. Auto-deref rewrites `&mut ctx.frame`
into `&mut DerefMut::deref_mut(&mut *ctx).frame`, which borrows all of `ctx`. Disjoint-field
reasoning is then gone, and one field borrow plus one accessor call such as `ctx.world_mut()`
is `E0499`.

Expose both halves as plain fields. Field access is a place expression, so
`&mut ctx.statics.frame` and `&mut ctx.world` are disjoint. When the split must sit behind a
method, return both halves from one call: `fn split(&mut self) -> (&mut S, &mut World)`. One
accessor per half is the shape that fails. Read the "Static plus dynamic state" section of
`references/state-partitioning.md` for the diagnostic and all three versions as checked code.

## ECS: the price of the dynamic world

An ECS-shaped world is the right answer when the component set is decided at run time. The
price is that the borrow checker no longer sees the accesses. A system that asks for two
overlapping mutable views of one component type builds with zero errors, and the library
reports the conflict as a run-time panic. Three rules cover the cost:

1. **The check runs when the schedule initializes the system parameters, before the system
   body executes.** A run condition that returns false does not hide the conflict, and an
   empty world does not hide it. Only a schedule that never runs hides it. Run every schedule
   once in a test.
2. **The default message can name nothing.** Enable the library's debug feature in
   development and CI builds, so the panic names the system, the parameter, and the
   component. Cargo features cannot differ per profile, so enable it through a dev-dependency
   for tests and your own crate feature for `cargo run`.
3. **The repair is a parameter set, not a restructure.** Put the conflicting views in the
   library's parameter-set type and reach them one at a time. A disjoint filter on the two
   views is the better repair when they cover different entities.

Read the "ECS trade" section of `references/state-partitioning.md` when you choose an ECS or
repair a conflict panic. It has the trade table, a `bevy_ecs` 0.19.1 reproduction, the
repair, and the feature setup.

## Suspendable routines over shared state

A routine that must pause mid-work and continue next tick does not need `async`. Give it a
trait whose step method takes the state. Every call takes a fresh reborrow by construction,
which is the property the loop needs:

```rust,run
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
    while !routines.is_empty() {
        routines.retain_mut(|routine| {
            matches!(routine.resume(&mut st), Step::Pending)
        });
    }
    assert_eq!(st.counter, 5);
    println!("counter={}", st.counter);   // counter=5
}
```

The cost: you write the state machine by hand, as fields on the routine struct. No `.await`
sugar exists for this shape on stable or nightly.

`Future::poll` takes `&mut Context<'_>` and nothing else, so it has no slot for a
caller-supplied `&mut State`. An `async fn(&mut State)` holds the borrow for the whole life
of the future. Use `async` only for routines that own everything they touch. When two futures
must touch one struct, hand each a `&mut` to a **different field** before the futures are
created. The `rust-async-internals` skill owns that case.

No escape works. A `*mut State` smuggled through `Waker::data()` does not survive
`FuturesUnordered`, and two `&mut State` made from it are undefined behavior.
`Context::ext()` (nightly) is `()` under tokio, so every downcast returns `None` with no
diagnostic. Nightly coroutines fail with `implementation of Coroutine is not general enough`.
Read `references/coroutines-and-generators.md` when someone proposes one of these escapes, a
stable generator crate, `std::ops::Generator`, or a `gen` block as the fix.

## Related skills

Use these skills when they are installed:

| Skill | Boundary |
| --- | --- |
| `rust-async-internals` | Everything under a runtime: `select!`, `JoinSet`, waker plumbing, cancellation, and two futures over disjoint fields of one struct |
| `rust-compiler-errors` | `E0499` and `E0502` as diagnostics, with the general repairs |
| `rust-discipline` | `Deref` on non-pointer types, blanket impls and semver |
| `rust-unsafe` | The aliasing rules and the Miri reproduction behind the raw-pointer rows |
| `rust-iterator-impl` | `iter::from_fn` for a routine that only yields values. The `Generator` to `Coroutine` rename and the `gen` block status |
| `rust-crate-architecture` | Which crate the handler trait and the state type live in |
