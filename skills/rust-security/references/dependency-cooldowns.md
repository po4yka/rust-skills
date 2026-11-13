# Dependency cooldowns

Cargo 1.100 can delay selection of a new registry version. Set a team-approved
age in `.cargo/config.toml`; three days is an example, not a security guarantee:

```toml
[registry]
global-min-publish-age = "3 days"
```

Run `cargo update --dry-run` and inspect the versions Cargo holds back before
using the policy. Then review the lockfile diff with the dependency gate in
[SKILL.md](../SKILL.md). A delayed release can still be malicious.

The resolver keeps versions already in `Cargo.lock`. Registry versions without
`pubtime` are not delayed. `cargo install` ignores this setting for the tool and
its dependencies. Pin and review installed tools separately. Older Cargo does
not provide this guarantee; run `cargo --version` in each resolver job.

For a reviewed urgent fix, override the policy for one command:

```bash
CARGO_RESOLVER_INCOMPATIBLE_PUBLISH_AGE=allow cargo update -p <crate> --precise <version>
```

Review the selected source before a build. Record why the exception is needed.
The selected version stays in the lockfile after the override ends.

Source: [Cargo publish age resolution](https://doc.rust-lang.org/1.100.0/cargo/reference/resolver.html#publish-age).
