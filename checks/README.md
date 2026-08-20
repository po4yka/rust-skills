# checks — compile-verify the examples in the skills

The catalog ships no Rust crate, so nothing in it is exercised by a build. This
harness closes that gap for the part that matters most: the code an agent is
told to copy. It reads every ` ```rust ` block in `../skills/**/*.md`, does what
the fence tag says, and fails CI on any result the tag did not promise.

There is no heuristic skip. A block is checked, is proved to fail, or carries
`ignore` on its fence, and the counts are printed on every run.

Adapted from the harness in [leonardomso/rust-skills](https://github.com/leonardomso/rust-skills) (MIT).

It is a development tool. It is not part of any skill, and `npx skills add`
never sees it.

## Run

```bash
bash checks/check.sh
```

That is the whole contract, and it is exactly what CI runs. The steps, if you
need one of them alone:

```bash
python3 scripts/validate-skills.py            # catalog structure; no toolchain needed
python3 scripts/test_validate_skills.py       # the frontmatter rules themselves
python3 checks/test_analyze.py                # the failure classifier itself
python3 checks/gen.py                         # blocks -> checks/examples/
cd checks
cargo check --locked --examples --keep-going --message-format=json > check.json
python3 analyze.py check.json                 # coverage plus suspect detail
python3 analyze.py check.json --check-baseline baseline.txt   # the CI gate
```

`--locked` is not optional. `cargo-workflows` requires it of every CI and agent
invocation, and a harness that updates the lock file while it runs is checking
a dependency set nobody committed.

## What the fence decides

The fence tag is the only thing that decides what happens to a block, and every
tag is enforced:

| Fence | Meaning |
| --- | --- |
| ` ```rust ` | Extracted and type-checked. It must compile, or fail only on a name the prose defines |
| ` ```rust,compile_fail ` | Extracted and type-checked. It must **not** compile |
| ` ```rust,compile_fail,E0499 ` | The same, and that error code must appear |
| ` ```rust,ignore ` | Not checked. The only way out of the gate |

An unknown tag is a failure, not a quiet pass: a typo in a fence would
otherwise take a block out of the check with nobody the wiser.

Name the expected code whenever you know it. Without it, a `compile_fail` block
that fails only because a name is undefined still counts as failing, and the
run prints how many blocks are in that state.

Prefer fixing the example over tagging it. `ignore` removes the block from the
check permanently, and the defect classes this harness actually finds — an
empty body under a non-unit return type, one name defined twice in one block, a
method that the crate does not have — all look like they need a tag and do not.

## Buckets

`analyze.py` sorts every failing example:

- **fragment** — every error is name resolution. Expected, ignored.
- **artifact** — the extraction caused it: a `&self` method body lifted into a
  free function, a doc comment with nothing after it.
- **low** — only "type annotations needed", which the real context supplies.
- **SUSPECT** — anything else. Treat as a real defect until shown otherwise.

## The gates

Three checks run before the buckets, and each one fails the build:

1. **Coverage.** Every example `gen.py` wrote has to appear in cargo's output.
   A block that silently stopped being compiled is a coverage drop, and a
   coverage drop reads exactly like a clean catalog unless something counts.
2. **compile_fail.** Every block tagged `compile_fail` has to fail, and has to
   produce the error codes its fence names. A demonstration that starts
   compiling after a language change is a claim the catalog can no longer make.
3. **Suspects.** Every remaining failure is bucketed, and a bucket outside the
   baseline fails the run.

`analyze.py` also refuses to report success unless `check.json` carries a
`build-finished` record and names at least one target. When cargo cannot start
— an unresolvable dependency, a malformed manifest, an unavailable toolchain —
it writes nothing to stdout, every count downstream is zero, and a naive gate
reports a clean catalog for a build that never happened. The guard turns that
into a failure and prints what cargo wrote to `check.err`.

`check.sh` prints the resolved `rustc` and `cargo` version for the same reason:
cargo's own output is redirected into `check.json`, so without that line a CI
log cannot show which toolchain compiled the examples.

## The baseline

`baseline.txt` lists accepted suspects by signature
(`file :: section :: block hash :: error codes`, with no line number, so it
survives edits above the block, and with a content hash so two blocks in one
section cannot collapse into one entry). The gate fails only on a signature
that is not listed.

It is currently empty, and that is the target state. When the gate reports a new
suspect, fix the example. Add a baseline line only for a failure no fence tag
can express, and write down why.

## Adding a dependency

When a skill starts using a crate in its examples, add it to `Cargo.toml`.
Without it every block that imports the crate degrades to a fragment and stops
being checked.

## Changing the toolchain

`rust-toolchain.toml` pins the channel and the target. CI installs nothing else;
rustup reads that file. Regenerate `baseline.txt` on the new channel in the same
commit, because error codes and wording move between releases.
