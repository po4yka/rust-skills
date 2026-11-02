#!/usr/bin/env bash
# Copies the fixture crate into the case workspace (the current directory).
# A local build leaves files/target/ behind; it is not part of the fixture.
set -euo pipefail
(cd "$(dirname "$0")/files" && tar -cf - --exclude=./target .) | tar -xf -
