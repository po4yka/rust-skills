# Review checklist for an event loop

Read it when you review an existing event loop, tick loop, or handler registry. Each question
names one defect class from `SKILL.md` and the repair.

1. Is the handler collection a field of the state, or does the tick iterate a collection it
   also passes into the call? Separate the owners.
2. Does dispatch borrow the event out of the state? Pop it by value.
3. Can a handler push events? Drain one batch per tick, not `while let`.
4. Does any handler struct hold a `&` or `&mut` into the state? Replace it with a key. Use a
   generational key when slots are freed.
5. Does the handler trait use `type State`? Make it `Handler<S>`.
6. Is there a blanket `impl<S: ...> Handler<S> for X`? No per-state impl of `Handler` for `X`
   can follow for a state that meets its bounds.
7. Does a context wrapper implement `DerefMut`? Delete it and use plain fields.
8. Is an ECS proposed? Name the run-time input that decides the component set. No such input,
   no ECS. An ECS already in use needs the schedule test and the debug feature in CI.
9. Is a routine a `Future` so it can hold `&mut State` across a suspend point? Rewrite it as
   `fn resume(&mut self, st: &mut State) -> Step`.
10. Does shared state sit behind `Rc<RefCell<_>>` or `Arc<Mutex<_>>` inside one synchronous
    loop, or does dispatch make a `&mut` from a raw pointer? Return to row 1 of the structure
    table.
