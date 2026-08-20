# checks — verify the Rust examples in the skills

The catalog ships no Rust crate, so nothing in it is exercised by a build. This
harness closes that gap for the part that matters most: the code an agent is
told to copy. It reads every ` ```rust ` block in `../skills/**/*.md`, compiles
it as the fence requires, runs portable behavior probes, and fails CI on any
result the fence did not promise.

There is no heuristic skip. A block is checked, is proved to fail, or carries
`ignore` on its fence, and the counts are printed on every run.

It is a development tool. It is not part of any skill, and `npx skills add`
never sees it.

## Run

```bash
bash checks/check.sh
```

That is the whole contract, and it is exactly what CI runs. The steps, if you
need one of them alone:

`check.sh` holds a checkout-scoped process lock for the complete run. Parallel
calls wait instead of replacing `examples/`, `manifest.json`, `check.json`, or
`check.err` while another call reads them. The lock is outside the checkout and
the operating system releases it when the process exits. The individual phase
commands below do not hold this lock. Do not run those commands concurrently in
one checkout.

```bash
python3 scripts/validate-skills.py            # frontmatter, references, routing, README; no toolchain
python3 scripts/test_validate_skills.py       # the frontmatter rules themselves
python3 checks/test_with_lock.py               # parallel-run serialization
python3 checks/test_gen.py                     # executable-fence rules
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
| ` ```rust,run ` | Must compile cleanly, then its `fn main()` runs on the native host |
| ` ```rust,compile_fail ` | Extracted and type-checked. It must **not** compile |
| ` ```rust,compile_fail,E0499 ` | The same, and that error code must appear |
| ` ```rust,ignore ` | Not checked. The only way out of the gate |

An unknown tag is a failure, not a quiet pass: a typo in a fence would
otherwise take a block out of the check with nobody the wiser.

Use `rust,run` only for small, portable standard-library probes. It is stricter
than an ordinary block: it cannot degrade into a fragment, must define
`fn main()`, and cannot contain `TODO`, `FIXME`, `todo!()`, or
`unimplemented!()`. The target compile gate still checks it first. `check.sh`
then compiles it with the pinned toolchain for the native host and executes it.

Name the expected code whenever you know it. Without it, a `compile_fail` block
that fails only because a name is undefined still counts as failing, and the
run prints how many blocks are in that state.

Prefer fixing the example over tagging it. `ignore` removes the block from the
check permanently, and the defect classes this harness actually finds — an
empty body under a non-unit return type, one name defined twice in one block, a
method that the crate does not have — all look like they need a tag and do not.

## Buckets

`analyze.py` sorts every failing example:

- **fragment** — every error is a name that the surrounding prose defines.
  A missing harness dependency or disabled dependency feature is a suspect,
  because it can hide all later type errors in the block.
- **artifact** — the extraction caused it: a `&self` method body lifted into a
  free function, a doc comment with nothing after it.
- **low** — only "type annotations needed", which the real context supplies.
- **SUSPECT** — anything else. Treat as a real defect until shown otherwise.

## The gates

Four checks run before the buckets, and each one fails the build:

1. **Coverage.** Every example `gen.py` wrote has to appear in cargo's output.
   A block that silently stopped being compiled is a coverage drop, and a
   coverage drop reads exactly like a clean catalog unless something counts.
2. **Run compilation.** Every block tagged `run` must compile cleanly. It cannot
   use the undefined-name or baseline exceptions.
3. **compile_fail.** Every block tagged `compile_fail` has to fail, and has to
   produce the error codes its fence names. A demonstration that starts
   compiling after a language change is a claim the catalog can no longer make.
4. **Suspects.** Every remaining failure is bucketed, and a bucket outside the
   baseline fails the run.

After these gates, `check.sh` compiles and executes each run block on the native
host. A panic, non-zero exit, or ten-second timeout fails the run.

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
being checked. `test_analyze.py` pins this contract: a missing external crate or
a disabled feature on a required crate is never an allowed fragment. Add each
dependency-backed import to `REQUIRED_EXTERNAL_CRATES` in `analyze.py` so a
later manifest edit cannot silently reduce its coverage.

### Bounded `imbl` advisory exception

The harness pins `imbl` 7.0.1 only to type-check the complete persistent-vector
example. That crate pulls `bitmaps` 3.2.1. The version matches
RUSTSEC-2025-0167 (unsoundness) and RUSTSEC-2026-0247 (unmaintained), and no
patched `bitmaps` release exists. Removing `imbl` would turn the example's
first import into a fragment and hide its API checks.

This exception is limited to the compile harness. `cargo check` does not run
the example, and `checks/` is not installed with the skills. Keep the direct
version exact. Re-run `cargo tree --locked -i bitmaps` on every harness
dependency update. Remove the dependency as soon as `imbl` no longer pulls
`bitmaps`, or replace the example and record the intentional coverage change.

## Changing the toolchain

`rust-toolchain.toml` pins the channel and the target. CI installs nothing else;
rustup reads that file. Regenerate `baseline.txt` on the new channel in the same
commit, because error codes and wording move between releases.
