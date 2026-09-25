---
name: rust-cli
description: Use when designing, changing, or reviewing the user-visible contract of a Rust CLI, such as clap arguments and their compatibility, stdout and stderr separation, CLI exit codes, config precedence, TTY and color behavior, Ctrl-C and SIGTERM handling, broken pipe errors, atomic file replacement, non-UTF-8 path arguments, and packaged shell completions. Not for server graceful shutdown; use `rust-networking`.
license: BSD-3-Clause
---

# Rust CLI

Preserve the parser, configuration format, and runtime that the workspace already
uses. Do not add `clap`, an async runtime, a signal crate, or a temporary-file
crate only to copy an example from this skill.

## Define the contract

Decide each surface that the change touches before you change code. A new
command needs every row.

| Surface | Required decision |
|---|---|
| Arguments | Grammar, defaults, conflicts, required values, and `--` behavior |
| Compatibility | Which names, values, output fields, and exit codes scripts can depend on |
| Standard output | Data format, ordering, encoding, and broken-pipe result |
| Standard error | Diagnostics, warnings, progress, and quiet behavior |
| Configuration | Sources, precedence, merge rules, and path base |
| Termination | Interrupt behavior, drain deadline, and partial-output policy |
| File output | Overwrite policy, atomicity, durability, and metadata policy |
| Terminal mode | Color, progress, prompts, paging, and non-terminal fallback |
| Completions | Supported shells, generation point, and package destinations |

Treat documented behavior and behavior used by automation as compatibility
surface. When the change touches an existing name, value, output, or exit
status, inspect release notes, completion files, man pages, scripts, and tests.
Do not infer the contract only from the parser definition.

A changed default, a newly required value, a renamed, removed, or reinterpreted
name or value, a changed stdout format, and a changed exit status break
scripts. Read [`references/compatibility.md`](references/compatibility.md) when
you add or change a flag, subcommand, positional, value, default, version line,
exit status, or machine-readable format. It holds the remaining grammar rules,
the change classification, the deprecation procedure, and the format rules.

## Triage failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `tool \| head` prints a panic | `println!` hides `BrokenPipe` | Propagate writes and map stdout `BrokenPipe` to success |
| Last rows missing, status 0 | The drop-time flush failed and `BufWriter` ignored the error, or `process::exit` skipped the drop | Call `flush()` and return `ExitCode` from `main` |
| Error prints as `Error: Os { code: 2, kind: NotFound, message: "No such file or directory" }` with status 1 | `main` returns `Result` and std prints `Debug` | Print a `Display` diagnostic and return `ExitCode` |
| JSON parser sees a banner | Diagnostics use stdout | Move all non-data output to stderr |
| Redirected output contains escape codes | TTY state is not checked per stream | Use auto color from the destination stream |
| CI waits forever | A prompt runs with non-terminal stdin | Fail and require an explicit flag |
| CLI flag does not override config | Sources merge in subsystem order | Merge typed partials once in documented precedence |
| `--no-*` cannot undo config | Boolean absence and false collapse | Preserve explicit boolean provenance |
| Old output disappears on failure | Destination is truncated or removed first | Write beside it and replace only after success |
| Windows overwrite fails | Unix rename semantics are assumed | Use the selected Windows atomic replace facility |
| Ctrl-C leaves a truncated file | Signal exits inside the write | Cancel work and discard the temporary file |
| Completion omits a new flag | A second command model generated it | Generate from the parser's command definition |
| A valid path is rejected | Path is forced through UTF-8 | Keep it as `OsStr` or `Path` until a text boundary |
| Scripts break after a default changes | Default behavior was not treated as API | Restore it or release the documented breaking change |

## Verify at the process boundary

Test through the built executable. In an integration test, take its path from
`env!("CARGO_BIN_EXE_<name>")` and run it with the repository's process-test
helper or `std::process::Command`. A hand-built `target/debug` path breaks under
`--target`, `CARGO_TARGET_DIR`, or another profile.

With `clap`, add one test that calls `debug_assert()` on the command, such as
`#[test] fn verify_cli() { Cli::command().debug_assert(); }` with
`clap::CommandFactory` in scope. clap reports a definition error, such as a
duplicate short flag, as a debug assertion only on a path that reaches it. Put
this test in the crate that defines `Cli`, such as the binary's
`#[cfg(test)] mod tests`, because an integration test cannot import a binary
crate's items. clap compiles these asserts only with `debug_assertions`, so the
test proves nothing under `cargo test --release`.

Cover each contract surface that the change touches with a process test. A new
command covers every surface. Read
[`references/process-tests.md`](references/process-tests.md) when you write or
review these tests. It holds the coverage checklist, the broken-pipe and
non-UTF-8 path cases, and the rules for terminal tests and goldens.

Run the process tests with `cargo test --locked -p <crate> --test <cli_test>`
while you iterate, and the workspace gate once before merge. Run them on each
operating system whose signal, path, and replacement behavior differs. A
Unix-only green run does not prove Windows replacement or console-event
behavior.

Report the decision for each contract surface that the change touched, the
process-boundary tests run on each operating system, and any unverified shell,
platform, packaging, or crash-durability behavior.

## Separate stdout from stderr

Write requested data to stdout. Write diagnostics, warnings, progress, banners,
update notices, log records, and interactive prompts to stderr. A successful
command that writes a file can leave stdout empty unless the contract defines a
result record.

Do not use `println!` for fallible streaming output. It panics when the write
fails. Lock stdout, propagate write errors, and treat `BrokenPipe` as successful
early consumer termination when stdout is the only incomplete destination. A
Rust binary starts with `SIGPIPE` ignored on Unix, so a write to a closed pipe
returns `ErrorKind::BrokenPipe` and does not kill the process. Call `flush()` on
a `BufWriter` before it drops. Drop ignores a flush error, so the last buffered
rows can disappear while the command exits with status 0.

```rust,run
use std::io::{self, BufWriter, Write};
use std::process::ExitCode;

fn write_rows(out: impl Write, rows: &[&str]) -> io::Result<()> {
    let mut out = BufWriter::new(out);
    for row in rows {
        writeln!(out, "{row}")?;
    }
    out.flush()
}

fn exit_status(result: io::Result<()>) -> ExitCode {
    match result {
        Ok(()) => ExitCode::SUCCESS,
        // The consumer closed stdout early, as in `tool list | head -n 1`.
        Err(error) if error.kind() == io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("tool: cannot write output: {error}");
            ExitCode::FAILURE
        }
    }
}

fn main() -> ExitCode {
    // Probe: the row fits in the buffer, so only flush() reaches the closed pipe.
    let (reader, writer) = io::pipe().expect("create pipe");
    drop(reader);
    let error = write_rows(writer, &["one"]).expect_err("the pipe is closed");
    assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);

    exit_status(write_rows(io::stdout().lock(), &["one", "two"]))
}
```

Do not translate every broken pipe to success. A broken pipe on an upload,
socket, log sink, or required output file is an operation failure. On Unix, do
not globally restore the default `SIGPIPE` disposition without reviewing all
writes in the process. A Rust library loaded by a non-Rust host does not get the
ignored `SIGPIPE`; use the `rust-debugging` skill, when it is installed, for that
case. On Windows, handle the corresponding I/O error instead of assuming a POSIX
signal.

Escape machine output with the format encoder. Do not build JSON or CSV with
string formatting. Define how non-UTF-8 path values appear in a Unicode-only
format. Prefer an explicit error or a documented lossless platform
representation over silent replacement characters.
Read [`references/compatibility.md`](references/compatibility.md) when you define
or change a machine-readable output format.

Let `--quiet` suppress informational stderr output. It must not suppress an
error that explains a nonzero exit. Let `--verbose` change diagnostic detail,
not stdout data. Redact secrets from both streams and from debug error chains.

## Replace output safely

Do not truncate the destination before computation succeeds. Write a new
temporary file in the destination directory, then commit it with one atomic
operation. Create the temporary file with `OpenOptions::create_new(true)` under
an unpredictable name. On Unix, set the mode that the metadata policy requires,
such as `OpenOptionsExt::mode(0o600)` for sensitive output, in the same open
call. Never use `File::create` on a predictable temporary name: it follows a
planted symbolic link and truncates its target. A rename across filesystems is
not atomic. Do not implement overwrite as remove-then-rename, because a crash
between the calls loses the old output.

`std::fs::rename` replaces an existing destination, so it is never a
no-clobber commit. An existence check followed by `rename` races with a
concurrent creator. Keep atomic visibility and post-crash durability as
separate claims on every platform.

Read [`references/atomic-output.md`](references/atomic-output.md) when the
command writes, replaces, or refuses to overwrite a file. It holds the commit
transaction, the std primitives for exclusive creation and no-clobber commit,
the Windows replacement rules, the metadata and `--force` policies, and a
behavior probe.

## Keep exit codes small and stable

Use a documented, portable set unless an established CLI already has one:

| Status | Meaning |
|---|---|
| `0` | Requested operation completed, or a stdout pipe closed normally |
| `1` | Operational failure |
| `2` | Invalid invocation or configuration |
| `130` | Graceful termination after an interactive Ctrl-C, when documented |

Use other codes only when automation needs to distinguish a result. Keep
portable application codes in `0..=125`. Shells commonly reserve `126`, `127`,
and `128 + signal`; Windows does not give those values the same process model.
Do not expose raw `errno`, an HTTP status, or an operating-system error code as
the process exit code.

Return `std::process::ExitCode` from `main`, such as `ExitCode::from(2)`. Do not
call `std::process::exit` while a `BufWriter`, temporary-file guard, or lock
guard is alive. It runs no destructors, so buffered output and cleanup are lost.
Do not return `Result<(), E>` from `main` for a user-facing error. std then
prints the `Debug` form, such as
`Error: Custom { kind: NotFound, error: "config.toml missing" }`, and exits
with status 1.

Map parser errors before application work starts. With `clap`, `Error::exit()`
prints help and version to stdout with status 0 and a usage error to stderr with
status 2, then calls `std::process::exit`. `Cli::parse()` calls `Error::exit()`,
so parse before you create a buffer or guard. For a clap error raised after work
starts, call `let _ = err.print();` and return
`ExitCode::from(u8::try_from(err.exit_code()).unwrap_or(2))`. `ExitCode` has no
`From<i32>`, and `exit_code()` returns `i32`. Preserve these statuses unless the
CLI has a documented older contract. Do not catch a parser error and
turn every result into status `1`.

Print one primary diagnostic for a failure. Include the failed object and the
next useful action. Put detailed causes behind verbose mode when they can expose
paths or internals. Do not print a Rust backtrace by default.

## Merge configuration with provenance

Define one precedence order and use it for every setting. A common order is:

```text
built-in default < system config < user config < project config < environment < CLI
```

Use the order required by the product. Do not add every source automatically.
Merge typed partial values, not serialized documents. Preserve the difference
between absent, explicit `false`, explicit zero, and an empty list.

For each setting, define whether a higher source replaces or extends a list.
Replacement is the safe default. If lists extend, define the order and a way to
clear inherited values.

Apply these rules:

- Treat an explicit `--config PATH` that does not exist as an error.
- Ignore a missing auto-discovered optional file.
- Report a present file that cannot be read or parsed.
- Resolve relative paths inside a config file from that file's directory unless
  the documented format says they use the process working directory.
- Parse environment values with the same range and enum validation as CLI values.
- Report an invalid present environment value. Do not silently use a default.
- Provide explicit negative flags such as `--no-color` when a boolean can come
  from lower-precedence sources.
- Record source provenance internally so diagnostics can name the winning value.
- Do not print secret values in effective-configuration output.

Read configuration before starting irreversible work. Validate the complete
effective configuration once. Do not let separate subsystems reinterpret the
same variable with different defaults.

Treat an auto-discovered project configuration as untrusted until the user
trusts that project or selects the file explicitly. It must not replace a
credential source, credential helper, authenticated endpoint, proxy, or TLS
trust policy inherited from user configuration. Bind credentials to the
origin they authenticate. Do not send them after a project setting changes the
endpoint. Keep security-sensitive precedence separate when ordinary setting
precedence would cross this trust boundary.

## Design one unambiguous argument grammar

Keep one command definition as the source for parsing, help, and completion
generation. Do not maintain a second list of flags for documentation or
completions.

Apply these rules:

- Validate numeric ranges in the parser, such as
  `clap::value_parser!(u16).range(1..)`. Do not defer them to runtime.
- State whether a repeated scalar uses first-wins, last-wins, or an error.
  clap 4 rejects a second `ArgAction::Set` occurrence unless
  `Command::args_override_self(true)`, or `Arg::overrides_with` that names the
  argument's own id, makes it last-wins.
- Do not use prefix matching for subcommands or enum values. A later addition
  can make an accepted prefix ambiguous. With `clap`, keep
  `Command::infer_subcommands` and `Command::infer_long_args` off, which is the
  default.
- Do not let unknown flags become positional values unless pass-through
  arguments are the explicit contract.
- Do not depend on the shell to expand globs, environment variables, or `~`.
  `cmd.exe` and PowerShell pass a glob to the program unexpanded.
- Do not read a password, token, or private key from an ordinary argument.
  Command lines can be visible in process listings and shell history.

Use `PathBuf` or `OsString` for paths and other operating-system values. Do not
call `to_str().unwrap()` on them. Convert to UTF-8 only at a boundary that
requires text, and return an error that names that boundary. On Unix, path bytes
need not be UTF-8. On Windows, a path is a sequence of 16-bit units that can
hold an unpaired surrogate, so `to_str()` can return `None` there too.

Read [`references/compatibility.md`](references/compatibility.md) when you add
or change a flag, subcommand, positional, or value. It holds the remaining
grammar rules.

## Handle terminals without changing data semantics

Detect each stream separately with `std::io::IsTerminal` (Rust 1.70) or the
existing terminal library. Do not add `atty`: it is unmaintained
(RUSTSEC-2024-0375) and unsound on Windows (RUSTSEC-2021-0145). Stdin can be a
terminal while stdout is redirected. Use TTY state only for presentation and
interaction. Do not change selected records, field types, or exit meaning
because a stream is a terminal. Emit no control sequences to a redirected
stream unless the user forces color with `--color=always` or `CLICOLOR_FORCE`.

Never prompt in CI, a pipe, a service, or when stdin or the prompt stream is
redirected; fail with an actionable flag instead. A prompt written to stderr is
not visible when stderr goes to a log. Require an explicit confirmation flag for
destructive non-interactive work. A `--yes` flag does not grant authority that
the caller does not have.

Read [`references/terminal.md`](references/terminal.md) when you add or change
color, progress output, paging, prompts, or `NO_COLOR` handling. It holds the
terminal and non-terminal defaults and the color precedence rules.

## Terminate gracefully

Treat Ctrl-C as a cancellation request, not as permission to abandon a write at
an arbitrary instruction. Install signal handling before long-running work.
Use the runtime or signal library already present.

A signal callback must do the minimum work allowed by its API. Do not allocate,
lock arbitrary application mutexes, or write complex diagnostics from a raw
Unix signal handler. Prefer a safe runtime notification facility.

Do not claim cleanup for `SIGKILL`, power loss, process abort, or forced Windows
termination. Atomic namespace replacement protects readers from a partially
written destination. It does not prove post-crash durability.

Read [`references/signals.md`](references/signals.md) when you implement or
change Ctrl-C, `SIGTERM`, or `SIGHUP` handling. It holds the per-platform
signal set, the shutdown sequence, and the durability test rule.

## Generate completions from the parser

Generate shell completions from the exact command definition for the released
binary version. With `clap`, keep
`clap_complete` on the same major version as `clap` and generate static scripts
with `clap_complete::aot::generate` or `clap_complete::aot::generate_to`. Do not
make completion generation execute network requests, read secrets, or inspect
user configuration.

Read [`references/completions.md`](references/completions.md) when you add a
completions command, package completions, add a shell, or change the release
job. It holds the command shape, the `CompleteEnv` rule, package paths, and the
per-shell syntax and load checks.
