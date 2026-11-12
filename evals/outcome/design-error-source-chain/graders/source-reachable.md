---
type: llm
focus: {source: file, path: src/lib.rs}
---

PASS if `ConfigError` exposes the `io::Error` of the `Read` variant through `Error::source` (a hand-written `source()` that returns it, or `#[source]`/`#[from]` if the agent added `thiserror`), and the `Display` text of `Read` no longer repeats that cause, so a chain printer shows it once. The public variants and their fields stay.
FAIL if `source()` still returns `None` for a read failure, if the cause is reachable only by matching on the enum, if the `Display` text still embeds the io error message, or if the error was flattened into a `String`.
