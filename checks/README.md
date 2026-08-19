# checks — compile-verify the examples in the skills

The catalog ships no Rust crate, so nothing in it is exercised by a build. This
harness closes that gap for the part that matters most: the code an agent is
told to copy. It extracts every ` ```rust ` block from `../skills/**/*.md`,
type-checks it, and fails CI on a new failure it cannot explain.

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
python3 checks/gen.py                         # blocks -> checks/examples/
cd checks
cargo check --examples --keep-going --message-format=json > check.json
python3 analyze.py check.json                 # summary plus suspect detail
python3 analyze.py check.json --check-baseline baseline.txt   # the CI gate
```

## How a block opts out

Most blocks are fragments: they name types the prose defines, so they cannot
resolve alone. That is fine and expected — the analyzer buckets them and moves
on. Two cases need an explicit tag on the fence, following rustdoc:

| Fence | Meaning |
| --- | --- |
| ` ```rust ` | Extracted and type-checked |
| ` ```rust,compile_fail ` | A deliberate error demonstration. Not extracted |
| ` ```rust,ignore ` | Cannot compile standalone by design: a build-script `include!`, pseudocode with `...` bodies. Not extracted |

Prefer fixing the example over tagging it. A tag removes the block from the
check permanently, and the two defect classes this harness actually finds —
an empty body under a non-unit return type, and one name defined twice in one
block — both look like they need a tag and do not.

## Buckets

`analyze.py` sorts every failing example:

- **fragment** — every error is name resolution. Expected, ignored.
- **artifact** — the extraction caused it: a `&self` method body lifted into a
  free function, a doc comment with nothing after it.
- **low** — only "type annotations needed", which the real context supplies.
- **SUSPECT** — anything else. Treat as a real defect until shown otherwise.

## The baseline

`baseline.txt` lists accepted suspects by signature
(`file :: section :: error codes`, with no line number, so it survives edits
above the block). The gate fails only on a signature that is not listed.

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
