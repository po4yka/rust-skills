---
name: rust-cli
description: Use when you design, implement, review, or publish a production Rust command-line interface; define clap arguments and compatibility, stdout and stderr contracts, exit codes, configuration precedence, signal handling, atomic output replacement, TTY behavior, Unicode paths, broken-pipe handling, and shell completion packaging. Triggers on "Rust CLI", "clap arguments", "CLI exit codes", "config precedence", "broken pipe", "atomic file replacement", "Ctrl-C", or "shell completions".
license: BSD-3-Clause
---

# Rust CLI

Use this skill for the user-visible contract of a Rust command-line program.
Preserve the parser, configuration format, and runtime that the workspace already
uses. Do not add `clap`, an async runtime, a signal crate, or a temporary-file
crate only to copy an example from this skill.

## Define the contract first

Record these decisions before you change code:

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
surface. Inspect release notes, completion files, man pages, scripts, and tests.
Do not infer the contract only from the parser definition.

## Design one unambiguous argument grammar

Use the parser that the repository already uses. When it uses `clap`, keep one
command definition as the source for parsing, help, and completion generation.
Do not maintain a second list of flags for documentation or completions.

Apply these rules:

- Give every option one canonical long name.
- Add a short name only when it is memorable and does not conflict.
- Reserve `-h` for help and `-V` for version unless the established CLI differs.
- Use a value name that states the domain, such as `PATH`, `FORMAT`, or `SECONDS`.
- Use an enum parser for a closed value set. Reject unknown values.
- Parse numeric ranges during argument validation. Do not defer them to runtime.
- Use a repeatable option only when order or accumulation has defined meaning.
- State whether a repeated scalar uses first-wins, last-wins, or an error.
- Require `--flag=value` only when syntax ambiguity makes it necessary.
- Honor `--` as the end of options before a positional can start with `-`.
- Do not depend on the shell to expand globs, environment variables, or `~`.
- Do not read a password, token, or private key from an ordinary argument.
  Command lines can be visible in process listings and shell history.

Keep positional arguments few and stable. An optional positional before a
required positional is ambiguous. Prefer a named option for the optional value.
Do not overload one positional with unrelated types that require guesswork.

Use `PathBuf` or `OsString` for paths and other operating-system values. Do not
call `to_str().unwrap()` on them. Convert to UTF-8 only at a boundary that
requires text, and return an error that names that boundary. On Unix, path bytes
need not be UTF-8. On Windows, paths use Unicode but can still fail conversion
to a selected output encoding.

Accept `-` as standard input or standard output only when the command documents
that convention. Reject combinations that would make data and diagnostics share
one stream.

## Change arguments compatibly

Classify a change before implementation:

| Change | Default classification |
|---|---|
| Add an optional flag with no effect when absent | Compatible |
| Add a subcommand | Usually compatible; check wrapper scripts |
| Add a value to a closed enum | Usually compatible; check exhaustive consumers |
| Change a default | Behavior breaking |
| Make an optional value required | Breaking |
| Rename or remove a flag, subcommand, or value | Breaking |
| Reinterpret an existing value | Breaking |
| Change stdout fields, ordering, or encoding | Breaking for scripts |
| Change exit status for an existing result | Breaking for scripts |
| Start prompting in a formerly non-interactive path | Breaking and unsafe |

For a supported rename, accept the old spelling for a documented transition.
Hide it from concise help only when users can still find the migration note.
Emit at most one actionable deprecation warning per invocation. Do not emit the
warning to stdout. Remove the alias only in the release allowed by policy.

Do not use prefix matching for subcommands or enum values. A later addition can
make an accepted prefix ambiguous. Do not let unknown flags become positional
values unless pass-through arguments are the explicit contract.

Keep machine-readable version output stable and short. If `--version` follows
the conventional `<name> <version>` form, do not add build prose to that line.
Expose extra build data through a separate command or explicit format.

## Separate stdout from stderr

Write requested data to stdout. Write diagnostics, warnings, progress, and
interactive prompts to stderr. A successful command that writes a file can
leave stdout empty unless the contract defines a result record.

Do not use `println!` for fallible streaming output. It panics when the write
fails. Lock stdout, propagate write errors, and treat `BrokenPipe` as successful
early consumer termination when stdout is the only incomplete destination.

```rust
use std::io::{self, Write};

fn write_rows(rows: impl IntoIterator<Item = String>) -> io::Result<()> {
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for row in rows {
        writeln!(out, "{row}")?;
    }
    Ok(())
}

fn main() -> io::Result<()> {
    match write_rows(["one".to_owned(), "two".to_owned()]) {
        Err(error) if error.kind() == io::ErrorKind::BrokenPipe => Ok(()),
        result => result,
    }
}
```

Do not translate every broken pipe to success. A broken pipe on an upload,
socket, log sink, or required output file is an operation failure. On Unix, do
not globally restore the default `SIGPIPE` disposition without reviewing all
writes in the process. On Windows, handle the corresponding I/O error instead
of assuming a POSIX signal.

Define each machine format exactly:

- State whether JSON output is one document or one JSON value per line.
- End text records with a newline unless the format forbids it.
- Keep stdout free of banners, progress bars, update notices, and log records.
- Keep field names and types stable. Add fields only when consumers permit them.
- Define ordering or say that order is unspecified.
- Escape data with the format encoder. Do not build JSON or CSV with formatting.
- Define how non-UTF-8 path values appear in a Unicode-only format. Prefer an
  explicit error or a documented lossless platform representation over silent
  replacement characters.

Let `--quiet` suppress informational stderr output. It must not suppress an
error that explains a nonzero exit. Let `--verbose` change diagnostic detail,
not stdout data. Redact secrets from both streams and from debug error chains.

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

Map parser errors before application work starts. With `clap`, preserve its
successful help and version exits and its usage-error status unless the CLI has
a documented older contract. Do not catch a parser exit and turn every result
into status `1`.

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

## Handle terminals without changing data semantics

Detect each stream separately with `std::io::IsTerminal` or the existing
terminal library. Stdin can be a terminal while stdout is redirected. Use TTY
state only for presentation and interaction. Do not change selected records,
field types, or exit meaning because a stream is a terminal.

Use these defaults:

| Feature | Terminal | Non-terminal |
|---|---|---|
| Color | Auto when supported | Off |
| Progress | On stderr when useful | Off, or explicit stable log records |
| Pager | Only by explicit policy | Off |
| Prompt | Allowed when input and the prompt stream are terminals | Fail with an actionable flag |
| Table decoration | Human-readable | Keep the selected output format stable |

Support `--color=auto|always|never` when color is part of the product. Honor
`NO_COLOR` in auto mode when project policy adopts that convention. An explicit
CLI value wins over environment and config. Never emit control sequences to a
redirected stream in auto mode.

Never prompt in CI, a pipe, a service, or when stdin or the prompt stream is
redirected. A prompt written to stderr is not visible when stderr goes to a
log. If the product opens the controlling terminal directly, make that a
separate explicit path and test it. Require an explicit confirmation flag for
destructive non-interactive work. A `--yes` flag does not grant authority that
the caller does not have.

## Terminate gracefully

Treat Ctrl-C as a cancellation request, not as permission to abandon a write at
an arbitrary instruction. Install signal handling before long-running work.
Use the runtime or signal library already present.

On Unix, consider `SIGINT` and `SIGTERM`. Review `SIGHUP` separately because a
daemon and an interactive CLI can assign it different meaning. On Windows,
handle the console Ctrl-C event through the selected cross-platform facility.
Do not assume that every Unix signal exists on Windows.

Use this sequence:

1. The first termination request stops admission of new work.
2. Notify owned tasks through the existing cancellation mechanism.
3. Stop progress rendering and keep stderr available for the final diagnostic.
4. Let the current atomic output either complete or discard its temporary file.
5. Drain owned work for one finite grace period.
6. Return the documented cancellation status if shutdown completes.
7. On a second interrupt or grace expiry, use the product's forced-exit policy.

A signal callback must do the minimum work allowed by its API. Do not allocate,
lock arbitrary application mutexes, or write complex diagnostics from a raw
Unix signal handler. Prefer a safe runtime notification facility.

Do not claim cleanup for `SIGKILL`, power loss, process abort, or forced Windows
termination. Atomic namespace replacement protects readers from a partially
written destination. It does not prove post-crash durability. State which file
and directory sync operations the supported filesystem needs, and test the
failure states that the platform can reproduce.

## Replace output safely

Do not truncate the destination before computation succeeds. For a regular-file
output, use this transaction:

1. Resolve the destination and validate the overwrite and symlink policy.
2. Create a new unpredictable temporary file in the destination directory with
   exclusive creation and the restrictive mode or security descriptor in the
   same open operation. Do not create it broadly and restrict it later.
3. Apply any additional metadata before sensitive data is written.
4. Stream all bytes to the temporary file and handle every write error.
5. Flush userspace buffers. Call file sync when the contract requires durability.
6. Close handles that prevent replacement on the target platform.
7. Commit with one platform-supported atomic no-replace or replace operation
   that matches the overwrite policy.
8. Sync the parent directory on Unix when rename durability is required.
9. Remove a leftover temporary file on ordinary failure when safe.

The temporary file must use the same filesystem as the destination. A rename
across filesystems is not atomic. Do not implement overwrite as remove-then-
rename. A crash between those calls loses the old output.

When overwrite is not authorized, the commit operation must fail atomically if
the destination exists. A separate existence check followed by ordinary rename
has a race and can overwrite a file created between the two calls. Use the
workspace's verified no-replace primitive for the supported platform, or report
that atomic no-clobber output is unavailable. Add a concurrent creator test.

On Unix, a replace-capable rename can atomically replace a destination entry.
Decide whether replacing a symlink entry is acceptable; do not accidentally
follow it and overwrite its target. On Windows, select one named replacement
primitive for the supported Windows and filesystem matrix. Verify its existing-
destination and documented failure states; do not infer them from a Unix rename
or from another Windows API. If no verified atomic replacement is available,
fail before deleting the old file and document that atomic overwrite is
unsupported. Keep atomic visibility and post-crash durability as separate
claims on every platform.

Define whether replacement preserves destination permissions, owner, ACLs,
extended attributes, streams, and timestamps. The result depends on the
platform and selected primitive. A Unix rename normally exposes the source
inode's metadata. A Windows replacement primitive can preserve or merge
destination metadata. Before commit, prove that the selected primitive
establishes the required final metadata and ACL. For sensitive output, it must
do so without a visibility window. If the ACL needs repair after publication,
fail before commit. Use a post-commit check only as defense in depth. Copy only
metadata required by the product. Do not inherit unsafe permissions from an
attacker-controlled file.

For `--force`, replace only the exact file type that the command documents.
Reject a directory. Treat a symbolic link, junction, or reparse point according
to an explicit policy. Encode the overwrite decision in the atomic commit
primitive when the directory is not trusted; a recheck alone does not close the
race. Never claim a multi-file update is atomic because each file rename is
atomic; use a manifest or generation directory when readers need one snapshot.

## Generate and package completions

Generate shell completions from the exact command definition for the released
binary version. Do not hand-maintain option lists. If completion support needs
an optional parser companion crate, match its version to the parser and keep it
in the existing build or release feature policy.

Provide a deterministic command such as:

```bash
tool completions bash > tool.bash
tool completions zsh > _tool
tool completions fish > tool.fish
tool completions powershell > tool.ps1
```

The command writes only the script to stdout. It writes no color, progress, or
banner. Reject an unsupported shell with the usage-error status.

Package files in the locations required by the target package manager. Common
system locations include `share/bash-completion/completions/<tool>`,
`share/zsh/site-functions/_<tool>`, and
`share/fish/vendor_completions.d/<tool>.fish`. Treat them as package-relative
paths, not universal installation paths. For PowerShell, follow the target
installer or module policy instead of editing a user's profile during install.

Regenerate completions in the release job after the final binary metadata is
fixed. Compare generated files with tracked package assets when the repository
tracks them. Test that every supported shell parses or loads its script in a
clean environment. Run the applicable syntax checks on a host that has each
supported shell:

```bash
bash -n tool.bash
zsh -n _tool
fish -n tool.fish
pwsh -NoProfile -Command '$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("tool.ps1", [ref]$null, [ref]$e) > $null; if ($e) { exit 1 }'
```

Also load each file in a clean shell and request a completion. A syntax check
does not prove that the generated function is registered. Do not make
completion generation execute network requests, read secrets, or inspect user
configuration.

## Test the process boundary

Test through the built executable. Use the repository's existing process-test
helper, or `std::process::Command` when no helper exists. Cover these observable
contracts:

- valid invocation, invalid invocation, help, and version statuses;
- exact stdout data and the absence of diagnostics on stdout;
- useful stderr and the documented operational status on failure;
- a consumer that closes stdout early, such as `tool list | head -n 1` on Unix;
- stdin, stdout, and stderr redirected independently;
- non-UTF-8 Unix path arguments when the command accepts paths;
- every configuration source alone and the complete precedence chain;
- an invalid explicit config file and invalid environment value;
- Ctrl-C during idle work and during output replacement;
- an injected write or sync failure that preserves the old destination;
- refusal to overwrite without the explicit overwrite option;
- terminal auto behavior with both terminal and pipe-backed streams;
- generated completion files for every supported shell.

Use a pseudo-terminal test only for behavior that depends on terminal state.
Do not mark a test interactive and then skip it in CI. Keep machine-format
goldens small and review changes as compatibility changes.

Run the workspace's normal gates. Also run the executable under the operating
systems whose signal, path, and replacement behavior differ. A Unix-only test
does not prove Windows replacement or console-event behavior.

## Triage failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `tool | head` prints a panic | `println!` hides `BrokenPipe` | Propagate writes and map stdout `BrokenPipe` to success |
| JSON parser sees a banner | Diagnostics use stdout | Move all non-data output to stderr |
| Redirected output contains escape codes | TTY state is not checked per stream | Use auto color from the destination stream |
| CI waits forever | A prompt runs with non-terminal stdin | Fail and require an explicit flag |
| CLI flag does not override config | Sources merge in subsystem order | Merge typed partials once in documented precedence |
| `--no-*` cannot undo config | Boolean absence and false collapse | Preserve explicit boolean provenance |
| Old output disappears on failure | Destination is truncated or removed first | Write beside it and replace only after success |
| Windows overwrite fails | Unix rename semantics are assumed | Use the selected Windows atomic replace facility |
| Ctrl-C leaves a truncated file | Signal exits inside the write | Cancel work and discard the temporary file |
| Completion omits a new flag | A second command model generated it | Generate from the parser's command definition |
| A valid path is rejected on Unix | Path is forced through UTF-8 | Keep it as `OsStr` or `Path` until a text boundary |
| Scripts break after a default changes | Default behavior was not treated as API | Restore it or release the documented breaking change |

## Handoff

Report:

- the argument and output compatibility classification;
- the exact stdout, stderr, and exit-code contracts;
- the effective configuration precedence and path base;
- the interrupt, grace-period, and partial-output behavior;
- the Unix and Windows overwrite implementations and metadata policy;
- terminal behavior for each stream;
- the generated completion shells and package paths;
- process-boundary tests run on each supported operating system;
- any unverified shell, platform, packaging, or crash-durability behavior.
