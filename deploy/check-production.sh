#!/usr/bin/env bash
set -euo pipefail

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
    echo "ai-hq-check: FAIL port 8090 is publicly bound" >&2
    exit 1
  fi
  ss -ltn | grep -Eq '127\.0\.0\.1:8090' || {
    echo "ai-hq-check: FAIL localhost port 8090 is not listening" >&2
    exit 1
  }
fi

echo "ai-hq-check: production smoke checks passed"
