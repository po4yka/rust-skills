# Data-shape traps

Read this file when a diff adds a `HashMap` or `HashSet` key type, reverses or truncates text, or
builds a fixed-size array for heap residence. Each trap is silent on an ASCII fixture or a small
value, and appears with real data or on a constrained stack.

Each item states a severity, a wrong example, a correct example, and a rule.

---

## `Hash` and `PartialEq` contract violation

**Severity: CRITICAL**

The standard library requires that `k1 == k2` implies `hash(k1) == hash(k2)`. If you write
`PartialEq` by hand and derive `Hash`, or the reverse, `HashMap` and `HashSet` return silently
incorrect results.

```rust
// BUG: the derived Hash uses the original case; the manual PartialEq ignores case.
#[derive(Hash)]
struct Tag(String);
impl PartialEq for Tag {
    fn eq(&self, other: &Self) -> bool {
        self.0.to_lowercase() == other.0.to_lowercase()
    }
}
impl Eq for Tag {}
// HashSet<Tag> stores "Foo" and "foo" as two different entries.
```

Rule: when you write a custom `PartialEq`, write a matching custom `Hash` that hashes the same
normalized form. Add a test that inserts through one form and looks up through the other.

---

## `chars().rev()` corrupts combining marks and ZWJ sequences

**Severity: CRITICAL**

A `char` is a Unicode scalar value, not a user-visible character. Reversing scalars moves a
combining mark onto the character that preceded it, and reverses the order of a ZWJ emoji
sequence. The result is still valid UTF-8, so nothing errors and no lint fires.

Measured on rustc 1.97.0, edition 2024, with `s.chars().rev().collect::<String>()`:

| Input | Output | Effect |
| --- | --- | --- |
| `"noe\u{301}l"` | `"l\u{301}eon"` | the acute accent moved from `e` to `l` |
| `"\u{1F469}\u{200d}\u{1F680}"` | `"\u{1F680}\u{200d}\u{1F469}"` | the ZWJ order reversed |
| `"abc"` | `"cba"` | correct, which is why an ASCII fixture passes |

```rust
// BAD: reverses scalar values, not characters. "noe\u{301}l" becomes
// "l\u{301}eon" — U+006C U+0301 U+0065 U+006F U+006E — which renders as "ĺeon".
fn reverse(text: &str) -> String {
    text.chars().rev().collect()
}

// GOOD: reverse grapheme clusters, from the `unicode-segmentation` crate.
// text.graphemes(true).rev().collect::<String>()
```

Rule: std has no correct reverse for arbitrary text. Use `graphemes(true)` from the
`unicode-segmentation` crate. The rule covers only the operations where order or user-visible
character boundaries matter: reverse, truncate, centre, pad, and per-character iteration for
display. `chars().count()`, `chars().filter()`, and byte-oriented parsing of a known ASCII grammar
do not reorder text and are not affected.

---

## Large stack arrays and the `Box::new([0u8; N])` pitfall

**Severity: WARNING**

`Box::new([0u8; N])` does not allocate `N` bytes directly on the heap. The expression first
builds `[0u8; N]` on the caller's stack, then `Box::new` copies it into a heap allocation. A
debug build performs no placement optimization, so the stack copy is always materialized. It
overflows a constrained thread stack — mobile and embedded targets commonly give a thread
about 1 MiB to 2 MiB — at roughly `N >= 256 KiB`. A release build sometimes removes the copy
through NRVO, but that optimization is fragile. Any intermediate
`let buf = Box::new([0u8; N]);` can materialize the stack copy again.

```rust
// BAD: overflows the stack in debug; relies on brittle NRVO in release.
let buf: Box<[u8; 1024 * 1024]> = Box::new([0u8; 1024 * 1024]);

// BAD: returning a large array by value forces a memcpy through the stack.
fn make_buf() -> [u8; 1024 * 1024] { [0u8; 1024 * 1024] }

// GOOD: allocate on the heap from the start.
let buf: Box<[u8]> = vec![0u8; 1024 * 1024].into_boxed_slice();

// GOOD (Rust 1.82 or later): allocate directly, with no zeroed stack temporary.
let buf: Box<[u8]> = unsafe {
    let mut b = Box::<[u8]>::new_uninit_slice(1024 * 1024);
    std::ptr::write_bytes(b.as_mut_ptr().cast::<u8>(), 0, 1024 * 1024);
    b.assume_init()
};
```

Rule: build any array larger than 16 KiB for heap residence with `Vec::into_boxed_slice` or
`Box::new_uninit_slice`. Never write `Box::new([T; N])` for a large `N`, and never return
`[T; N]` by value for a large `N`. Hot-path code additionally falls under the no-allocation
rule in the main skill.

`Vec::into_boxed_slice` is not free. It calls `shrink_to_fit` whenever capacity exceeds length,
which issues a `realloc` that may move the buffer. Measured with a `Vec<u32>` at length 3:
capacity 3 and capacity 4 keep the data pointer; capacity 8 and capacity 1000 move it. State the
cost as "may cost a full copy when capacity is meaningfully above length", not as "always
copies". The reverse direction has no such cost: `<[T]>::into_vec` never reallocates. When the
length is exact, build the boxed slice straight from the iterator, which allocates once:

```rust
let squares: Box<[u32]> = (0..1024u32).map(|n| n * n).collect();
```

Find candidates:

```bash
rg "Box::new\(\s*\[0?[a-z0-9_]+\s*;\s*[0-9]{4,}" --type rust -n
rg "fn .* -> \[[a-z0-9_]+\s*;\s*[0-9]{4,}\]" --type rust -n
```
