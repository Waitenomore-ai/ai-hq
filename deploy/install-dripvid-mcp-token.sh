#!/usr/bin/env bash
set -euo pipefail

SOURCE_ENV=/etc/dripvid/mcp.env
TARGET_TOKEN=/etc/ai-hq/dripvid-mcp.token
TARGET_ENV=/etc/ai-hq/ai-hq.env

fail(){ echo "install-dripvid-mcp-token: $*" >&2; exit 1; }

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run as root"
[[ -f "$SOURCE_ENV" && ! -L "$SOURCE_ENV" ]] || fail "DripVid MCP environment file is missing"
[[ -f "$TARGET_ENV" && ! -L "$TARGET_ENV" ]] || fail "AI HQ production environment file is missing"

SOURCE_MODE="$(stat -c '%a' "$SOURCE_ENV")"
SOURCE_UID="$(stat -c '%u' "$SOURCE_ENV")"
[[ "$SOURCE_UID" == "0" ]] || fail "DripVid MCP environment file must be owned by root"
(( (8#$SOURCE_MODE & 077) == 0 )) || fail "DripVid MCP environment file permissions are too broad"

TOKEN=""
while IFS= read -r line; do
  case "$line" in
    MCP_BEARER_TOKEN=*)
      TOKEN="${line#MCP_BEARER_TOKEN=}"
      break
      ;;
  esac
done < "$SOURCE_ENV"

[[ -n "$TOKEN" ]] || fail "DripVid MCP bearer token is missing"
[[ "$TOKEN" != "CHANGE_ME_GENERATE_SECURE_TOKEN" ]] || fail "DripVid MCP bearer token is still a placeholder"
[[ "$TOKEN" != *[[:space:]]* ]] || fail "DripVid MCP bearer token contains whitespace"
[[ ${#TOKEN} -ge 32 && ${#TOKEN} -le 4096 ]] || fail "DripVid MCP bearer token length is invalid"

umask 077
TMP_TOKEN="$(mktemp /etc/ai-hq/.dripvid-mcp.token.XXXXXX)"
TMP_ENV="$(mktemp /etc/ai-hq/.ai-hq.env.XXXXXX)"
cleanup(){
  rm -f "$TMP_TOKEN" "$TMP_ENV"
  unset TOKEN line
}
trap cleanup EXIT

printf '%s' "$TOKEN" > "$TMP_TOKEN"
install -m 600 -o root -g root "$TMP_TOKEN" "$TARGET_TOKEN"
chmod 600 "$TARGET_TOKEN"
chown root:root "$TARGET_TOKEN"
unset TOKEN line

awk '
  BEGIN {
    socket = 0
    file = 0
    source = 0
    timeout = 0
  }
  /^AI_HQ_DRIPVID_MCP_SOCKET=/ {
    if (!socket) print "AI_HQ_DRIPVID_MCP_SOCKET=/run/dripvid-mcp/mcp.sock"
    socket = 1
    next
  }
  /^AI_HQ_DRIPVID_MCP_TOKEN_FILE=/ {
    if (!file) print "AI_HQ_DRIPVID_MCP_TOKEN_FILE=/run/secrets/dripvid-mcp-token"
    file = 1
    next
  }
  /^AI_HQ_DRIPVID_MCP_TOKEN_SOURCE=/ {
    if (!source) print "AI_HQ_DRIPVID_MCP_TOKEN_SOURCE=/etc/ai-hq/dripvid-mcp.token"
    source = 1
    next
  }
  /^AI_HQ_DRIPVID_MCP_TIMEOUT_SECONDS=/ {
    if (!timeout) print "AI_HQ_DRIPVID_MCP_TIMEOUT_SECONDS=5"
    timeout = 1
    next
  }
  { print }
  END {
    if (!socket) print "AI_HQ_DRIPVID_MCP_SOCKET=/run/dripvid-mcp/mcp.sock"
    if (!file) print "AI_HQ_DRIPVID_MCP_TOKEN_FILE=/run/secrets/dripvid-mcp-token"
    if (!source) print "AI_HQ_DRIPVID_MCP_TOKEN_SOURCE=/etc/ai-hq/dripvid-mcp.token"
    if (!timeout) print "AI_HQ_DRIPVID_MCP_TIMEOUT_SECONDS=5"
  }
' "$TARGET_ENV" > "$TMP_ENV"

ENV_MODE="$(stat -c '%a' "$TARGET_ENV")"
ENV_UID="$(stat -c '%u' "$TARGET_ENV")"
ENV_GID="$(stat -c '%g' "$TARGET_ENV")"
install -m "$ENV_MODE" -o "$ENV_UID" -g "$ENV_GID" "$TMP_ENV" "$TARGET_ENV"

echo "install-dripvid-mcp-token: MCP credential installed without displaying it"
echo "install-dripvid-mcp-token: AI HQ MCP paths configured"
