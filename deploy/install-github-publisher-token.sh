#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=/etc/ai-hq/ai-hq.env
TOKEN_FILE=/etc/ai-hq/github-publisher.token
ENV_LINE='AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE=/etc/ai-hq/github-publisher.token'

fail(){ echo "install-github-publisher-token: $*" >&2; exit 1; }

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run as root"
[[ -f "$ENV_FILE" ]] || fail "production environment file is missing"

umask 077
read -r -s -p "GitHub publisher token: " TOKEN
echo
[[ -n "$TOKEN" ]] || fail "token must not be empty"
[[ "$TOKEN" != *[[:space:]]* ]] || fail "token must not contain whitespace"

TMP_TOKEN="$(mktemp /etc/ai-hq/.github-publisher.token.XXXXXX)"
TMP_ENV="$(mktemp /etc/ai-hq/.ai-hq.env.XXXXXX)"
cleanup(){
  rm -f "$TMP_TOKEN" "$TMP_ENV"
  unset TOKEN
}
trap cleanup EXIT

printf '%s\n' "$TOKEN" >"$TMP_TOKEN"
install -m 600 -o root -g root "$TMP_TOKEN" "$TOKEN_FILE"

awk -v replacement="$ENV_LINE" '
  BEGIN { replaced = 0 }
  /^AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE=/ {
    if (!replaced) {
      print replacement
      replaced = 1
    }
    next
  }
  { print }
  END {
    if (!replaced) print replacement
  }
' "$ENV_FILE" >"$TMP_ENV"

ENV_MODE="$(stat -c '%a' "$ENV_FILE")"
ENV_UID="$(stat -c '%u' "$ENV_FILE")"
ENV_GID="$(stat -c '%g' "$ENV_FILE")"
install -m "$ENV_MODE" -o "$ENV_UID" -g "$ENV_GID" "$TMP_ENV" "$ENV_FILE"

unset TOKEN

echo "install-github-publisher-token: publisher credential installed"
echo "install-github-publisher-token: source configured at $TOKEN_FILE"
