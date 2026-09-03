#!/usr/bin/env bash
set -euo pipefail

fail(){ echo "ai-hq-nginx-render: $*" >&2; exit 1; }

[[ $# -eq 2 ]] || fail "usage: render-nginx.sh <dripvid-server-conf> <candidate-output>"
SOURCE="$1"
CANDIDATE="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNIPPET="$SCRIPT_DIR/nginx-ai-hq-location.conf"

[[ -f "$SOURCE" ]] || fail "source nginx config not found"
[[ -f "$SNIPPET" ]] || fail "nginx-ai-hq-location.conf not found"
[[ "$SOURCE" != "$CANDIDATE" ]] || fail "candidate output must not overwrite source config"

python3 - "$SOURCE" "$CANDIDATE" "$SNIPPET" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
candidate = Path(sys.argv[2])
snippet = Path(sys.argv[3]).read_text().rstrip() + "\n\n"
text = source.read_text()
marker = "    location / {"
if marker not in text:
    raise SystemExit("ai-hq-nginx-render: DripVid catch-all location / { not found")
if "location /ai-hq/" in text:
    raise SystemExit("ai-hq-nginx-render: AI HQ route already exists in source config")
rendered = text.replace(marker, snippet + marker, 1)
candidate.write_text(rendered)
PY

echo "ai-hq-nginx-render: candidate written to $CANDIDATE"
echo "ai-hq-nginx-render: validate with: sudo nginx -t -c $CANDIDATE (or install candidate then run sudo nginx -t)"
