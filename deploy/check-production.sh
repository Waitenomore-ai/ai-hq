#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "ai-hq-check: FAIL $*" >&2
  exit 1
}

check_url() {
  local label="$1"
  local url="$2"
  curl -fsS --max-time 8 "$url" >/dev/null || {
    echo "ai-hq-check: FAIL $label" >&2
    exit 1
  }
  echo "ai-hq-check: OK $label"
}

check_url "DripVid root" "https://dripvid.uk/"
check_url "AI HQ login" "https://dripvid.uk/ai-hq/login"
check_url "AI HQ liveness" "https://dripvid.uk/ai-hq/health/live"
check_url "AI HQ readiness" "https://dripvid.uk/ai-hq/health/ready"
check_url "AI HQ local readiness" "http://127.0.0.1:8090/health/ready"

if command -v ss >/dev/null; then
  if ss -ltn | grep -Eq '0\.0\.0\.0:8090|\[::\]:8090'; then
    fail "port 8090 is publicly bound"
  fi
  ss -ltn | grep -Eq '127\.0\.0\.1:8090' || fail "localhost port 8090 is not listening"
fi

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run as root so the root-readable helper credential can be verified safely"
command -v python3 >/dev/null || fail "python3 is required"
command -v docker >/dev/null || fail "docker is required"

test -S /run/ai-hq/host-helper.sock || fail "Host Helper socket is missing"
[[ "$(stat -c '%a' /run/ai-hq/host-helper.sock)" == "660" ]] || fail "Host Helper socket mode is not 660"
[[ -f /etc/ai-hq/host-helper.env ]] || fail "Host Helper environment file is missing"

python3 - <<'PY' || fail "Host Helper authenticated health request failed"
import json
import socket
from pathlib import Path

credential = None
for line in Path("/etc/ai-hq/host-helper.env").read_text().splitlines():
    if line.startswith("AI_HQ_HOST_HELPER_CREDENTIAL="):
        credential = line.split("=", 1)[1]
        break
if not credential:
    raise SystemExit(1)

request = {
    "credential": credential,
    "capability": "host.health",
    "target": None,
    "params": {},
}
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.settimeout(4)
try:
    client.connect("/run/ai-hq/host-helper.sock")
    client.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
    data = bytearray()
    while len(data) <= 65536:
        chunk = client.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
finally:
    client.close()

if len(data) > 65536:
    raise SystemExit(1)
response = json.loads(bytes(data).split(b"\n", 1)[0].decode())
if response.get("ok") is not True or response.get("capability") != "host.health":
    raise SystemExit(1)
PY
echo "ai-hq-check: OK Host Helper authenticated health"

worker_id="$(docker ps -q --filter 'label=com.docker.compose.project=ai-hq' --filter 'label=com.docker.compose.service=worker' | head -n 1)"
web_id="$(docker ps -q --filter 'label=com.docker.compose.project=ai-hq' --filter 'label=com.docker.compose.service=web' | head -n 1)"
[[ -n "$worker_id" ]] || fail "AI HQ worker container is not running"
[[ -n "$web_id" ]] || fail "AI HQ web container is not running"

worker_mounts="$(docker inspect --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' "$worker_id")"
web_mounts="$(docker inspect --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' "$web_id")"

grep -Fq '/run/ai-hq/host-helper.sock' <<<"$worker_mounts" || fail "worker does not have Host Helper socket mount"
if grep -Fq '/run/ai-hq/host-helper.sock' <<<"$web_mounts"; then
  fail "web container must not have Host Helper socket mount"
fi
if grep -Fq '/var/run/docker.sock' <<<"$worker_mounts$web_mounts"; then
  fail "AI HQ containers must not have Docker socket access"
fi
[[ "$(docker inspect --format '{{.HostConfig.Privileged}}' "$worker_id")" == "false" ]] || fail "worker is privileged"
[[ "$(docker inspect --format '{{.HostConfig.Privileged}}' "$web_id")" == "false" ]] || fail "web is privileged"
echo "ai-hq-check: OK worker-only Host Helper isolation"

echo "ai-hq-check: production smoke checks passed"
