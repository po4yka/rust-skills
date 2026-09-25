# State partitioning for an event loop

Deep material for `SKILL.md`: the full diagnostics and runnable versions of the examples it
compresses, the generic-state registry in full, and the ECS trade in detail.

- [Migration: the handlers already live in the state](#migration-the-handlers-already-live-in-the-state)
- [Queue drain diagnostic](#queue-drain-diagnostic)
- [Key-holding handler](#key-holding-handler), with the `E0499` of a `&mut`-holding handler
- [Capability traits: cutting the god object](#capability-traits-cutting-the-god-object), with the blanket-impl `E0119` and the `?Sized` state
- [Static plus dynamic state: three versions](#static-plus-dynamic-state-three-versions)
- [ECS trade](#ecs-trade): the `bevy_ecs` reproduction, the repair, and the test rule

Every `rust,run` block here compiles and runs on rustc 1.98.1, edition 2024. The two
`bevy_ecs` blocks are not checked automatically. Their output comes from a manual run of
bevy_ecs 0.19.1 on rustc 1.98.1.

## Migration: the handlers already live in the state

The `compile_fail` block in `SKILL.md` (handlers as a field of `State`, dispatched from
`st.handlers.iter_mut()`) gives:

```text
error[E0499]: cannot borrow `*st` as mutable more than once at a time
6 |     for h in st.handlers.iter_mut() {
  |              ----------------------
  |              first mutable borrow occurs here / first borrow later used here
7 |         h.handle(st, &ev);
  |                  ^^ second mutable borrow occurs here
```

This is the whole `mem::take` pattern, including the trap. A handler may register a new
handler while the tick runs. Those newcomers land in `st.handlers`, which `mem::take` left
empty, so a plain `st.handlers = hs` at the end throws them away. Append first.

```rust,run
struct Event(u32);
trait Handler { fn handle(&mut self, st: &mut State, ev: &Event); }

#[derive(Default)]
struct State { counter: u32, handlers: Vec<Box<dyn Handler>> }

struct Spawner;
impl Handler for Spawner {
    fn handle(&mut self, st: &mut State, _ev: &Event) { st.handlers.push(Box::new(Count)); }
}
struct Count;
impl Handler for Count {
    fn handle(&mut self, st: &mut State, ev: &Event) { st.counter += ev.0; }
}

fn tick(st: &mut State, ev: Event) {
    let mut hs = std::mem::take(&mut st.handlers);
    for h in hs.iter_mut() {
        h.handle(st, &ev);
    }
    hs.append(&mut st.handlers);        // keep handlers registered during this tick
    st.handlers = hs;
}

fn main() {
    let mut st = State::default();
    st.handlers.push(Box::new(Spawner));
    tick(&mut st, Event(5));            // Spawner adds a Count
    assert_eq!(st.handlers.len(), 2);
    tick(&mut st, Event(5));            // the Count now runs
    assert_eq!(st.counter, 5);
    println!("counter={} handlers={}", st.counter, st.handlers.len());   // counter=5 handlers=3
}
```

`mem::take` needs `Vec<Box<dyn Handler>>: Default`, which every `Vec` has. It is a pointer
swap and allocates nothing. Two limits to know before you keep it:

- A panic between the take and the put-back loses the whole handler set. This matters when
  anything uses the state after the panic: `catch_unwind`, a poisoned `Mutex` recovered with
  `PoisonError::into_inner`, or a thread that outlives a panicking worker. Move the field out
  for good in that case.
- A handler that reads `st.handlers.len()` sees an empty or partial list during the tick.

Treat this as a migration step. The end state is a `State` with no handler field.

## Queue drain diagnostic

`while let Some(ev) = st.queue.front() { handle(st, ev); }` keeps the reference from
`front()` live across the dispatch call, so the whole state stays borrowed:

```text
error[E0502]: cannot borrow `*st` as mutable because it is also borrowed as immutable
8 |     while let Some(ev) = st.queue.front() {
  |                          -------- immutable borrow occurs here
9 |         handle(st, ev);
  |         ------^^^^^^^^
  |         mutable borrow occurs here / immutable borrow later used by call
```

## Key-holding handler

A handler built from a field of the state carries that borrow into every dispatch.
`struct Caching<'a> { cache: &'a mut Cache }`, constructed as
`Caching { cache: &mut st.caches[0] }` and then dispatched with `h.handle(st)`, gives:

```text
error[E0499]: cannot borrow `*st` as mutable more than once at a time
10 |     let mut h = Caching { cache: &mut st.caches[0] };
   |                                       --------- first mutable borrow occurs here
11 |     h.handle(st);
   |       ------ ^^ second mutable borrow occurs here
   |       first borrow later used by call
```

This is the shape that works. The handler is constructed without touching the state, so the same registry serves
every tick. A handler that needs two slots at once resolves both keys with one
`get_disjoint_mut` call (Rust 1.86+). An overlapping or out-of-range pair returns `Err`
instead of a panic:

```rust,run
struct Cache { hits: u32 }
struct State { caches: Vec<Cache> }

trait Handler { fn handle(&mut self, st: &mut State); }

struct Caching { slot: usize }
impl Handler for Caching {
    fn handle(&mut self, st: &mut State) {
        let n = st.caches.len() as u32;
        st.caches[self.slot].hits += n;
    }
}
struct Transfer { from: usize, to: usize }
impl Handler for Transfer {
    fn handle(&mut self, st: &mut State) {
        let Ok([from, to]) = st.caches.get_disjoint_mut([self.from, self.to]) else { return };
        to.hits += from.hits;
        from.hits = 0;
    }
}

fn main() {
    let mut st = State { caches: vec![Cache { hits: 0 }, Cache { hits: 0 }] };
    let mut handlers: Vec<Box<dyn Handler>> = vec![
        Box::new(Caching { slot: 0 }),
        Box::new(Transfer { from: 0, to: 1 }),
        Box::new(Transfer { from: 1, to: 1 }),   // overlapping keys: skipped, no panic
    ];
    for h in handlers.iter_mut() { h.handle(&mut st); }
    assert_eq!((st.caches[0].hits, st.caches[1].hits), (0, 2));
    println!("hits={} {}", st.caches[0].hits, st.caches[1].hits);   // hits=0 2
}
```

The cost of this shape is index staleness, and it is not a compile error. `Vec::remove`
shifts every later element left, so every stored `slot` above the removed index now names a
different cache. `Vec::swap_remove` moves the last element into the removed index, so exactly
two slots change meaning and the old last index goes out of bounds. Two repairs, in order of
preference:

- Never remove. Replace the slot content with a tombstone and reuse the slot.
- Store a generational key: `struct Key { slot: u32, generation: u32 }`, and bump the slot's
  generation on every reuse. A `handle` that finds a generation mismatch returns without
  writing. Do not name the field `gen`: it is a reserved keyword in edition 2024.

## Capability traits: cutting the god object

The god object stays one struct. What you cut is the **view** each handler gets of it. One
capability trait per group of fields a handler needs together:

| Rule | Reason |
| --- | --- |
| One trait per capability, not one trait per field | A handler that needs three fields would carry three bounds, and the bound list becomes the type signature of the state |
| Methods, not field accessors | `fn now(&mut self) -> u64` lets the state compute or cache. `fn tick_field(&mut self) -> &mut u64` freezes the layout |
| Name the capability, not the owner | `TimeState`, `InputState`, `RenderTargets`. A trait named after the struct it came from cannot be implemented by a second state |
| The loop's concrete state implements all of them | The registry is `Vec<Box<dyn Handler<App>>>`, so `App` must satisfy the union of every bound in the registry |

Three handlers with three different bounds, all in one registry, dispatched together:

```rust,run
struct Mouse;

trait TimeState { fn now(&mut self) -> u64; }
trait CounterState { fn bump(&mut self); }

trait Handler<S> { fn on_mouse(&mut self, st: &mut S, m: &Mouse); }

struct Standalone;
impl<S> Handler<S> for Standalone {
    fn on_mouse(&mut self, _st: &mut S, _m: &Mouse) {}
}
struct Timed { last: u64 }
impl<S: TimeState> Handler<S> for Timed {
    fn on_mouse(&mut self, st: &mut S, _m: &Mouse) { self.last = st.now(); }
}
struct Both;
impl<S: TimeState + CounterState> Handler<S> for Both {
    fn on_mouse(&mut self, st: &mut S, _m: &Mouse) { let _ = st.now(); st.bump(); }
}

struct App { tick: u64, clicks: u32 }
impl TimeState for App { fn now(&mut self) -> u64 { self.tick += 1; self.tick } }
impl CounterState for App { fn bump(&mut self) { self.clicks += 1; } }

fn main() {
    let mut app = App { tick: 0, clicks: 0 };
    let mut handlers: Vec<Box<dyn Handler<App>>> =
        vec![Box::new(Standalone), Box::new(Timed { last: 0 }), Box::new(Both)];
    for h in handlers.iter_mut() { h.on_mouse(&mut app, &Mouse); }
    assert_eq!(app.tick, 2);
    assert_eq!(app.clicks, 1);
    println!("tick={} clicks={}", app.tick, app.clicks);   // tick=2 clicks=1
}
```

The three impls monomorphize to `Handler<App>` at the registration site, and each concrete
type gets its own `dyn Handler<App>` vtable. Nothing is dynamic at run time except the
handler dispatch itself.

### The blanket impl and `E0119`

`impl<S> Handler<S> for Standalone` overlaps every concrete state, and stable Rust has no
specialization. Adding `impl Handler<App> for Standalone` later gives:

```text
error[E0119]: conflicting implementations of trait `Handler<App>` for type `Standalone`
 5 | impl<S> Handler<S> for Standalone {
   | --------------------------------- first implementation here
10 | impl Handler<App> for Standalone {
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ conflicting implementation for `Standalone`
```

`impl<S: TimeState> Handler<S> for Standalone` gives the same `E0119` while
`App: TimeState` holds.

### `?Sized` when the state is a trait object

Add `S: ?Sized` to the trait and to every impl when the loop wants to pass a `&mut dyn
Capability` rather than a concrete state. Without it, `S` carries an implicit `Sized` bound
and the trait-object state is rejected:

```rust,run
struct Mouse;

trait TimeState { fn now(&mut self) -> u64; }

trait Handler<S: ?Sized> { fn on_mouse(&mut self, st: &mut S, m: &Mouse); }

struct Timed { last: u64 }
impl<S: TimeState + ?Sized> Handler<S> for Timed {
    fn on_mouse(&mut self, st: &mut S, _m: &Mouse) { self.last = st.now(); }
}

struct App { tick: u64 }
impl TimeState for App { fn now(&mut self) -> u64 { self.tick += 1; self.tick } }

fn main() {
    let mut app = App { tick: 0 };
    let st: &mut dyn TimeState = &mut app;
    let mut h = Timed { last: 0 };
    h.on_mouse(st, &Mouse);
    assert_eq!(h.last, 1);
    println!("last={}", h.last);        // last=1
}
```

`?Sized` costs nothing when it is not used. Adding it later does not break downstream impls,
because it relaxes a bound. Those impls stay `Sized`-only, so a trait-object state still does
not work until every impl is relaxed as well. Write it once, when you write the trait.

## Static plus dynamic state: three versions

The `DerefMut` version is rejected. `&mut ctx.frame` goes through `deref_mut`, which takes
`&mut self` on the whole wrapper, so the second accessor has nothing left to borrow:

```rust,compile_fail,E0499
struct World { entities: Vec<u32> }
struct Static { frame: u64 }
struct Ctx<S> { statics: S, world: World }

impl<S> std::ops::Deref for Ctx<S> {
    type Target = S;
    fn deref(&self) -> &S { &self.statics }
}
impl<S> std::ops::DerefMut for Ctx<S> {
    fn deref_mut(&mut self) -> &mut S { &mut self.statics }
}
impl<S> Ctx<S> {
    fn world_mut(&mut self) -> &mut World { &mut self.world }
}

fn step(ctx: &mut Ctx<Static>) {
    let f: &mut u64 = &mut ctx.frame;
    let w: &mut World = ctx.world_mut();
    w.entities.push(*f as u32);
}
```

```text
error[E0499]: cannot borrow `*ctx` as mutable more than once at a time
17 |     let f: &mut u64 = &mut ctx.frame;
   |                            --- first mutable borrow occurs here
18 |     let w: &mut World = ctx.world_mut();
   |                         ^^^ second mutable borrow occurs here
```

Plain fields compile, because each field borrow names a different place:

```rust,run
struct World { entities: Vec<u32> }
struct Static { frame: u64 }
struct Ctx<S> { statics: S, world: World }

fn step(ctx: &mut Ctx<Static>) {
    let f = &mut ctx.statics.frame;
    let w = &mut ctx.world;
    *f += 1;
    w.entities.push(*f as u32);
}

fn main() {
    let mut ctx = Ctx { statics: Static { frame: 0 }, world: World { entities: Vec::new() } };
    step(&mut ctx);
    step(&mut ctx);
    assert_eq!(ctx.world.entities, [1, 2]);
    println!("{:?}", ctx.world.entities);   // [1, 2]
}
```

When the fields must stay private, give the wrapper one method that returns both halves.
Two accessors, one per half, cannot work: the borrow checker sees two `&mut self` calls.

```rust,run
struct World { entities: Vec<u32> }
struct Static { frame: u64 }
struct Ctx<S> { statics: S, world: World }

impl<S> Ctx<S> {
    fn split(&mut self) -> (&mut S, &mut World) { (&mut self.statics, &mut self.world) }
}

fn step(ctx: &mut Ctx<Static>) {
    let (s, w) = ctx.split();
    s.frame += 1;
    w.entities.push(s.frame as u32);
}

fn main() {
    let mut ctx = Ctx { statics: Static { frame: 0 }, world: World { entities: Vec::new() } };
    step(&mut ctx);
    step(&mut ctx);
    assert_eq!(ctx.world.entities, [1, 2]);
    println!("{:?}", ctx.world.entities);   // [1, 2]
}
```

## ECS trade

| Property | Plain struct plus handler registry | ECS-shaped dynamic world |
| --- | --- | --- |
| Aliasing detection | Compile time, `E0499` and `E0502` | Run time, when the schedule initializes the system parameters |
| Adding a component or field | Edit the state struct. Every crate that names it recompiles | Register a new component type. No shared struct to edit |
| Component set decided by | The crate that defines the state | Plugins, scripts, save files, an editor |
| Cost of a wrong access pattern | The build fails | The process panics, in the first run of the schedule that holds that system |
| Who can add a system | Anyone with the state type in scope | Anyone at all, including at run time |
| Debuggability of a conflict | The compiler names both borrows and both lines | A panic message that names nothing until the debug feature is on |
| Iteration layout | Whatever the struct fields are | Columnar, chosen by the engine |

Take the right column only when a row in it is a requirement, not a convenience. "Adding a
component without editing a shared struct" is a requirement in a plugin host, and a
convenience in a game whose whole component set ships in one binary.

### Reproducing the conflict panic

Two mutably overlapping `Query` parameters in one system. The code compiles with zero errors
and zero warnings:

```rust,ignore
use bevy_ecs::prelude::*;

#[derive(Component)] struct Health(u32);

fn bad_system(mut a: Query<&mut Health>, mut b: Query<&mut Health>) {
    for mut h in a.iter_mut() { h.0 += 1; }
    for mut h in b.iter_mut() { h.0 += 1; }
}

fn main() {
    let mut world = World::new();
    world.spawn(Health(10));
    let mut sched = Schedule::default();
    sched.add_systems(bad_system);
    sched.run(&mut world);              // panics here, not at add_systems
}
```

Default features:

```text
thread 'main' (<tid>) panicked at .../bevy_ecs-0.19.1/src/query/state.rs:216:13:
error[B0001]: <Enable the debug feature to see the name> in system <Enable the debug feature
to see the name> accesses component(s) <Enable the debug feature to see the name> in a way
that conflicts with a previous system parameter. Consider using `Without<T>` to create
disjoint Queries or merging conflicting Queries into a `ParamSet`. See:
https://bevy.org/learn/errors/b0001
```

With `bevy_ecs = { version = "0.19.1", features = ["debug"] }`:

```text
thread 'main' (<tid>) panicked at .../bevy_ecs-0.19.1/src/query/state.rs:216:13:
error[B0001]: Query<&mut Health> in system app::bad_system accesses component(s) Health in a
way that conflicts with a previous system parameter. Consider using `Without<T>` to create
disjoint Queries or merging conflicting Queries into a `ParamSet`. See:
https://bevy.org/learn/errors/b0001
```

The default message names neither the system, nor the query, nor the component. Enable the
debug feature for tests through a dev-dependency. Resolver 2 and later activate a
dev-dependency's features only for targets that need dev-dependencies, so every `cargo test`
gets the names with no flag, and `cargo build` and `cargo run` stay unchanged:

```toml
[dependencies]
bevy_ecs = "0.19.1"

[dev-dependencies]
bevy_ecs = { version = "0.19.1", features = ["debug"] }
```

Edition 2024 selects resolver 3. A virtual workspace has no edition, so set `resolver = "3"`
in its root manifest. Resolver 1 applies the dev-dependency features to every build.

For names in `cargo run` during development, declare a feature of your own,
`ecs-debug = ["bevy_ecs/debug"]` under `[features]`, and run `cargo run --features ecs-debug`.
With the `bevy` crate instead of `bevy_ecs`, write `bevy/debug` in both places. `bevy_ecs/debug`
is an error there, because `bevy_ecs` is not a direct dependency.

### The repair

`ParamSet` makes the two queries disjoint in time instead of in space. `p0()` and `p1()`
each borrow the set mutably, so only one is live at a time:

```rust,ignore
use bevy_ecs::prelude::*;

#[derive(Component)] struct Health(u32);

fn ok_system(mut set: ParamSet<(Query<&mut Health>, Query<&mut Health>)>) {
    for mut h in set.p0().iter_mut() { h.0 += 1; }
    for mut h in set.p1().iter_mut() { h.0 += 1; }
}

fn main() {
    let mut world = World::new();
    let e = world.spawn(Health(10)).id();
    let mut sched = Schedule::default();
    sched.add_systems(ok_system);
    sched.run(&mut world);
    println!("health={}", world.get::<Health>(e).unwrap().0);   // health=12
}
```

`Without<T>` is the other repair, and it is the better one when the two queries were meant to
cover different entities: `Query<&mut Health, With<Player>>` plus
`Query<&mut Health, Without<Player>>` have disjoint access sets, so no parameter set is
needed and both queries stay live at once.

### The test rule

The panic fires when the schedule initializes the system parameters, before the system body
runs. A run condition that returns false does not hide the conflict, and an empty world does
not hide it: `bad_system.run_if(|| false)` in a schedule run once against `World::new()`
panics with the same `B0001`. Only a schedule that never runs hides it. Add one test that
builds every real schedule and runs each once against an empty world. It costs one frame,
and it turns the whole class of conflicts into a test failure.
