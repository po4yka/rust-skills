#!/usr/bin/env bash
# Builds the case workspace (the current directory) as a git repository with two commits:
# the released 1.4.2 tree from files/, tagged v1.4.2, and the unreleased change from next/.
# A local build leaves target/ behind; it is not part of the fixture.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

export GIT_AUTHOR_NAME="Crate Maintainer" GIT_AUTHOR_EMAIL="maintainer@example.invalid"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git_() { git -c commit.gpgsign=false -c tag.gpgsign=false -c core.hooksPath=/dev/null "$@"; }

(cd "$here/files" && tar -cf - --exclude=./target .) | tar -xf -
printf 'target/\n' > .gitignore
git_ init -q -b main
git_ add -A
GIT_AUTHOR_DATE="2026-08-14T10:00:00Z" GIT_COMMITTER_DATE="2026-08-14T10:00:00Z" \
    git_ commit -q -m "Release 1.4.2"
git_ tag -a v1.4.2 -m "confmt 1.4.2"

(cd "$here/next" && tar -cf - --exclude=./target .) | tar -xf -
git_ add -A
GIT_AUTHOR_DATE="2026-10-20T10:00:00Z" GIT_COMMITTER_DATE="2026-10-20T10:00:00Z" \
    git_ commit -q -m "feat: add YAML support and case-insensitive detection"
