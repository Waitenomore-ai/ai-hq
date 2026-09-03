# AI HQ Production Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI HQ production-ready at `https://dripvid.uk/ai-hq` with a dedicated admin password, server-validated sessions, CSRF protection, rate-limited login, localhost-only exposure, and rollback-capable deployment assets.

**Architecture:** Keep the existing FastAPI/PostgreSQL/Redis/Docker foundation. Add a dedicated authentication boundary inside AI HQ, store only a password hash in `/etc/ai-hq/ai-hq.env`, persist administrator sessions in PostgreSQL, use Redis for bounded login-attempt rate limiting, and configure FastAPI for the `/ai-hq` root path. Nginx remains the public router and sends only `/ai-hq/` to AI HQ on `127.0.0.1:8090`; DripVid remains on its existing `127.0.0.1:3000` route.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, Argon2, Jinja2, Docker Compose, Nginx, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-production-access-design.md`

## Global Constraints

- Production URL is exactly `https://dripvid.uk/ai-hq`.
- AI HQ must never reuse DripVid `ADMIN_PASSWORD`, sessions, database authentication, or Jellyfin authentication.
- Production secrets live outside GitHub in `/etc/ai-hq/ai-hq.env`.
- Store `AI_HQ_ADMIN_PASSWORD_HASH`, never the plaintext AI HQ password.
- Production startup fails closed if the admin password hash or session secret is missing or invalid.
- AI HQ web exposure remains localhost-only at host port `8090` unless a separately reviewed architecture change changes that port.
- First production launch remains `SAFE` with simulation mode enabled.
- `/health/live` and `/health/ready` stay unauthenticated; interactive pages and privileged APIs require authentication.
- Browser session cookie is HttpOnly, Secure in production, SameSite=Lax, and scoped to `/ai-hq`.
- Default maximum session lifetime is 12 hours.
- State-changing browser requests require CSRF validation.
- Login failures are rate-limited and never log submitted passwords.
- Nginx configuration must be validated with `nginx -t` before reload.
- Production deployment must support readiness checks and rollback.

---

### Task 1: Production authentication configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/ai_hq/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces `Settings.root_path: str`, `Settings.admin_password_hash: str | None`, `Settings.session_secret: str | None`, `Settings.session_lifetime_hours: int`, and `Settings.is_production`.
- Production validation must reject missing password hash, missing/short session secret, unsafe operating mode defaults, or disabled simulation defaults when constructing production settings.

- [ ] Add failing tests constructing production `Settings` without `AI_HQ_ADMIN_PASSWORD_HASH` and assert validation fails.
- [ ] Add failing tests constructing production `Settings` with a session secret shorter than 32 characters and assert validation fails.
- [ ] Add failing test asserting default `root_path == "/ai-hq"` and default session lifetime is 12 hours.
- [ ] Add runtime dependencies `argon2-cffi>=23,<26`, `jinja2>=3.1,<4`, and `python-multipart>=0.0.20,<1`.
- [ ] Implement settings fields and a model-level production validator.
- [ ] Keep development usable with unset auth secrets, but never let `environment=production` validate without them.
- [ ] Update `.env.example` with placeholders for root path, password hash, session secret, and session lifetime.
- [ ] Run `pytest tests/test_config.py -q` and `python -m ruff check src tests`.
- [ ] Commit as `feat: add production authentication settings`.

### Task 2: Password verification and session persistence

**Files:**
- Create: `src/ai_hq/auth/passwords.py`
- Create: `src/ai_hq/auth/sessions.py`
- Create: `src/ai_hq/auth/__init__.py`
- Create: `src/ai_hq/models/admin_session.py`
- Modify: `src/ai_hq/models/__init__.py`
- Create: `migrations/versions/0002_admin_sessions.py`
- Test: `tests/test_auth_passwords.py`
- Test: `tests/test_auth_sessions.py`

**Interfaces:**
- `verify_password(password: str, encoded_hash: str) -> bool` uses Argon2 and returns False on malformed hashes.
- `create_session(session, *, lifetime_hours: int) -> tuple[str, AdminSession]` generates a high-entropy bearer token, stores only its SHA-256 digest, and generates a separate CSRF token.
- `resolve_session(session, token: str) -> AdminSession | None` checks digest, expiry, and revocation.
- `revoke_session(session, token: str) -> bool` marks the matching session revoked.

- [ ] Write password tests using an Argon2-generated test hash; correct password passes and incorrect/malformed hash fails.
- [ ] Write session tests against SQLite verifying raw bearer token is not stored, valid token resolves, expired token does not resolve, and revoked token does not resolve.
- [ ] Implement `AdminSession` with `id`, `token_digest`, `csrf_token`, `created_at`, `expires_at`, and `revoked_at`.
- [ ] Add Alembic migration creating `admin_sessions`, unique index on `token_digest`, and expiry index.
- [ ] Implement session helpers using `secrets.token_urlsafe(48)`, SHA-256 token digest, UTC timestamps, and constant-time digest comparison where applicable.
- [ ] Run `pytest tests/test_auth_passwords.py tests/test_auth_sessions.py -q` and Ruff.
- [ ] Commit as `feat: add admin password and session primitives`.

### Task 3: Redis-backed login rate limiting

**Files:**
- Create: `src/ai_hq/auth/rate_limit.py`
- Test: `tests/test_login_rate_limit.py`

**Interfaces:**
- `LoginRateLimiter(redis_client, *, max_attempts=5, window_seconds=900)`.
- `is_blocked(identity: str) -> bool` returns true at or above threshold.
- `record_failure(identity: str) -> None` increments with a bounded TTL.
- `clear(identity: str) -> None` removes failure state after successful login.
- Redis failures fail closed for login attempts in production-facing route handling but do not affect health endpoints.

- [ ] Add tests with a small fake Redis implementation verifying threshold, TTL establishment, and clearing after success.
- [ ] Implement namespaced keys using `ai-hq:auth:failed:<sha256(identity)>` so raw client identifiers are not stored in Redis keys.
- [ ] Ensure no password values enter keys or logs.
- [ ] Run targeted tests and Ruff.
- [ ] Commit as `feat: rate limit AI HQ admin login`.

### Task 4: Root-path-aware admin login, protected home, logout, and CSRF

**Files:**
- Create: `src/ai_hq/auth/dependencies.py`
- Create: `src/ai_hq/web.py`
- Create: `src/ai_hq/templates/login.html`
- Create: `src/ai_hq/templates/home.html`
- Modify: `src/ai_hq/app.py`
- Modify: `pyproject.toml` package-data configuration if required for templates
- Test: `tests/test_web_auth.py`

**Interfaces:**
- Session cookie name: `ai_hq_session`.
- Login GET: `/login` renders a password-only form.
- Login POST: `/login` checks CSRF-origin policy for login, rate limit, Argon2 password verification, creates DB session, then redirects to root path `/ai-hq/` externally.
- Home GET: `/` requires valid admin session.
- Logout POST: `/logout` requires valid admin session and matching CSRF token, revokes the session, clears cookie, redirects to login.
- Protected API example: `/api/session` returns minimal authenticated session metadata and proves privileged API enforcement.

- [ ] Add TestClient tests showing unauthenticated `/` redirects to `/ai-hq/login`.
- [ ] Add successful login test with a generated Argon2 hash and SQLite DB override; assert 303 redirect and cookie attributes include HttpOnly, SameSite=Lax, Path=/ai-hq, and Secure in production.
- [ ] Add incorrect-password test returning generic invalid-credentials content with no hash/password disclosure.
- [ ] Add authenticated home test using issued cookie.
- [ ] Add logout test requiring CSRF, revoking the DB session, and clearing cookie.
- [ ] Add test proving health endpoints remain accessible without a cookie.
- [ ] Add test proving `/api/session` rejects unauthenticated access.
- [ ] Configure `FastAPI(root_path=settings.root_path)` without double-prefixing internal route declarations.
- [ ] Use Jinja templates with all generated form actions/links rooted under the configured external root path.
- [ ] Validate `Origin`/`Host` on login POST in production and require session CSRF token on logout/future authenticated mutations.
- [ ] Run targeted tests, full pytest, and Ruff.
- [ ] Commit as `feat: add AI HQ admin login boundary`.

### Task 5: Localhost-only Compose and production environment contract

**Files:**
- Modify: `compose.yaml`
- Modify: `tests/test_compose_contract.py`
- Modify: `.env.example`

**Interfaces:**
- Web host mapping remains exactly `127.0.0.1:8090:8000`.
- Web/worker receive the same AI HQ environment file.
- Healthcheck continues to address the container-local `/health/live` path because FastAPI `root_path` affects external URL generation rather than internal route matching.

- [ ] Strengthen Compose contract tests to assert no `0.0.0.0` or bare `8090:8000` mapping exists.
- [ ] Assert `AI_HQ_ROOT_PATH=/ai-hq` appears in the environment example.
- [ ] Keep Postgres and Redis without host port publication.
- [ ] Run Compose contract tests and `docker compose config` in CI.
- [ ] Commit as `chore: harden production compose exposure`.

### Task 6: Nginx integration asset for dripvid.uk

**Files:**
- Create: `deploy/nginx-ai-hq-location.conf`
- Create: `deploy/render-nginx.sh`
- Test: `tests/test_nginx_contract.py`

**Interfaces:**
- Exact `/ai-hq` redirects to `/ai-hq/`.
- `/ai-hq/` proxies to `http://127.0.0.1:8090` while preserving Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host, and X-Forwarded-Prefix.
- The asset is designed to be inserted before DripVid's existing `location /` catch-all.

- [ ] Add contract test asserting specific `/ai-hq` blocks exist and target localhost 8090.
- [ ] Add test asserting no DripVid backend port 3000 is modified by the AI HQ snippet.
- [ ] Create a render/install helper that refuses to write outside an explicitly supplied candidate output file and does not reload Nginx itself.
- [ ] Document the required host-side sequence: render candidate, `nginx -t`, install, `nginx -t`, reload.
- [ ] Run tests and ShellCheck when available; CI at minimum runs syntax-oriented contract tests.
- [ ] Commit as `deploy: add dripvid.uk AI HQ nginx route`.

### Task 7: Versioned release deployment and rollback scripts

**Files:**
- Create: `deploy/ai-hq-deploy`
- Create: `deploy/ai-hq.service`
- Create: `deploy/check-production.sh`
- Test: `tests/test_deploy_contract.py`

**Interfaces:**
- Base: `/opt/ai-hq`.
- Releases: `/opt/ai-hq/releases/<sha>`.
- Active symlink: `/opt/ai-hq/app`.
- Production env: `/etc/ai-hq/ai-hq.env`.
- Lock: `/run/lock/ai-hq-deploy.lock`.
- Readiness probe: `http://127.0.0.1:8090/health/ready`.
- External smoke target: `https://dripvid.uk/ai-hq/login`.

- [ ] Add contract tests requiring SHA validation, deployment lock, env-file presence, versioned releases, atomic symlink update, readiness loop, previous-release capture, rollback path, and limited release retention.
- [ ] Implement deployment script that validates required files, copies the external env file to a release-local non-repository runtime location or passes it explicitly to Compose, starts migrations/services, waits for readiness, updates the active symlink atomically, and rolls back on failure.
- [ ] Ensure script never touches `/opt/dripvid/app` or `/etc/dripvid/dripvid.env`.
- [ ] Add production check script that verifies DripVid root, AI HQ login, AI HQ liveness/readiness, and localhost port binding without printing secrets.
- [ ] Add a small systemd oneshot/service wrapper only if needed for boot-time Compose restoration; keep Docker restart policies authoritative for container restart.
- [ ] Run deployment contract tests and Ruff.
- [ ] Commit as `deploy: add AI HQ versioned release workflow`.

### Task 8: Password bootstrap utility

**Files:**
- Create: `src/ai_hq/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`

**Interfaces:**
- Console command `ai-hq hash-admin-password` reads a password from a no-echo prompt twice and prints only an Argon2 encoded hash.
- Command rejects mismatched or shorter-than-12-character passwords.
- It never writes the plaintext password to disk or logs.

- [ ] Add tests by monkeypatching `getpass.getpass` and capturing stdout.
- [ ] Implement the command and register `[project.scripts] ai-hq = "ai_hq.cli:main"`.
- [ ] Add README instructions showing `sudo -u <deployment-user> ai-hq hash-admin-password` and storing only the printed hash in `/etc/ai-hq/ai-hq.env`.
- [ ] Run CLI tests and Ruff.
- [ ] Commit as `feat: add AI HQ admin password bootstrap utility`.

### Task 9: CI and full acceptance gate

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Test: all tests

**Interfaces:**
- CI sequence: install -> Ruff -> pytest -> `docker compose config` -> deployment/Nginx contract tests included in pytest.
- Production documentation must explicitly state that live deployment needs server access and a newly chosen AI HQ admin password; neither credential belongs in GitHub.

- [ ] Run `python -m ruff check src tests`.
- [ ] Run `pytest -q` and require zero failures.
- [ ] Run `docker compose config` in GitHub Actions.
- [ ] Verify branch diff contains no plaintext password, DripVid secret, SSH key, or production environment value.
- [ ] Verify `main` is unchanged until CI is green.
- [ ] Commit as `ci: verify AI HQ production access boundary`.

## Production Deployment Gate

Implementation and CI may complete without production credentials. Live activation must stop until the server has:

1. `/etc/ai-hq/ai-hq.env` with a newly generated AI HQ admin password hash and session secret.
2. A dedicated AI HQ PostgreSQL password if Compose variables require one.
3. Permission to install/validate the Nginx `/ai-hq` route.
4. Permission to create/manage `/opt/ai-hq` and run Docker Compose.

Once those exist, deployment may proceed through the versioned release script. No existing DripVid password should ever be requested or copied into AI HQ.