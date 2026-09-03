#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'ai-hq-host-helper-install: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run as root"
[[ $# -eq 0 ]] || fail "this installer accepts no command-line arguments"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE=/opt/ai-hq
VENV="$BASE/host-helper-venv"
ETC_DIR=/etc/ai-hq
HELPER_ENV="$ETC_DIR/host-helper.env"
AI_ENV="$ETC_DIR/ai-hq.env"
UNIT_SOURCE="$SCRIPT_DIR/ai-hq-host-helper.service"
UNIT_TARGET=/etc/systemd/system/ai-hq-host-helper.service
SOCKET=/run/ai-hq/host-helper.sock

for command in python3 systemctl install id grep sed; do
  command -v "$command" >/dev/null || fail "$command is required"
done

[[ -f "$SOURCE_ROOT/pyproject.toml" ]] || fail "run this installer from an AI HQ release source tree"
[[ -f "$UNIT_SOURCE" ]] || fail "host helper systemd unit is missing"
[[ -f "$AI_ENV" ]] || fail "AI HQ production environment file is missing"

if ! id ai-hq-helper >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin ai-hq-helper
fi

install -d -m 0750 "$ETC_DIR"

credential=""
if [[ -f "$HELPER_ENV" ]]; then
  credential="$(sed -n 's/^AI_HQ_HOST_HELPER_CREDENTIAL=//p' "$HELPER_ENV" | tail -n 1)"
fi

if [[ -z "$credential" ]]; then
  printf 'Enter a new AI HQ Host Helper credential (32-128 letters, numbers, _ or -): ' >/dev/tty
  IFS= read -r -s credential </dev/tty
  printf '\n' >/dev/tty
fi

[[ "$credential" =~ ^[A-Za-z0-9_-]{32,128}$ ]] || fail "credential must be 32-128 letters, numbers, underscores or hyphens"

umask 077
helper_tmp="$(mktemp "$ETC_DIR/.host-helper.env.XXXXXX")"
ai_tmp="$(mktemp "$ETC_DIR/.ai-hq.env.XXXXXX")"
cleanup() {
  rm -f "$helper_tmp" "$ai_tmp"
}
trap cleanup EXIT

{
  printf 'AI_HQ_HOST_HELPER_CREDENTIAL=%s\n' "$credential"
  printf 'AI_HQ_HOST_HELPER_SOCKET=%s\n' "$SOCKET"
} >"$helper_tmp"
chmod 600 "$helper_tmp"

# Preserve every existing AI HQ production setting while replacing only the helper credential.
grep -v '^AI_HQ_HOST_HELPER_CREDENTIAL=' "$AI_ENV" >"$ai_tmp" || true
printf 'AI_HQ_HOST_HELPER_CREDENTIAL=%s\n' "$credential" >>"$ai_tmp"
chmod 600 "$ai_tmp"

install -m 0600 "$helper_tmp" "$HELPER_ENV"
install -m 0600 "$ai_tmp" "$AI_ENV"

install -d -m 0755 "$BASE"
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir "$SOURCE_ROOT" >/dev/null

install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl daemon-reload
systemctl enable ai-hq-host-helper.service >/dev/null
systemctl restart ai-hq-host-helper.service

socket_ready=false
for _ in $(seq 1 20); do
  if test -S /run/ai-hq/host-helper.sock; then
    socket_ready=true
    break
  fi
  sleep 1
done
[[ "$socket_ready" == true ]] || fail "host helper socket did not become ready"

printf 'ai-hq-host-helper-install: host helper installed and socket is ready\n'
