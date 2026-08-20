# Third-party notices

This repository is published under BSD-3-Clause (see [LICENSE](LICENSE)). The files below
carry material from another project, under that project's terms.

## checks/ — the compile-check harness

Files: `checks/gen.py`, `checks/analyze.py`, `checks/check.sh`, `checks/baseline.txt`.

The harness began as an adaptation of the one in
[leonardomso/rust-skills](https://github.com/leonardomso/rust-skills). The design it keeps from
upstream is the shape of the pipeline: lift the Rust blocks out of the Markdown, make each one a
cargo example, compile them in a single pass, and bucket the failures instead of gating on a
plain pass or fail. The current files were rewritten around explicit fence modes, coverage and
`compile_fail` gates, and a different classifier, but the lineage is real and the notice stays.

Both `gen.py` and `analyze.py` name the source in their module docstring.

    MIT License

    Copyright (c) 2025 Leonardo Maldonado

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## Everything else

`skills/`, `scripts/`, `tests/`, and `README.md` are original to this repository and carry no
third-party code. The skills are generalized from two private production codebases; they name
public crates and public APIs, and they copy no source from them.

Crates that `checks/Cargo.toml` pulls in are build-time dependencies of the harness only. No
skill ships a crate, and nothing in `skills/` links against one.
