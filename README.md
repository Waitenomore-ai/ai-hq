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

## Safety defaults

AI HQ starts in **Safe Mode** with **Simulation Mode enabled**. Freeze mode prevents workers from consuming new work. Web and worker containers do not receive the host Docker socket or unrestricted host/root access.

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

## Repository rules

- Never commit `.env` or real credentials.
- PostgreSQL owns durable application state.
- Redis is transient coordination/cache/queue infrastructure, not the durable mission record.
- All future external actions must pass through the Tool Gateway and approval policy.
- AI workers must not receive unrestricted root shell or Docker socket access.
- DripVid remains a separate application/stack; integration is explicit and permissioned.

See `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md` for the approved Phase 1 design.
