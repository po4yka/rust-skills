# tokio-console setup

Deep material for `rust-debugging`, section 5. Read it before you add `tokio-console` to a local
debug build. Never ship it: it opens a local TCP port.

1. Add `console-subscriber` to the binary crate, enable `features = ["full", "tracing"]` on
   `tokio`, and call `console_subscriber::init()` first in `main`. `init()` installs the global
   subscriber with its own `fmt` layer, and it panics when a subscriber is already set. Remove
   the `fmt()...init()` call of SKILL.md section 1, or keep your subscriber and add
   `console_subscriber::spawn()` to a `tracing_subscriber::registry()` as a layer.
2. Add the cfg to the rustflags in `.cargo/config.toml`, not to `RUSTFLAGS`, which replaces
   every config-file rustflag. Add it to the rustflags table that the workspace already uses,
   because a matching `[target.<triple>]` table replaces `[build]` rustflags.

Remove all four changes, the rustflags entry included, before you commit. A committed
`tokio_unstable` flag reaches every CI and release build.

```toml
# .cargo/config.toml
[build]
rustflags = ["--cfg", "tokio_unstable"]
```

```bash
cargo install --locked tokio-console
cargo run --locked -p my-cli -- <args>
tokio-console        # in a second terminal
```
