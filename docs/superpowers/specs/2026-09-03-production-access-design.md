# AI HQ Production Access Design

**Date:** 2026-09-03
**Status:** Approved design
**Repository:** `Waitenomore-ai/ai-hq`
**Production URL:** `https://dripvid.uk/ai-hq`

## 1. Purpose

Deploy AI HQ on the same public domain as DripVid while keeping AI HQ operationally, logically, and credential-wise separate from DripVid.

AI HQ must be available at `https://dripvid.uk/ai-hq` and protected by its own administrator login and session system.

DripVid remains served independently and must not share AI HQ credentials, database state, Redis state, or application secrets.

## 2. Existing DripVid production model used as reference

The current DripVid deployment provides several conventions that AI HQ will reuse conceptually:

- Nginx terminates public HTTP routing for `dripvid.uk`.
- DripVid's application is proxied to `127.0.0.1:3000`.
- Application files live under `/opt/dripvid`.
- Production environment secrets live outside GitHub under `/etc/dripvid/`.
- Deployments use versioned release directories and a stable application symlink.
- Deployments perform readiness checks and automatically roll back when a new release fails readiness.

AI HQ must mirror these safety properties without depending on DripVid's runtime or secrets.

## 3. Production topology

Public request flow:

`Internet -> dripvid.uk -> Nginx -> /ai-hq -> AI HQ localhost port -> AI HQ Docker Compose stack`

DripVid continues using its existing catch-all routing to `127.0.0.1:3000`.

Nginx must define a more-specific `/ai-hq/` location before the existing `/` location so requests to AI HQ are not forwarded to DripVid.

AI HQ is deployed under:

`/opt/ai-hq/`

Recommended structure:

- `/opt/ai-hq/releases/<git-sha>/` — immutable release directories
- `/opt/ai-hq/app` — symlink to active release
- `/opt/ai-hq/data/` — persistent runtime data where needed
- `/etc/ai-hq/ai-hq.env` — production secrets and configuration

The AI HQ Docker Compose stack remains separate from DripVid and uses its own Docker network.

## 4. Public path handling

AI HQ must operate correctly under the URL prefix `/ai-hq` rather than assuming it is mounted at `/`.

The application must use an explicit configurable root path:

`AI_HQ_ROOT_PATH=/ai-hq`

All application-generated routes, redirects, static asset paths, login URLs, logout URLs, and API paths must work under this prefix.

Nginx must preserve forwarded scheme, host, client IP, and prefix information needed by the application.

The internal AI HQ service must only bind to localhost or an otherwise non-public interface. The Docker-published web port must not be exposed directly to the internet.

## 5. Authentication boundary

AI HQ must use its own authentication system.

It must not reuse:

- DripVid `ADMIN_PASSWORD`
- DripVid session cookies
- DripVid database users or sessions
- DripVid Jellyfin authentication

AI HQ production uses these dedicated secret values:

- `AI_HQ_ADMIN_PASSWORD_HASH`
- `AI_HQ_SESSION_SECRET`

The plaintext administrator password must not be stored in GitHub, source files, Docker images, logs, database rows, or deployment artifacts.

The recommended bootstrap flow is:

1. administrator chooses an AI HQ password
2. deployment tooling generates a password hash locally on the server
3. only the hash is stored in `/etc/ai-hq/ai-hq.env`
4. login compares the submitted password against the stored hash

Production startup must refuse to run if the password hash or session secret is missing or invalid.

## 6. Login and session behaviour

Public unauthenticated requests to protected AI HQ pages must redirect to:

`/ai-hq/login`

The login page accepts the AI HQ administrator password.

Successful authentication creates an authenticated server-validated session.

The browser cookie must use:

- `HttpOnly`
- `Secure` in production
- `SameSite=Lax` or stricter unless a future integration explicitly requires otherwise
- cookie path `/ai-hq`

Sessions must expire after a configurable period. Default maximum session lifetime for Phase 1 is 12 hours.

Logout invalidates the active session and clears the browser cookie.

The login endpoint must use timing-safe password verification through a well-maintained password hashing implementation such as Argon2 or bcrypt.

Repeated failed login attempts must be rate limited.

## 7. Authentication scope

Authentication protects all interactive AI HQ application pages and privileged APIs.

The following endpoints remain unauthenticated for infrastructure health checking only:

- `/ai-hq/health/live`
- `/ai-hq/health/ready`

Health responses must never expose secrets, configuration values, database URLs, Redis URLs, stack traces, or administrator/session state.

No other privileged endpoint may bypass authentication merely because it originates from localhost or another container.

Internal service-to-service authorization remains a separate future capability and must not be implemented by reusing the browser administrator session.

## 8. Secret storage

AI HQ secrets live in:

`/etc/ai-hq/ai-hq.env`

Recommended permissions:

- owner: dedicated AI HQ service/deployment account or root as appropriate
- mode: `600` or `640` with the smallest required group access

GitHub stores only placeholder variable names in `.env.example`.

The environment file may contain references such as:

- PostgreSQL credentials
- Redis connection configuration
- AI HQ password hash
- session secret
- future AI provider credentials
- future Gmail/Google Calendar OAuth credentials

Secrets must be redacted from logs and diagnostic output.

## 9. Database and Redis isolation

AI HQ uses its own PostgreSQL database and Redis namespace/service.

It must not write to the DripVid database.

Preferred PostgreSQL arrangement on the existing server is a dedicated AI HQ database and database role, whether PostgreSQL itself runs in the AI HQ Compose stack or is later moved to a shared host-level PostgreSQL service.

Phase 1 Compose remains authoritative unless deployment constraints require a later reviewed architecture change.

Redis state remains non-authoritative and disposable. Durable mission, session metadata where applicable, approval, memory, and audit state remains in PostgreSQL.

## 10. Nginx routing

The DripVid Nginx server block must add a specific AI HQ route before the existing catch-all route.

Conceptual routing:

```nginx
location = /ai-hq {
    return 301 /ai-hq/;
}

location /ai-hq/ {
    proxy_pass http://127.0.0.1:<AI_HQ_PORT>;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /ai-hq;
}
```

The final internal port is an AI HQ deployment setting and must not conflict with DripVid port `3000`, Jellyfin, qBittorrent, or other existing host services.

The chosen port must bind only to `127.0.0.1` at the host boundary.

## 11. Deployment model

AI HQ should follow a versioned release model similar to DripVid.

Deployment steps:

1. package the tested Git commit
2. transfer or fetch the release onto the server
3. unpack into `/opt/ai-hq/releases/<sha>`
4. validate required files and production configuration
5. build/start the release's Docker Compose services
6. run database migrations
7. wait for `/health/ready`
8. atomically update `/opt/ai-hq/app` to the new release
9. route/reload Nginx only after configuration validation
10. run production smoke checks through `https://dripvid.uk/ai-hq`
11. keep a limited number of previous releases for rollback

A failed readiness or smoke check must leave or restore the previous known-good release.

Deployments must never modify DripVid's active release symlink, DripVid environment file, or DripVid service configuration except for the deliberate Nginx `/ai-hq` routing addition.

## 12. Nginx change safety

Before applying an Nginx change:

- render or install the candidate configuration
- run `nginx -t`
- do not reload Nginx unless validation succeeds

After reload:

- verify DripVid root pages still respond
- verify AI HQ `/ai-hq/login` responds
- verify AI HQ health endpoints respond

If AI HQ routing fails, restore the previous Nginx config and reload the validated previous configuration.

## 13. Production modes

The first production deployment must retain AI HQ's existing safe defaults:

- operating mode: `SAFE`
- simulation mode: enabled

Making AI HQ publicly reachable behind administrator authentication does not enable autonomous mutating actions.

Promotion from simulation to real execution remains capability-by-capability and follows the Phase 1 approval model.

## 14. Brute-force and session protections

The initial admin login must include rate limiting.

Minimum behaviour:

- count failed attempts per client identity with a bounded time window
- delay or temporarily reject excessive failures
- never reveal whether a specific internal account record exists
- return a generic invalid-credentials response
- record security-relevant failures without logging submitted passwords

Phase 1 remains a single-admin system, but the implementation must avoid making later multi-admin support impossible.

## 15. CSRF and request safety

State-changing browser requests must receive CSRF protection appropriate to the chosen session framework.

Authentication cookies alone must not be considered sufficient CSRF protection.

Login, logout, and future approval/actions interfaces must reject malformed or cross-origin mutation requests according to policy.

## 16. Testing requirements

Automated tests must cover at minimum:

- production refuses missing AI HQ admin password hash
- production refuses missing/weak session secret
- successful admin authentication
- incorrect password rejection
- login rate limiting
- protected-page redirect to `/ai-hq/login`
- authenticated protected-page access
- logout invalidation
- secure cookie attributes in production
- cookie path `/ai-hq`
- health endpoints remain unauthenticated
- privileged API endpoints remain authenticated
- root-path-aware redirects and route generation
- Compose publishes the AI HQ web service only on localhost
- Nginx candidate configuration contains a more-specific `/ai-hq/` route before the DripVid `/` route
- deployment scripts validate readiness and preserve rollback behaviour

CI must continue to run lint, unit/integration tests, and Compose validation.

## 17. Production verification

A production deployment is not considered successful until all of the following are true:

- `https://dripvid.uk/` still serves DripVid
- `https://dripvid.uk/ai-hq` redirects or resolves correctly to AI HQ
- unauthenticated access reaches AI HQ login rather than DripVid
- valid AI HQ credentials establish an authenticated session
- invalid credentials do not authenticate
- logout invalidates the session
- `/ai-hq/health/live` succeeds
- `/ai-hq/health/ready` succeeds
- AI HQ remains in Safe Mode with Simulation Mode enabled
- the AI HQ web port is not directly reachable publicly

## 18. Explicit non-goals for this slice

This production-access slice does not implement:

- DripVid single sign-on
- shared passwords
- public AI HQ registration
- multiple administrator accounts
- MFA
- Cloudflare Access
- OAuth login
- Gmail/Calendar integration
- Mission Engine behaviour
- privileged SysAdmin Broker actions

Those features require their own reviewed implementation slices.

## 19. Security invariant

Compromise of the DripVid administrator password alone must not grant AI HQ access.

Compromise of the AI HQ administrator password alone must not grant DripVid administrator access.

The two systems share a public domain and host infrastructure, but their application authentication and secrets remain independent.
