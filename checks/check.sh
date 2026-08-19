#!/usr/bin/env bash
# One command that reproduces CI. Run it from anywhere:
#
#     bash checks/check.sh
#
# It runs the same gates CI runs, on the toolchain and target that
# checks/rust-toolchain.toml pins, so a green run here means a green run there.
# `cargo check` type-checks without linking, so the Linux target works on any
# host with no cross-linker installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="x86_64-unknown-linux-gnu"

echo "==> catalog: frontmatter, references, routing, README parity"
python3 "$ROOT/scripts/validate-skills.py"

echo "==> extracting rust examples from skills/"
cd "$ROOT/checks"
python3 gen.py

echo "==> compile-checking examples (target: $TARGET)"
# cargo exits non-zero on the illustrative fragments. The baseline gate below is
# what decides pass or fail, so do not let the exit status stop the script.
cargo check --examples --target "$TARGET" --keep-going --message-format=json \
    > check.json 2> check.err || true

echo "==> gating against the baseline"
python3 analyze.py check.json --check-baseline baseline.txt

echo "All checks passed."
