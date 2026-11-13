#!/usr/bin/env bash
# Reuse a std-only fixture whose existing tests pass before the agent changes it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../../.." && pwd)"
(cd "$root/evals/outcome/design-error-source-chain/files" && tar -cf - --exclude=./target .) | tar -xf -
