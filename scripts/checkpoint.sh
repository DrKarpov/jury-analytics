#!/usr/bin/env bash
# Persist a completed data stage and refuse concurrent or destructive writes.
set -euo pipefail

store=$1
message=$2
shift 2
cd "$store"

git diff --cached --quiet
if [[ -z "$(git status --porcelain --untracked-files=all -- "$@")" ]]; then
    exit 0
fi
git ls-files -z --cached --others --exclude-standard -- "$@" |
    git --literal-pathspecs add -A --pathspec-from-file=- --pathspec-file-nul
git diff --cached --quiet && exit 0

if [[ -n "$(git diff --cached --name-only --diff-filter=DMRT -- seed updates audit current-audit holders/daily repairs repair-attempts genesis/v1/master.json genesis/v1/receipts genesis/v1/wallet-history/accounts genesis/v1/wallet-deployment/observations continuation/v1/accounts arbitrage/v1/verified)" ]]; then
    echo 'Refusing to change immutable history or audit records' >&2
    exit 1
fi
expected=$(git rev-parse HEAD)
remote=$(git ls-remote --exit-code origin refs/heads/data | cut -f1)
if [[ "$remote" != "$expected" ]]; then
    echo 'Data changed during the stage. A new run must replay the latest checkpoint.' >&2
    exit 1
fi
git -c user.name='github-actions[bot]' \
    -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    commit -m "$message"
git push origin HEAD:refs/heads/data
