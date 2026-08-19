# Review checklist

The pre-merge checklist for `rust-discipline`. Every rule it names is stated in full in
[`../SKILL.md`](../SKILL.md) or in one of the other reference files.

## Apply it to every changed API

Apply this checklist to every changed `pub` or `pub(crate)` API, and to every Rust pull
request.

**API design**

1. Any `&String`, `&Vec<T>`, or `&PathBuf` parameter? Use `&str`, `&[T]`, `&Path`, or
   `impl AsRef<...>`.
2. Any `&'a mut Trait` stored in a struct field? Use a generic `H: Trait`, plus forwarding impls
   that carry `+ ?Sized` and delegate through `H::method(self, ..)`.
3. Any callback without `for<'a>` where the caller must not keep the reference? Add the HRTB.
4. Any `pub` accessor that returns `&mut Vec<T>` or `&mut String`? Return `&mut [T]` or
   `&mut str`, and name each length-changing operation. Any public bound that names `&&T`?
5. Any callback stored as `Box<dyn FnMut>` where `Box<dyn Fn>` works? Any `Weak` callback
   registry that drops registrations silently?
6. Any `Fn` bound picked from the `move` keyword instead of the body? Any callback method whose
   lifetime sits on the `impl` block instead of the method?

**Panics, errors, and resources**

7. Any new `.unwrap()`, or any bare `.expect()` with no invariant in the message, outside
   tests?
8. Any `Box<dyn std::error::Error>` returned from a library crate?
9. Any raw `i32` file descriptor held across an error path? Any `Drop` impl with no documented
   ordering?
10. Any `_ =>` arm in a match over an internal enum? Any `downcast_ref` chain over a closed set
    of types?

**Performance and concurrency**

11. Any allocation inside an event-loop tick, a per-item decode loop, or a parser hot path?
12. Any lock held across `.await`? Any `RwLock` that protects a write-heavy field? Any `rayon`
    parallel iterator mixed with async code? Any `Condvar::wait` outside a predicate loop or a
    `wait_while` call?
13. Any new atomic with no `// Ordering:` comment? Any `Relaxed` on a publish/subscribe flag?
14. Any blocking syscall inside async with no `spawn_blocking` and no dedicated thread? Any
    blocking I/O inside a `rayon` task?

**Unsafe, FFI, and lints**

15. Any internal `unsafe fn` with no `# Safety` rustdoc section? Any `unsafe` block with no
    `// SAFETY:` comment?
16. Any FFI entry point that can panic instead of returning a `Result`?
17. Any new `#[allow(clippy::correctness | suspicious)]`? Any new `deny.toml` ignore with no
    tracking issue and no expiry?

**Trait and type-system traps** (details in
[`references/type-and-trait-traps.md`](references/type-and-trait-traps.md),
[`references/trait-resolution.md`](references/trait-resolution.md), and
[`references/data-shape-traps.md`](references/data-shape-traps.md))

18. Any `impl Drop` on a struct where a field must be consumed? Use a dedicated guard type
    with `ManuallyDrop`.
19. Any `fn(T) -> T` that takes a struct past the target's inline-copy boundary (128 bytes on
    x86_64, 256 on aarch64) on a hot path?
20. Any custom `PartialEq` with no matching custom `Hash`, or the reverse, on a `HashMap` or
    `HashSet` key?
21. Any `#[derive(Clone)]` on a struct that contains `Arc<T>` where the caller might expect an
    isolated copy?
22. Any `Deref` impl on a newtype that is not a smart pointer? Any `Deref` relied on to satisfy
    a trait bound or a `dyn Trait` coercion? Neither one walks the deref chain.
23. Any migration from `std::sync::Mutex` to `parking_lot` or `tokio::sync::Mutex` that relied
    on poison detection?
24. Any unchecked arithmetic on a value derived from untrusted input?
25. Any `Arc<T>` that points back to its parent container?
26. Any function that takes `&'a T` and also writes references into a storage parameter that
    shares the same `'a`? Split the lifetimes, or store owned data.
27. Any `impl<T: ...> PubTrait for T` on a public trait that is not sealed? Seal the trait, or
    write explicit per-type impls. The same blanket impl also makes every pointer-forwarding
    impl `E0119`, and blocks every later concrete impl on the same `Self` type.
28. Any foreign trait implemented for `Rc<Local>`, `Arc<Local>`, or `Vec<Local>`? Only `&T`,
    `&mut T`, and `Box<T>` are `#[fundamental]`; the rest is `E0117`. Newtype the wrapper.
29. Any `Box::new([T; N])`, or any return of `[T; N]` by value, for `N` over 16 KiB? Use
    `Vec::into_boxed_slice` or `Box::new_uninit_slice`. `into_boxed_slice` may cost a full copy
    when capacity is meaningfully above length; collect into `Box<[T]>` directly when the length
    is exact.
30. Any extension-trait method whose name already exists on the type, or on a type in its deref
    chain? The shadowing is silent, and adding the method to a published trait breaks downstream
    builds with `E0034`.
31. Any `impl From<X> for Y` beside an `impl TryFrom<X> for Y`? The `core` blanket impl makes
    the pair `E0119`, and the choice between them is permanent.

If the answer to any item is yes, revise the change before you merge it.
