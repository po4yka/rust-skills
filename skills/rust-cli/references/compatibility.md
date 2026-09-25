# Argument grammar, compatibility, and machine formats

Read this when you add or change a flag, subcommand, positional, value, default,
version line, exit status, or machine-readable output format.

## Grammar rules

- Give every option one canonical long name.
- Reserve `-h` for help and `-V` for version unless the established CLI differs.
- Use an enum parser for a closed value set, such as `clap::ValueEnum`. Reject
  unknown values.
- Use a repeatable option only when order or accumulation has defined meaning.
- Require `--flag=value` only when syntax ambiguity makes it necessary.
- Honor `--` as the end of options before a positional can start with `-`.

Keep positional arguments few and stable. An optional positional before a
required positional is ambiguous. Prefer a named option for the optional value.
Do not overload one positional with unrelated types that require guesswork.

Accept `-` as standard input or standard output only when the command documents
that convention. Reject combinations that would make data and diagnostics share
one stream.

## Classify a change

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

Keep machine-readable version output stable and short. If `--version` follows
the conventional `<name> <version>` form, do not add build prose to that line.
Expose extra build data through a separate command or explicit format.

## Machine-readable formats

Define each machine format exactly:

- State whether JSON output is one document or one JSON value per line.
- End text records with a newline unless the format forbids it.
- Add fields only when consumers permit them.
- Define ordering or say that order is unspecified.
