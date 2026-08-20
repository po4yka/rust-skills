#!/usr/bin/env bash
# One command that reproduces CI. Run it from anywhere:
#
#     bash checks/check.sh
#
# It runs the same gates CI runs, on the toolchain and target that
# checks/rust-toolchain.toml pins, so a green run here means a green run there.
# The one exception is the skills-CLI discovery gate, which needs npx: this
# script says so out loud when it has to skip it, and CI always runs it.
# `cargo check` type-checks without linking, so the Linux target works on any
# host with no cross-linker installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="x86_64-unknown-linux-gnu"
SKILLS_CLI_VERSION="1.5.23"

echo "==> catalog: frontmatter, references, routing, README parity"
python3 "$ROOT/scripts/validate-skills.py"

cd "$ROOT/checks"

# The classifier decides which compile failures the catalog may ignore. A wrong
# entry in its excuse list turns a broken example into a passing one, so the
# excuse list has its own tests and they run before anything depends on them.
echo "==> unit tests: frontmatter rules and the failure classifier"
python3 "$ROOT/scripts/test_validate_skills.py" 2>&1 | tail -3
python3 test_analyze.py 2>&1 | tail -3

echo "==> extracting rust examples from skills/"
python3 gen.py

# Print what rustup resolved. cargo's own output goes to check.json and
# check.err below, so without this line nothing in a CI log shows which
# toolchain compiled the examples, and a pin that silently failed looks
# identical to one that worked.
echo "==> toolchain: $(rustc --version), $(cargo --version)"

echo "==> compile-checking examples (target: $TARGET)"
# cargo exits non-zero on the illustrative fragments and on every compile_fail
# example. The gate below is what decides pass or fail, so do not let the exit
# status stop the script.
cargo check --locked --examples --target "$TARGET" --keep-going --message-format=json \
    > check.json 2> check.err || true

echo "==> gating: coverage, compile_fail, and the suspect baseline"
python3 analyze.py check.json --check-baseline baseline.txt

echo "==> skills CLI discovers every skill"
if command -v npx > /dev/null 2>&1; then
    cd "$ROOT"
    npx -y "skills@${SKILLS_CLI_VERSION}" add ./ --list 2>&1 |
        sed 's/\x1b\[[0-9;]*m//g' > /tmp/discovered.txt
    failed=0
    for dir in skills/*/; do
        name="$(basename "$dir")"
        if ! grep -qx "[^a-z0-9-]*${name}[^a-z0-9-]*" /tmp/discovered.txt; then
            echo "  the skills CLI did not discover '${name}'"
            failed=1
        fi
    done
    [ "$failed" -eq 0 ] || exit 1
    echo "  the skills CLI discovered all $(ls -1d skills/*/ | wc -l | tr -d ' ') skills"
else
    echo "  SKIPPED: no npx on this host. CI runs this gate on every push."
fi

echo "All checks passed."
