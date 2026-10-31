# Generic and dynamic state

Detail for structure rows 2 and 3 of `SKILL.md`: a handler trait reused across states, a
context that pairs static and dynamic state, and an ECS world.

Contents:

- State is a trait parameter, not an associated type
- Static plus dynamic state, no DerefMut
- ECS: the price of the dynamic world

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
