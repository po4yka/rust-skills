# Rust GDB/LLDB Pretty-Printers Reference

Full command reference for debugging Rust with GDB and LLDB. The parent skill
[SKILL.md](../SKILL.md) covers when to reach for a debugger; this file covers
how to drive one.

## GDB Setup

### Automatic via rust-gdb

`rust-gdb` is a wrapper script installed with rustup. It starts GDB and sources
the Rust pretty-printers, so `String`, `Vec`, `Option`, `Result`, and `HashMap`
print in Rust syntax.

```bash
# Find the wrapper
which rust-gdb
# ~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rust-gdb

# Use it against a debug binary
rust-gdb target/debug/my-cli
```

### Manual ~/.gdbinit setup

Use this when you must run plain `gdb`, for example inside an IDE or a container
that does not ship the wrapper.

```python
# ~/.gdbinit
python
import subprocess, sys
import gdb

# Find the rustc sysroot
sysroot = subprocess.check_output(['rustc', '--print', 'sysroot']).decode().strip()
sys.path.insert(0, f'{sysroot}/lib/rustlib/etc')

import gdb_lookup
# The import alone loads no printer. Register them, exactly as the shipped
# gdb_load_rust_pretty_printers.py does.
gdb_lookup.register_printers(gdb.current_objfile())
end

# Enable pretty-printing
set print pretty on
set print array on
```

In `~/.gdbinit` there is no current objfile, so `gdb.current_objfile()` returns
`None` and the printers register globally. That is what you want here.

## GDB Commands for Rust

### Types and values

```gdb
# Print the type of an expression
(gdb) ptype my_var
(gdb) whatis my_var

# Inspect String
(gdb) p my_string
$1 = "hello world"

# Inspect Vec<T>
(gdb) p my_vec
$2 = vec![1, 2, 3, 4, 5]
(gdb) p my_vec.len

# Inspect Option<T>
(gdb) p my_option
$3 = Some(42)

# Inspect Result<T, E>
(gdb) p my_result
$4 = Ok(42)
# or
$4 = Err(DecodeError { .. })

# Inspect HashMap
(gdb) p my_map
$5 = HashMap{...}
```

If a value prints as raw struct fields instead of Rust syntax, the
pretty-printers are not loaded. Restart under `rust-gdb`, or fix `~/.gdbinit`.

### Breakpoints in Rust

```gdb
# Break on a function by full path (crate paths use underscores, not hyphens)
(gdb) break my_crate::module::function_name

# Break on a trait method: quote the whole symbol
(gdb) break '<MyType as MyTrait>::method'

# Break on a closure (closures get mangled names)
(gdb) break my_crate::module::function_name::{closure#0}

# Break on panic
(gdb) break rust_panic
(gdb) break std::panicking::begin_panic

# Break on a file and line
(gdb) break src/lib.rs:171

# Conditional break: stop only on the input that fails
(gdb) break my_crate::decode if bytes.len() > 4096
(gdb) break my_crate::process if id == 100
```

A conditional breakpoint on the argument that triggers the bug is faster than
stepping through thousands of good iterations.

### Thread debugging

```gdb
# List all threads
(gdb) info threads

# Switch to a thread
(gdb) thread 2

# Backtrace every thread: the first command to run on a hang
(gdb) thread apply all bt

# Stop other threads from running while you step
(gdb) set scheduler-locking on
```

## LLDB Setup

### Automatic via rust-lldb

```bash
rust-lldb target/debug/my-cli
```

### Manual setup

```bash
# Find the Rust LLDB scripts
rustc --print sysroot
# ~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu

# Source the scripts inside an LLDB session
(lldb) command script import ~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/etc/lldb_lookup.py
(lldb) command source ~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/etc/lldb_commands
```

Use the manual form inside Xcode and Android Studio, where the IDE starts LLDB
itself and the `rust-lldb` wrapper never runs.

## LLDB Commands for Rust

```lldb
# Set a breakpoint by symbol or by file and line
(lldb) b my_crate::module::function_name
(lldb) b src/lib.rs:171

# Break on panic
(lldb) b rust_panic

# Run with arguments (when the binary was launched without them)
(lldb) run <args>

# Print a variable
(lldb) frame variable my_var
(lldb) p my_vec

# Print a specific field
(lldb) p my_struct.field

# All locals in the current frame
(lldb) frame variable

# Thread list
(lldb) thread list

# Backtrace
(lldb) thread backtrace
(lldb) thread backtrace all
```

## VS Code / IDE Integration

### CodeLLDB extension

CodeLLDB is the practical choice for Rust in VS Code: it ships its own LLDB and
loads the Rust formatters.

`.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "type": "lldb",
            "request": "launch",
            "name": "Debug my-cli",
            "program": "${workspaceFolder}/target/debug/my-cli",
            "args": ["--input", "fixtures/sample.bin", "--output", "/tmp/out.bin"],
            "cwd": "${workspaceFolder}",
            "env": {
                "RUST_BACKTRACE": "1",
                "RUST_LOG": "my_crate=debug,my_other_crate=trace"
            },
            "sourceMap": {
                "/rustc/...": "${env:HOME}/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/src/rust"
            }
        },
        {
            "type": "lldb",
            "request": "launch",
            "name": "cargo test -- my_crate",
            "cargo": {
                "args": ["test", "--no-run", "-p", "my-crate"],
                "filter": { "name": "my_crate", "kind": "lib" }
            },
            "args": ["module_name"],
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

Notes:

- `sourceMap` maps the `/rustc/<hash>/` paths baked into std debug info onto the
  local rust-src component. Without it you cannot step into `std`. Install the
  component with `rustup component add rust-src`.
- The `cargo` block builds the test binary with `--no-run` and then launches the
  produced executable, so you can debug a test without knowing its hashed path.
- `args` in the test configuration is passed to the test harness, so it filters
  which tests run.

## Symbol Demangling

Tombstones, `perf` output, and linker errors show mangled Rust symbols. Demangle
them before you read them.

```bash
# Install rustfilt
cargo install rustfilt

# Demangle a single symbol. v0 is the default shape on rustc 1.97.0.
echo '_RNvCsbhslDugC6KQ_2m211foo_bar_baz' | rustfilt
# m2::foo_bar_baz

# Legacy shape. Older artifacts and pre-v0 toolchains still carry it.
echo '_ZN4core4fmt9Formatter9write_fmt17hb4f5d866d07ffa27E' | rustfilt
# core::fmt::Formatter::write_fmt

# The LLVM c++filt demangles v0 too
echo '_RNvCsbhslDugC6KQ_2m211foo_bar_baz' | c++filt
# m2::foo_bar_baz
```

Grep for `_R`, not `_ZN`. On rustc 1.97.0 v0 is already the default, so a `_ZN` pattern
matches no symbol in a current build and silently returns nothing. Measured on rustc
1.97.0: `-C symbol-mangling-version=v0` changes no symbol, and
`-C symbol-mangling-version=legacy` is rejected with "requires `-Z unstable-options`",
which stable does not accept. Mach-O adds one leading underscore, so `nm` prints
`__RNv...` on macOS.

`rustfilt` also filters a whole file or a stream, so you can pipe a log through
it. `llvm-addr2line -C` and `llvm-symbolizer` demangle on their own; you do not
need `rustfilt` after them.
