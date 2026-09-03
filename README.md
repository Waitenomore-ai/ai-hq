# AI HQ

AI HQ is a personal AI operations system built as an isolated service stack. Phase 1 starts with the Commander, Communications, Calendar and SysAdmin departments, backed by shared mission, approval, knowledge, audit and tool-gateway foundations.

## Current implementation

The repository is currently building the Phase 1 foundation:

- FastAPI application shell
- PostgreSQL system-of-record foundation
- Redis coordination/queue foundation
- guarded worker runtime
- Safe / Normal / Freeze operating modes
- Simulation Mode enabled by default
- liveness and readiness endpoints
- isolated Docker Compose stack
- dedicated AI HQ administrator authentication
- Argon2 password verification with no plaintext password storage
- PostgreSQL-backed administrator sessions with CSRF protection
- Redis-backed login rate limiting
- production routing contract for `https://dripvid.uk/ai-hq`

## Safety defaults

AI HQ starts in **Safe Mode** with **Simulation Mode enabled**. Freeze mode prevents workers from consuming new work. Web and worker containers do not receive the host Docker socket or unrestricted host/root access.

AI HQ and DripVid have separate administrator credentials. Never copy or reuse the DripVid admin password as the AI HQ password.

## Local bootstrap

```bash
cp .env.example .env
# Replace all example credentials before any non-local deployment.
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make test
make lint
make config
make up
```

The application is exposed on `127.0.0.1:8090` by default. Check:

```bash
curl http://127.0.0.1:8090/health/live
curl http://127.0.0.1:8090/health/ready
```

## Production access

The approved public production address is:

`https://dripvid.uk/ai-hq`

The AI HQ Docker web service remains bound only to `127.0.0.1:8090`. Nginx owns the public `/ai-hq` route and strips the public prefix before proxying requests to FastAPI while forwarding `X-Forwarded-Prefix: /ai-hq`.

Production files are separated from DripVid:

- application releases: `/opt/ai-hq/releases/<git-sha>`
- active release symlink: `/opt/ai-hq/app`
- production environment: `/etc/ai-hq/ai-hq.env`
- DripVid remains under `/opt/dripvid` and `/etc/dripvid`

### Create the separate AI HQ admin password

Install the project tooling, then run:

```bash
ai-hq hash-admin-password
```

The command prompts twice without echoing the password and prints only an Argon2 hash. Put that hash in `/etc/ai-hq/ai-hq.env` as `AI_HQ_ADMIN_PASSWORD_HASH`. Do not store the plaintext password in GitHub or in the environment file.

Generate a separate session secret, for example:

```bash
openssl rand -hex 32
```

Store that value as `AI_HQ_SESSION_SECRET` in `/etc/ai-hq/ai-hq.env`. Production startup refuses missing authentication secrets and requires Safe Mode with Simulation Mode enabled.

### Nginx integration

`deploy/nginx-ai-hq-location.conf` contains the AI HQ route. `deploy/render-nginx.sh` inserts it before DripVid's existing catch-all `location /` into a candidate configuration without modifying or reloading Nginx itself.

A safe host-side workflow is:

```bash
./deploy/render-nginx.sh /etc/nginx/sites-available/dripvid.uk /tmp/dripvid.uk.ai-hq.candidate
# Review the candidate, install it using the server's normal config-management process,
sudo nginx -t
sudo systemctl reload nginx
```

Never reload Nginx if `nginx -t` fails.

### Versioned deployment

`deploy/ai-hq-deploy` accepts an exact Git SHA and `/tmp/ai-hq-release-<sha>.tgz`, deploys it under `/opt/ai-hq/releases`, starts the Compose stack using `/etc/ai-hq/ai-hq.env`, waits for readiness, atomically switches `/opt/ai-hq/app`, and rolls back on readiness failure.

After Nginx routing is active, run:

```bash
./deploy/check-production.sh
```

The production check verifies DripVid still responds, AI HQ login and health endpoints respond, and port 8090 is not publicly bound.

## Repository rules

- Never commit `.env` or real credentials.
- PostgreSQL owns durable application state.
- Redis is transient coordination/cache/queue infrastructure, not the durable mission record.
- All future external actions must pass through the Tool Gateway and approval policy.
- AI workers must not receive unrestricted root shell or Docker socket access.
- DripVid remains a separate application/stack; integration is explicit and permissioned.

See `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md` for the approved Phase 1 design and `docs/superpowers/specs/2026-09-03-production-access-design.md` for the production-access design.
