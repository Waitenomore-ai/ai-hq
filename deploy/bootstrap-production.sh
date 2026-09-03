#!/usr/bin/env bash
set -euo pipefail

fail() { echo "ai-hq-bootstrap: $*" >&2; exit 1; }
log() { echo "ai-hq-bootstrap: $*"; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "must run as root"
[[ $# -eq 1 ]] || fail "usage: bootstrap-production.sh <40-char-git-sha>"

SHA="$1"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "release SHA must be exactly 40 lowercase hex characters"

ARCHIVE="/tmp/ai-hq-release-${SHA}.tgz"
RELEASE_URL="https://github.com/Waitenomore-ai/ai-hq/archive/${SHA}.tar.gz"
ENV_DIR="/etc/ai-hq"
ENV_FILE="/etc/ai-hq/ai-hq.env"
BASE="/opt/ai-hq"
DRIPVID_NGINX="/etc/nginx/sites-available/dripvid.uk"
NGINX_BACKUP="${DRIPVID_NGINX}.pre-ai-hq.$(date +%Y%m%d%H%M%S)"
TMP_DIR="$(mktemp -d /tmp/ai-hq-bootstrap.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

for cmd in curl docker python3 openssl nginx systemctl tar; do
    command -v "$cmd" >/dev/null 2>&1 || fail "required command not found: $cmd"
done

docker compose version >/dev/null 2>&1 || fail "docker compose plugin is required"
[[ -f "$DRIPVID_NGINX" ]] || fail "DripVid nginx config not found: $DRIPVID_NGINX"

if [[ ! -f "$ARCHIVE" ]]; then
    log "fetching immutable AI HQ release $SHA from GitHub"
    curl -fL --retry 3 --connect-timeout 10 "$RELEASE_URL" -o "$ARCHIVE"
fi

tar -tzf "$ARCHIVE" >/dev/null || fail "release archive is not a valid gzip tar archive: $ARCHIVE"

mkdir -p "$ENV_DIR" "$BASE/releases"
chmod 750 "$ENV_DIR" "$BASE"

tar -xzf "$ARCHIVE" -C "$TMP_DIR"
SRC_DIR="$(find "$TMP_DIR" -maxdepth 2 -type f -name pyproject.toml -printf '%h\n' | head -n1)"
[[ -n "$SRC_DIR" ]] || fail "release archive does not contain pyproject.toml"
[[ -f "$SRC_DIR/deploy/ai-hq-deploy" ]] || fail "release archive missing deploy/ai-hq-deploy"
[[ -f "$SRC_DIR/deploy/render-nginx.sh" ]] || fail "release archive missing deploy/render-nginx.sh"
[[ -f "$SRC_DIR/deploy/check-production.sh" ]] || fail "release archive missing deploy/check-production.sh"

if [[ -f "$ENV_FILE" ]]; then
    fail "$ENV_FILE already exists; refusing to overwrite existing production secrets"
fi

log "building temporary AI HQ image for secure password hashing"
docker build -q -t "ai-hq-bootstrap:${SHA}" "$SRC_DIR" >/dev/null

log "choose the separate AI HQ administrator password"
ADMIN_HASH="$(docker run --rm -it "ai-hq-bootstrap:${SHA}" ai-hq hash-admin-password | tr -d '\r' | tail -n1)"
[[ "$ADMIN_HASH" == \$argon2* ]] || fail "hash-admin-password did not return an Argon2 hash"

SESSION_SECRET="$(openssl rand -hex 32)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"

umask 077
cat >"$ENV_FILE" <<EOF
AI_HQ_ENVIRONMENT=production
AI_HQ_DATABASE_URL=postgresql+psycopg://ai_hq:${POSTGRES_PASSWORD}@postgres:5432/ai_hq
AI_HQ_REDIS_URL=redis://redis:6379/0
AI_HQ_OPERATING_MODE=safe
AI_HQ_SIMULATION_MODE=true
AI_HQ_LOG_LEVEL=INFO
AI_HQ_ROOT_PATH=/ai-hq
AI_HQ_ADMIN_PASSWORD_HASH=${ADMIN_HASH}
AI_HQ_SESSION_SECRET=${SESSION_SECRET}
AI_HQ_SESSION_LIFETIME_HOURS=12
POSTGRES_DB=ai_hq
POSTGRES_USER=ai_hq
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EOF
chmod 600 "$ENV_FILE"

log "validating generated AI HQ environment without printing secrets"
grep -q '^AI_HQ_ENVIRONMENT=production$' "$ENV_FILE" || fail "production environment missing"
grep -q '^AI_HQ_OPERATING_MODE=safe$' "$ENV_FILE" || fail "Safe Mode missing"
grep -q '^AI_HQ_SIMULATION_MODE=true$' "$ENV_FILE" || fail "Simulation Mode missing"
grep -q '^AI_HQ_ROOT_PATH=/ai-hq$' "$ENV_FILE" || fail "root path missing"

log "deploying exact release $SHA"
bash "$SRC_DIR/deploy/ai-hq-deploy" "$SHA"

log "preparing DripVid nginx backup and AI HQ candidate route"
cp -a "$DRIPVID_NGINX" "$NGINX_BACKUP"
CANDIDATE="$TMP_DIR/dripvid.uk.ai-hq.candidate"
bash "$SRC_DIR/deploy/render-nginx.sh" "$DRIPVID_NGINX" "$CANDIDATE"

cp "$CANDIDATE" "$DRIPVID_NGINX"
if ! nginx -t; then
    cp -a "$NGINX_BACKUP" "$DRIPVID_NGINX"
    nginx -t || true
    fail "nginx validation failed; restored $NGINX_BACKUP"
fi

systemctl reload nginx

if ! bash "$SRC_DIR/deploy/check-production.sh"; then
    cp -a "$NGINX_BACKUP" "$DRIPVID_NGINX"
    if nginx -t; then
        systemctl reload nginx
    fi
    fail "production smoke check failed; nginx config restored from $NGINX_BACKUP"
fi

docker image rm "ai-hq-bootstrap:${SHA}" >/dev/null 2>&1 || true

log "production activation complete"
log "AI HQ: https://dripvid.uk/ai-hq"
log "Safe Mode: enabled"
log "Simulation Mode: enabled"
log "nginx backup: $NGINX_BACKUP"
