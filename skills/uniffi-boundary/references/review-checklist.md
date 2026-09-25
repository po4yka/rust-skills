# UniFFI boundary review checklist

Answer every item before you merge a change to the boundary crate.

1. Is `setup_scaffolding!()` present once, in the crate root, with no `.udl` file?
2. Is every exported Object `Send + Sync` without a manual `unsafe impl`, and free of `Cell`,
   `RefCell`, `Rc`, and raw pointer fields?
3. Is every new type on the correct side of the Record and Object line?
4. Is every Record field a UniFFI type, with no inner-crate type leaking through?
5. Is every borrow a top-level shared argument, with no borrowed return, no `&[u8]` in an async
   export, and no reference in a foreign-trait method?
6. Does every fallible export return `Result<_, E>` with a `uniffi::Error` type?
7. Can any export panic? Is the clippy lint set in `lib.rs`, and is every non-throwing export
   panic-free?
8. Does a large byte buffer cross by value? Move it to a file path.
9. Is each new method a whole operation, not a getter that a caller runs in a loop?
10. Does every callback trait declare `Send + Sync`, return `Result` with a UniFFI error that
    implements `From<UnexpectedUniFFICallbackError>`, and stay coarse?
11. Is each callback handle released when the job ends, with no cycle across the boundary?
12. Does job registration follow the `ffi-error-progress-cancel` design: duplicate rejection,
    pre-cancel, RAII removal, and poison recovery on non-throwing paths?
13. Does the change add computation to the boundary crate, or make an inner crate depend on
    it?
14. Does the change reshape an existing export where an added method or a wider JSON contract
    would do? Are enum changes coordinated with both consumers?
15. Were the Kotlin and Swift bindings regenerated from the same build?
16. Does each new `async fn` return a `Send` future, stay drop-safe at every `.await`, and
    avoid an async primary constructor? Does it declare `async_runtime = "tokio"` when it uses
    Tokio resources, or spawn onto the process runtime `Handle` when the crate owns one?
17. Does every new custom type round trip losslessly?
18. Do engine Objects use the host scheduler or one process runtime, with idempotent
    initialization and non-blocking callback release?
19. Does every form match the pinned UniFFI version in the version floor table in
    [SKILL.md](../SKILL.md)?

If the answer to any item is wrong, revise the change before you merge it.
