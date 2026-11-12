# Bridge types

Contents:

- Type map
- Shared enums
- Strings
- Vectors
- Smart pointers
- Thread safety
- One C++ type in two bridges

The facts are for cxx 1.0.205.

## Type map

| Rust in the bridge | C++ | Restriction |
|--------------------|-----|-------------|
| `String`, `&str` | `rust::String`, `rust::Str` | None |
| `&[T]`, `&mut [T]` | `rust::Slice<const T>`, `rust::Slice<T>` | No opaque C++ element |
| `Vec<T>` | `rust::Vec<T>` | No opaque C++ element |
| `Box<T>` | `rust::Box<T>` | No opaque C++ type; use it to give C++ an opaque Rust type |
| `[T; N]` | `std::array<T, N>` | No opaque C++ element |
| `&CxxString`, `Pin<&mut CxxString>` | `std::string` | Never by value |
| `&CxxVector<T>`, `UniquePtr<CxxVector<T>>` | `std::vector<T>` | Never by value; no opaque Rust element |
| `UniquePtr<T>`, `SharedPtr<T>` | `std::unique_ptr<T>`, `std::shared_ptr<T>` | No opaque Rust type; `std::default_delete` only |
| `*mut T`, `*const T` | `T*`, `const T*` | The function must be `unsafe fn` |
| `fn(T) -> U` | `rust::Fn<U(T)>` | Rust to C++ only |
| `Result<T>` | throw and catch | Return type only |

C++ code includes `"rust/cxx.h"` for the `rust::` types; `cxx_build` puts it on
the include path.

## Shared enums

A shared enum is a struct with one `repr` field, so a `match` without a `_` arm
is not exhaustive:

```rust,compile_fail,E0004
#[cxx::bridge]
mod ffi {
    enum Mode {
        Fast,
        Safe,
    }
}

fn label(mode: ffi::Mode) -> &'static str {
    match mode {
        ffi::Mode::Fast => "fast",
        ffi::Mode::Safe => "safe",
    }
}

fn main() {
    println!("{}", label(ffi::Mode::Fast));
}
```

Add `_ => "unknown"`. To bind an enum that a C++ header already defines,
declare the same enum in the bridge and also `type Mode;` in the
`extern "C++"` block: cxx then static-asserts each variant and the base type
instead of emitting a definition.

## Strings

A `CxxString` cannot live on the Rust stack by value. Build one with
`let_cxx_string!`, which gives a `Pin<&mut CxxString>`:

```rust
use cxx::{CxxString, let_cxx_string};

fn byte_len(text: &CxxString) -> usize {
    text.len()
}

fn main() {
    let_cxx_string!(name = "engine");
    name.as_mut().push_str("-1");
    assert_eq!(byte_len(&name), 8);
    assert_eq!(name.to_str(), Ok("engine-1"));
}
```

`to_str()` returns `Err(Utf8Error)` for bytes that are not UTF-8, because a
`std::string` holds any bytes. `as_bytes()` reads them without a check.

## Vectors

`CxxVector<T>::as_slice()` and `push()` need an element type that Rust can
move, which is a primitive or a shared struct, not `CxxString`. Iterate a
vector of strings:

```rust
use cxx::{CxxString, CxxVector};

pub fn collect(names: &CxxVector<CxxString>) -> Vec<String> {
    names.iter().map(|name| name.to_string_lossy().into_owned()).collect()
}

pub fn sum(values: &CxxVector<i32>) -> i64 {
    values.as_slice().iter().map(|&value| i64::from(value)).sum()
}
```

`CxxVector::<T>::new()` returns `UniquePtr<CxxVector<T>>`. Mutate it through
`pin_mut()`.

## Smart pointers

- `UniquePtr<T>`: `as_ref()` and `as_mut()` return `None` for null.
  `pin_mut()` and `*ptr` panic with `called pin_mut on a null UniquePtr<T>` or
  `called deref on a null UniquePtr<T>`.
- `SharedPtr<T>` gives `&T` only, because other owners can alias the object.
  `pin_mut_unchecked()` is `unsafe`. On an opaque C++ type, call it only for a
  non-`const` member function that is thread-safe; on any other type, only
  while no other reference to the object exists. Prefer a `const` C++ method.
- `SharedPtr<T>` is `Send` and `Sync` only when `T` is both. `UniquePtr<T>` is
  `Send` when `T` is `Send`.
- Give an opaque Rust type to C++ as `Box<T>`, never as `UniquePtr<T>`.

## Thread safety

cxx emits no `Send` or `Sync` impl for an opaque C++ type, so a
`UniquePtr` to it cannot move to another thread:

```rust,compile_fail,E0277
#[cxx::bridge]
mod ffi {
    unsafe extern "C++" {
        include!("demo/include/engine.h");
        type Engine;
        fn new_engine() -> UniquePtr<Engine>;
        fn total(&self) -> i32;
    }
}

fn main() {
    let engine = ffi::new_engine();
    let worker = std::thread::spawn(move || engine.total());
    println!("{}", worker.join().unwrap_or(0));
}
```

Add the impl only when the C++ class is safe to use from another thread, and
state the reason. The `rust-send-sync` skill, when it is installed, owns this
proof; else read every C++ member that the bridge calls for unsynchronized
shared state, such as a cache or a lazy field behind a `const` method.

```rust
#[cxx::bridge]
mod ffi {
    unsafe extern "C++" {
        include!("demo/include/engine.h");
        type Engine;
    }
}

// SAFETY: engine::Engine has no thread-affine state, and its methods lock an
// internal std::mutex (see include/engine.h).
unsafe impl Send for ffi::Engine {}
```

## One C++ type in two bridges

Two `type Engine;` declarations in two bridges are two Rust types. Alias the
second to the first, and cxx checks that both name the same C++ type:

```rust
mod core_ffi {
    #[cxx::bridge(namespace = "engine")]
    pub mod ffi {
        unsafe extern "C++" {
            include!("demo/include/engine.h");
            type Engine;
            fn new_engine() -> UniquePtr<Engine>;
        }
    }
}

#[cxx::bridge(namespace = "engine")]
mod report_ffi {
    unsafe extern "C++" {
        include!("demo/include/report.h");
        type Engine = crate::core_ffi::ffi::Engine;
        fn report(engine: &Engine) -> String;
    }
}
```

For a type that `bindgen` generated, write `unsafe impl cxx::ExternType` with
`type Id = cxx::type_id!("ns::Name");` and `type Kind = cxx::kind::Opaque;`.
Use `cxx::kind::Trivial` only when the C++ move constructor and destructor are
trivial, because Rust then moves the value with a byte copy.
