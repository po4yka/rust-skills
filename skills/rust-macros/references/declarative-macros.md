# Declarative macro details

Contents:

- [Scope a macro by path](#scope-a-macro-by-path)
- [A caller's alias shadows a bare standard-library name](#a-callers-alias-shadows-a-bare-standard-library-name)
- [Hygiene examples](#hygiene-examples)
- [Follow sets](#follow-sets)
- [Build a format string](#build-a-format-string)

Every quoted message comes from rustc 1.98.1, edition 2024.

## Scope a macro by path

`pub(crate) use` after the definition makes the macro an ordinary crate-private item, reachable
by path from any module:

```rust
mod math {
    macro_rules! twice {
        ($v:expr) => {
            $v * 2
        };
    }
    pub(crate) use twice;
}

fn main() {
    println!("{}", math::twice!(21));
}
```

## A caller's alias shadows a bare standard-library name

A macro expands in the caller's module, so a bare `Result` in the macro body resolves to the
caller's `type Result<T> = ...` alias:

```rust,compile_fail,E0107
macro_rules! parse_fn {
    ($name:ident) => {
        pub fn $name(s: &str) -> Result<i32, String> {
            s.parse().map_err(|_| s.to_owned())
        }
    };
}

mod caller {
    type Result<T> = core::result::Result<T, std::io::Error>;
    parse_fn!(parse);
}

fn main() {}
```

The error is `type alias takes 1 generic argument but 2 generic arguments were supplied`.
`::core::result::Result<i32, ::std::string::String>` in the macro body fixes it for a caller that
links `std`.

## Hygiene examples

A generated local is invisible outside the expansion. rustc adds `help: an identifier with the
same name is defined here, but is not accessible due to macro hygiene`:

```rust,compile_fail,E0425
macro_rules! decl {
    () => {
        let tmp = 7;
    };
}

fn main() {
    decl!();
    println!("{tmp}");
}
```

A generated item is visible, so a fixed item name collides on the second invocation with
``error[E0428]: the name `Inner` is defined multiple times``:

```rust,compile_fail,E0428
macro_rules! mk_tag {
    ($n:ident) => {
        struct $n;
        struct Inner;
    };
}

mk_tag!(Alpha);
mk_tag!(Beta);

fn main() {}
```

The anonymous `const _: () = { ... };` fix. Each expansion of the block gets its own item
namespace, and an `impl` inside it still applies to the outer type:

```rust
macro_rules! mk_tag {
    ($n:ident) => {
        pub struct $n;

        const _: () = {
            struct Guard;
            impl $n {
                pub fn tag() -> &'static str {
                    let _g = Guard;
                    stringify!($n)
                }
            }
        };
    };
}

mk_tag!(Alpha);
mk_tag!(Beta);

fn main() {
    println!("{} {}", Alpha::tag(), Beta::tag());
}
```

## Follow sets

rustc checks these rules when it reads the `macro_rules!` item. The rules are in the
[Reference](https://doc.rust-lang.org/reference/macros-by-example.html#follow-set-ambiguity-restrictions):

| Fragment | Tokens allowed after it |
| --- | --- |
| `expr`, `stmt` | `=>`, `,`, `;` |
| `pat` | `=>`, `,`, `=`, `if`, `in` |
| `pat_param` | The `pat` set, plus `\|` |
| `ty`, `path` | `{`, `[`, `=>`, `,`, `>`, `>>`, `=`, `:`, `;`, `\|`, `as`, `where`, a `$b:block` metavariable |
| `vis` | `,`, an identifier other than `priv`, any token that starts a type, an `ident`, `ty`, or `path` metavariable |
| `ident`, `lifetime`, `literal`, `block`, `meta`, `tt`, `item` | No restriction |

```text
error: `$e:expr` is followed by `$s:stmt`, which is not allowed for `expr` fragments
  = note: allowed there are: `=>`, `,` or `;`
```

The note for `ty` and `path` omits `>>` and a `$b:block` metavariable. Both compile.

`pat` matches a top-level or-pattern since edition 2021, which is why `|` cannot follow it. Use
`pat_param` when `|` must be your separator.

## Build a format string

A format string must be a literal token. A variable or a runtime `String` fails with
`error: format argument must be a string literal`.

Three routes work. Forward the caller's literal with `$fmt:literal` (or `$fmt:tt`). Prefix it
with `concat!("prefix", $fmt)`. Build one from identifiers with `concat!` over `stringify!`.

```rust,run
macro_rules! log {
    ($fmt:literal $(, $arg:expr)* $(,)?) => {
        println!(concat!("[app] ", $fmt) $(, $arg)*)
    };
}

macro_rules! dump {
    ($($v:ident),* $(,)?) => {
        println!(concat!($(stringify!($v), "={:?} "),*), $($v),*)
    };
}

fn main() {
    let count = 7;
    let name = "x";
    log!("count is {}", count);
    dump!(count, name);
}
```

A format string that comes from `concat!` cannot capture variables inline. `log!("{count}")`
fails with ``error: there is no argument named `count` ``, and the note says `format_args!`
cannot capture variables when the format string is expanded from a macro. Pass the arguments
explicitly, or forward `$fmt` to `println!` unchanged when you need inline capture.
