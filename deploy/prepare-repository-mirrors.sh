#!/usr/bin/env bash
set -euo pipefail

fail() {
    echo "prepare-repository-mirrors: $*" >&2
    exit 1
}

[[ $# -eq 2 ]] || fail \
    "usage: prepare-repository-mirrors.sh <ai-hq-source> <dripvid-source>"

AI_SOURCE="$(readlink -f "$1")"
DRIPVID_SOURCE="$(readlink -f "$2")"

[[ -e "$AI_SOURCE/.git" ]] || fail \
    "AI HQ source must be a Git worktree"

[[ -e "$DRIPVID_SOURCE/.git" ]] || fail \
    "DripVid source must be a Git worktree"

command -v rsync >/dev/null || fail \
    "rsync is required"

command -v npm >/dev/null || fail \
    "npm is required"

BASE="/opt/ai-hq/repository-mirrors"
SANDBOX="/opt/ai-hq/repository-sandboxes"
STAGE="$BASE/.stage-$$"

cleanup() {
    rm -rf "$STAGE"
}

trap cleanup EXIT

install -d -m 0755 "$BASE"
install -d -m 0770 "$SANDBOX"

mkdir -p \
    "$STAGE/ai-hq" \
    "$STAGE/dripvid"

rsync -a --delete \
    --exclude=.git \
    --exclude=.venv \
    --exclude=__pycache__ \
    --exclude=node_modules \
    "$AI_SOURCE/" \
    "$STAGE/ai-hq/"

rsync -a --delete \
    --exclude=.git \
    --exclude=.venv \
    --exclude=__pycache__ \
    --exclude=node_modules \
    "$DRIPVID_SOURCE/" \
    "$STAGE/dripvid/"

(
    cd "$STAGE/dripvid"
    npm ci
)

chmod -R a-w \
    "$STAGE/ai-hq" \
    "$STAGE/dripvid"

rm -rf \
    "$BASE/ai-hq.previous" \
    "$BASE/dripvid.previous"

if [[ -d "$BASE/ai-hq" ]]; then
    mv \
        "$BASE/ai-hq" \
        "$BASE/ai-hq.previous"
fi

if [[ -d "$BASE/dripvid" ]]; then
    mv \
        "$BASE/dripvid" \
        "$BASE/dripvid.previous"
fi

mv \
    "$STAGE/ai-hq" \
    "$BASE/ai-hq"

mv \
    "$STAGE/dripvid" \
    "$BASE/dripvid"

rmdir "$STAGE"
trap - EXIT

echo "Trusted mirrors prepared."
echo "AI HQ:   $BASE/ai-hq"
echo "DripVid: $BASE/dripvid"
echo "Sandbox: $SANDBOX"
