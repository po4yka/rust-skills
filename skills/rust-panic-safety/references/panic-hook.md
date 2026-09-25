# Privacy-safe panic hook

Read this file when you install or review a panic hook. It holds the catalog's single copy of
the report block; other skills point here. The rules in the "Report the panic without exposing
its payload" section of `SKILL.md` apply to every line of it.

```rust
#[derive(Clone, Copy)]
enum PanicSite {
    Boundary,
    Engine,
    Unknown,
}

fn classify_site(file: &str) -> PanicSite {
    // Cargo passes a workspace member as `<member-dir>/src/...` and a registry
    // dependency as an absolute path, so match a segment, not a prefix.
    if file.contains("src/boundary/") {
        PanicSite::Boundary
    } else if file.contains("src/engine/") {
        PanicSite::Engine
    } else {
        PanicSite::Unknown
    }
}

pub fn report_panic(info: &std::panic::PanicHookInfo<'_>) {
    let (site, line, column) = info
        .location()
        .map(|location| {
            (
                classify_site(location.file()),
                location.line(),
                location.column(),
            )
        })
        .unwrap_or((PanicSite::Unknown, 0, 0));

    write_platform_panic("rust_panic", site, line, column);
}

// The application-owned outermost Rust FFI bootstrap owns the process-global
// hook and statically composes every component handler once during startup.
pub fn install_bootstrap_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        report_panic(info);
        report_other_library_panics(info);
    }));
}
```

- `write_platform_panic` stands for the platform sink. The `rust-observability` skill covers
  the sink.
- `report_other_library_panics` stands for the redacted handlers that embedded components
  expose. The bootstrap composes them here once.
- The bootstrap can install from its `JNI_OnLoad` or from one explicit init export, after it
  composes the component handlers.
- For a message or a backtrace, use `RUST_BACKTRACE=full` in a local host repro. Symbolicate a
  tombstone or crash report offline against the exact unstripped binary for an app process.
