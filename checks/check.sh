#!/usr/bin/env bash
# One command that reproduces CI. Run it from anywhere:
#
#     bash checks/check.sh
#     bash checks/check.sh --fast        # no cargo: catalog, unit tests, and client gates
#     bash checks/check.sh --no-clients  # no npx: catalog, unit tests, and cargo gates
#
# --fast is for the edit loop of a description or a marketplace change. It
# skips every gate that runs cargo: the compile check of the examples, the
# behavior probes, and the outcome fixtures. A green --fast run is not a green
# CI run; run the full script before a pull request.
#
# --no-clients skips the three gates that run a consumer's CLI through npx. CI
# uses it in the job that compiles the examples, because the job that validates
# the catalog runs those gates with --fast; each CI run then installs each
# client once. The two flags together run only the catalog and unit tests.
#
# It runs the same gates CI runs, on the toolchain and target that
# checks/rust-toolchain.toml pins, so a green run here means a green run there.
# The exceptions are the three gates that run a consumer's CLI through npx: the
# skills-CLI discovery and the Claude Code and Codex plugin installs. This
# script says so out loud when it has to skip them, and CI always runs them.
# `cargo check` type-checks without linking, so the Linux target works on any
# host with no cross-linker installed. The one C build script in the harness
# (alloca, from criterion) needs clang on a non-Linux host; see below.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="x86_64-unknown-linux-gnu"
SKILLS_CLI_VERSION="1.7.4"
# The Claude Code CLI for the plugin install gate. This line is the one pin:
# .github/workflows/plugin-eval.yml and client-compat.yml read it, so the
# install gate and the evaluations judge the plugin with the same client.
CLAUDE_CODE_VERSION="2.1.316"
# The Codex CLI for the same gate. Codex reads .claude-plugin/marketplace.json
# as a legacy-compatible marketplace, so a Codex release can change the result.
# After a bump, check CODEX_BUILTIN_SKILLS in checks/plugin_install.py: a new
# built-in skill shows up as a foreign skill in the gate.
CODEX_VERSION="0.166.0"

FAST=0
CLIENTS=1
for arg in "$@"; do
    case "$arg" in
        --fast) FAST=1 ;;
        --no-clients) CLIENTS=0 ;;
        *)
            echo "usage: bash checks/check.sh [--fast] [--no-clients]" >&2
            exit 2
            ;;
    esac
done

# gen.py, cargo, and analyze.py share examples/, manifest.json, check.json, and
# check.err. Hold one checkout-scoped process lock across the complete sequence
# so parallel agents cannot replace an artifact while another run reads it.
if [ "${RUST_SKILLS_CHECK_LOCKED:-}" != "1" ]; then
    exec python3 "$ROOT/checks/with_lock.py" --root "$ROOT" -- \
        bash "$ROOT/checks/check.sh" "$@"
fi

echo "==> catalog: frontmatter, references, routing, bundles, budgets, README parity"
python3 "$ROOT/scripts/validate-skills.py"

echo "==> routing evaluation set: schema, coverage, and blindness (no key, no network)"
python3 "$ROOT/evals/routing/run.py" --lint

cd "$ROOT/checks"

# The classifier decides which compile failures the catalog may ignore. A wrong
# entry in its excuse list turns a broken example into a passing one, so the
# excuse list has its own tests and they run before anything depends on them.
echo "==> unit tests: catalog rules, drift report, eval lints, check locking, plugin install, agent hook, and the classifier"
python3 "$ROOT/scripts/test_validate_skills.py" 2>&1 | tail -3
python3 "$ROOT/scripts/test_drift_report.py" 2>&1 | tail -3
python3 "$ROOT/evals/routing/test_run.py" 2>&1 | tail -3
python3 "$ROOT/evals/outcome/test_check.py" 2>&1 | tail -3
python3 "$ROOT/evals/outcome/test_cross_agent.py" 2>&1 | tail -3
python3 test_with_lock.py 2>&1 | tail -3
python3 test_lint_gate.py 2>&1 | tail -3
python3 test_plugin_install.py 2>&1 | tail -3
python3 test_gen.py 2>&1 | tail -3
python3 test_analyze.py 2>&1 | tail -3
python3 "$ROOT/scripts/test_agent_hook.py" 2>&1 | tail -3

RUN_DIR="$(mktemp -d)"
trap 'rm -rf "$RUN_DIR"' EXIT

# The cargo gates. --fast skips this block; its body stays at the outer
# indentation so each gate reads as it does in CI.
if [ "$FAST" -eq 1 ]; then
    echo "==> SKIPPED (--fast): rust example compile check, behavior probes, outcome fixtures"
else
echo "==> extracting rust examples from skills/"
python3 gen.py

# Print what rustup resolved. cargo's own output goes to check.json and
# check.err below, so without this line nothing in a CI log shows which
# toolchain compiled the examples, and a pin that silently failed looks
# identical to one that worked.
echo "==> toolchain: $(rustc --version), $(cargo --version)"

# criterion 0.8 depends on alloca, whose build script compiles alloca.c for the
# target even under `cargo check`. alloca.c includes only <stddef.h> and
# <stdint.h>, which clang ships itself, so clang builds it for the Linux target
# with no Linux sysroot, and `cargo check` never links the object. On a host
# that is not x86_64 Linux, cc would otherwise look for x86_64-linux-gnu-gcc,
# which a macOS host does not have. A CC_x86_64_unknown_linux_gnu that the
# caller set wins.
HOST="$(rustc -vV | sed -n 's/^host: //p')"
if [ "$HOST" != "$TARGET" ] && [ -z "${CC_x86_64_unknown_linux_gnu:-}" ] &&
    command -v clang > /dev/null 2>&1; then
    export CC_x86_64_unknown_linux_gnu=clang
    export CFLAGS_x86_64_unknown_linux_gnu="-ffreestanding"
    export AR_x86_64_unknown_linux_gnu="$(command -v llvm-ar || command -v ar)"
    echo "==> host $HOST: building target C sources with clang --target=$TARGET"
fi

echo "==> compile-checking examples (target: $TARGET)"
# cargo exits non-zero on the illustrative fragments and on every compile_fail
# example. The gate below is what decides pass or fail, so do not let the exit
# status stop the script.
cargo check --locked --examples --target "$TARGET" --keep-going --message-format=json \
    > check.json 2> check.err || true

echo "==> gating: coverage, compile_fail, fragments, and the suspect baseline"
python3 analyze.py check.json --check-fragments fragments.txt --check-baseline baseline.txt

echo "==> running behavior probes on the native host"
run_count=0
while IFS= read -r example; do
    [ -n "$example" ] || continue
    rustc --edition=2024 "examples/${example}.rs" -o "$RUN_DIR/$example"
    python3 -c 'import subprocess, sys; subprocess.run([sys.argv[1]], check=True, timeout=10)' \
        "$RUN_DIR/$example"
    run_count=$((run_count + 1))
done < <(
    python3 -c 'import json; print("\n".join(k for k, v in json.load(open("manifest.json", encoding="utf-8")).items() if v["mode"] == "run"))'
)
echo "  ${run_count} behavior probe(s) passed"

# The rust-lints skill names about fifty lints in its strict template. The gate copies that
# template and the skill's clippy.toml into a throwaway workspace and requires each named lint
# to fire on a marked line of checks/lints/violations.rs, so a lint that a toolchain bump
# removes, renames, or silences fails here instead of in a reader's workspace.
echo "==> rust-lints templates: every named lint exists and fires (clippy)"
python3 "$ROOT/checks/lint_gate.py"

# Each outcome case plants a defect in a small std-only crate. The gate builds every fixture
# offline on the pinned toolchain, checks that `cargo test` does what cases.toml says, and
# requires each probe to fail on the fixture and to pass on the reference fix in solution/, so a
# fixture cannot lose its defect without a red build.
echo "==> outcome evaluation suite: case structure and planted defects (no key, no network)"
python3 "$ROOT/evals/outcome/check.py"
fi  # end of the cargo gates

# The client gates. --no-clients skips this block; its body stays at the outer
# indentation, as the cargo gates do.
if [ "$CLIENTS" -eq 0 ]; then
    echo "==> SKIPPED (--no-clients): skills CLI discovery, Claude Code and Codex plugin installs"
else
# A local host without npx skips these gates and says so. In CI the skip would
# hide the only proof that the clients load the catalog, so it fails instead.
if [ -n "${CI:-}" ] && ! command -v npx > /dev/null 2>&1; then
    echo "FAIL: CI has no npx, so the client gates cannot run"
    exit 1
fi

echo "==> skills CLI discovers every skill"
if command -v npx > /dev/null 2>&1; then
    cd "$ROOT"
    npx -y "skills@${SKILLS_CLI_VERSION}" add ./ --list 2>&1 |
        sed 's/\x1b\[[0-9;]*m//g' > "$RUN_DIR/discovered.txt"
    failed=0
    for dir in skills/*/; do
        name="$(basename "$dir")"
        if ! grep -qx "[^a-z0-9-]*${name}[^a-z0-9-]*" "$RUN_DIR/discovered.txt"; then
            echo "  the skills CLI did not discover '${name}'"
            failed=1
        fi
    done
    [ "$failed" -eq 0 ] || exit 1
    echo "  the skills CLI discovered all $(ls -1d skills/*/ | wc -l | tr -d ' ') skills"
else
    echo "  SKIPPED: no npx on this host. CI runs this gate on every push."
fi

# validate-skills.py proves the marketplace file matches bundles.toml. This
# gate proves Claude Code loads each plugin with exactly those skills. It uses a
# throwaway config directory, so it needs no login and leaves ~/.claude alone.
echo "==> Claude Code installs every plugin with exactly its skills"
if command -v npx > /dev/null 2>&1; then
    python3 "$ROOT/checks/plugin_install.py" \
        --claude "npx -y -p @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} claude"
else
    echo "  SKIPPED: no npx on this host. CI runs this gate on every push."
fi

# The same comparison for Codex, which reads the same marketplace file. Each
# plugin installs into its own throwaway CODEX_HOME and HOME, so ~/.codex and
# ~/.agents are untouched and do not share the skill list. Each bundle must
# also keep every routing phrase visible after Codex shortens its descriptions.
echo "==> Codex installs every plugin with exactly its skills, routing phrases visible"
if command -v npx > /dev/null 2>&1; then
    python3 "$ROOT/checks/plugin_install.py" --codex "npx -y @openai/codex@${CODEX_VERSION}"
else
    echo "  SKIPPED: no npx on this host. CI runs this gate on every push."
fi
fi  # end of the client gates

if [ "$FAST" -eq 1 ] || [ "$CLIENTS" -eq 0 ]; then
    skipped=""
    [ "$FAST" -eq 0 ] || skipped=" cargo"
    [ "$CLIENTS" -eq 1 ] || skipped="${skipped} clients"
    echo "Checks passed. Skipped gates:${skipped}. Run bash checks/check.sh before a pull request."
else
    echo "All checks passed."
fi
