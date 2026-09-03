# AI HQ Phase 1 Foundation Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the production-ready technical foundation for AI HQ so later mission, approval, agent, knowledge, and integration features can be added on a stable, testable base.

**Architecture:** Start with a modular Python backend using FastAPI, SQLAlchemy 2 and Alembic, backed by PostgreSQL and Redis and packaged as an isolated Docker Compose stack. Keep the first slice intentionally small: one web/API service, one worker process, shared configuration and health infrastructure, with clear module boundaries ready for later mission and tool-gateway packages.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, psycopg 3, redis-py, Pydantic Settings, pytest, pytest-asyncio, HTTPX, Docker Compose, PostgreSQL 16, Redis 7.

**Spec:** `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md`

## Global Constraints

- AI HQ remains a separate repository and Docker Compose stack from DripVid.
- Durable mission/application state belongs in PostgreSQL; Redis is only for queues, transient coordination and caching.
- The web UI is never the source of truth for operational state.
- Credentials and secrets must never be committed to the repository.
- All future real-world integrations must pass through a permissioned Tool Gateway.
- If authorization is unavailable, execution must default to deny.
- The architecture must support Normal, Safe Mode and Freeze operating modes.
- The platform must remain multi-user-ready even though Phase 1 targets one primary user.
- No agent worker receives unrestricted root or Docker-socket access.

---

### Task 1: Python project skeleton and configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/ai_hq/__init__.py`
- Create: `src/ai_hq/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: environment variables only.
- Produces: `get_settings() -> Settings` with `environment`, `database_url`, `redis_url`, `operating_mode`, `simulation_mode` and `log_level`.

- [ ] **Step 1: Write the failing configuration tests**

```python
from ai_hq.config import OperatingMode, Settings


def test_settings_defaults_are_safe():
    settings = Settings(database_url="postgresql+psycopg://u:p@db/hq", redis_url="redis://redis:6379/0")
    assert settings.operating_mode is OperatingMode.SAFE
    assert settings.simulation_mode is True
    assert settings.environment == "development"


def test_freeze_mode_is_accepted():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
        operating_mode="freeze",
    )
    assert settings.operating_mode is OperatingMode.FREEZE
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because `ai_hq.config` does not exist.

- [ ] **Step 3: Implement the minimal configuration module and packaging**

`pyproject.toml` must define Python `>=3.12`, installable package source under `src`, runtime dependencies `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `redis`, `pydantic-settings`, and dev dependencies `pytest`, `pytest-asyncio`, `httpx`, `ruff`.

`src/ai_hq/config.py`:

```python
from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class OperatingMode(StrEnum):
    NORMAL = "normal"
    SAFE = "safe"
    FREEZE = "freeze"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_HQ_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    redis_url: str
    operating_mode: OperatingMode = OperatingMode.SAFE
    simulation_mode: bool = True
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`.env.example` must contain only non-secret examples and safe defaults.

- [ ] **Step 4: Run the tests and lint**

Run: `python -m pytest tests/test_config.py -q && python -m ruff check src tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore .env.example src tests
git commit -m "feat: bootstrap AI HQ Python foundation"
```

---

### Task 2: Database engine, session boundary and initial schema

**Files:**
- Create: `src/ai_hq/db.py`
- Create: `src/ai_hq/models/__init__.py`
- Create: `src/ai_hq/models/system_state.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_system_state.py`
- Create: `tests/test_system_state.py`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: `Base`, `get_engine()`, `get_session_factory()`, and `SystemState` with durable operating/simulation state.

- [ ] **Step 1: Write the failing model test**

```python
from ai_hq.config import OperatingMode
from ai_hq.models.system_state import SystemState


def test_system_state_defaults_to_safe_simulation():
    state = SystemState()
    assert state.operating_mode == OperatingMode.SAFE.value
    assert state.simulation_mode is True
```

- [ ] **Step 2: Run the model test and verify it fails**

Run: `python -m pytest tests/test_system_state.py -q`
Expected: FAIL because the model does not exist.

- [ ] **Step 3: Implement the database boundary and initial model**

`SystemState` must use a stable singleton key (`id=1`), store `operating_mode`, `simulation_mode`, `created_at`, and `updated_at`, and default to safe mode with simulation enabled. Database engine/session construction must be isolated in `db.py` so tests and later workers can replace it cleanly.

- [ ] **Step 4: Add Alembic migration 0001**

Create the `system_state` table with database-level defaults matching the model. The downgrade removes only that table.

- [ ] **Step 5: Run tests and migration syntax checks**

Run: `python -m pytest tests/test_system_state.py -q && python -m compileall src migrations`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_hq/db.py src/ai_hq/models alembic.ini migrations tests/test_system_state.py
git commit -m "feat: add AI HQ database foundation"
```

---

### Task 3: FastAPI application and health endpoints

**Files:**
- Create: `src/ai_hq/app.py`
- Create: `src/ai_hq/health.py`
- Create: `tests/test_health.py`

**Interfaces:**
- Consumes: settings, database session factory and Redis URL.
- Produces: `create_app() -> FastAPI`, `GET /health/live`, and `GET /health/ready`.

- [ ] **Step 1: Write failing API tests**

```python
from fastapi.testclient import TestClient
from ai_hq.app import create_app


def test_liveness_is_process_only():
    client = TestClient(create_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Add a readiness test that overrides dependency probes and expects JSON containing `status`, `database`, and `redis`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_health.py -q`
Expected: FAIL because the application module does not exist.

- [ ] **Step 3: Implement app factory and probe functions**

Liveness must never depend on PostgreSQL or Redis. Readiness must check both dependencies independently and return HTTP 503 if either is unavailable, without leaking credentials or raw connection strings.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_health.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/app.py src/ai_hq/health.py tests/test_health.py
git commit -m "feat: add AI HQ health API"
```

---

### Task 4: Worker runtime and queue connectivity

**Files:**
- Create: `src/ai_hq/worker.py`
- Create: `src/ai_hq/queue.py`
- Create: `tests/test_worker.py`

**Interfaces:**
- Consumes: `Settings.redis_url`, `OperatingMode`.
- Produces: a worker startup check and `execution_allowed(mode: OperatingMode) -> bool` guard that blocks work in Freeze mode.

- [ ] **Step 1: Write failing safety tests**

```python
from ai_hq.config import OperatingMode
from ai_hq.worker import execution_allowed


def test_freeze_mode_blocks_worker_execution():
    assert execution_allowed(OperatingMode.FREEZE) is False


def test_safe_mode_allows_read_only_worker_loop():
    assert execution_allowed(OperatingMode.SAFE) is True
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_worker.py -q`
Expected: FAIL because the worker module does not exist.

- [ ] **Step 3: Implement minimal worker runtime**

The worker must establish Redis connectivity, report startup status, refuse to consume new jobs in Freeze mode, and contain no arbitrary command execution or Docker access. Keep actual mission execution out of this slice.

- [ ] **Step 4: Run worker tests**

Run: `python -m pytest tests/test_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/queue.py src/ai_hq/worker.py tests/test_worker.py
git commit -m "feat: add guarded AI HQ worker runtime"
```

---

### Task 5: Isolated Docker Compose stack

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `docker/entrypoint-web.sh`
- Create: `docker/entrypoint-worker.sh`
- Create: `tests/test_compose_contract.py`

**Interfaces:**
- Consumes: environment values defined by `.env` on the server.
- Produces: services `web`, `worker`, `postgres`, and `redis` on an AI-HQ-only network.

- [ ] **Step 1: Write failing Compose contract tests**

Use Python/YAML parsing to assert the stack contains exactly the required core services, that only the `web` service exposes an application port, that PostgreSQL and Redis use named volumes where persistence is required, and that neither `web` nor `worker` mounts `/var/run/docker.sock`.

- [ ] **Step 2: Run the contract test and verify failure**

Run: `python -m pytest tests/test_compose_contract.py -q`
Expected: FAIL because `compose.yaml` does not exist.

- [ ] **Step 3: Implement Dockerfile, entrypoints and Compose stack**

The web entrypoint runs `alembic upgrade head` before starting Uvicorn. The worker waits for its dependencies then starts the guarded worker process. Add container health checks. Do not embed passwords in Compose; consume them from environment variables.

- [ ] **Step 4: Validate the stack**

Run: `docker compose config && python -m pytest tests/test_compose_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile compose.yaml docker tests/test_compose_contract.py
git commit -m "feat: add isolated AI HQ compose stack"
```

---

### Task 6: Developer commands, CI and foundation acceptance test

**Files:**
- Create: `Makefile`
- Create: `.github/workflows/ci.yml`
- Create: `README.md`
- Create: `tests/test_foundation_contract.py`

**Interfaces:**
- Consumes: all foundation components from Tasks 1-5.
- Produces: repeatable `make test`, `make lint`, `make up`, `make down`, and CI validation on pushes/PRs.

- [ ] **Step 1: Write the failing foundation contract test**

The test must import `create_app`, confirm safe defaults, confirm Freeze blocks worker execution, and verify both health routes are registered. This is deliberately dependency-light so it runs in CI without requiring the full production stack.

- [ ] **Step 2: Run it and verify current gaps fail**

Run: `python -m pytest tests/test_foundation_contract.py -q`
Expected: FAIL until all required interfaces are wired consistently.

- [ ] **Step 3: Add Makefile, CI workflow and README**

CI must install the project with dev dependencies, run Ruff, run pytest, and validate `docker compose config`. README must document local bootstrap, safe defaults, architecture boundaries, and the rule that `.env` is never committed.

- [ ] **Step 4: Run the complete foundation verification**

Run: `python -m ruff check src tests && python -m pytest -q && docker compose config`
Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add Makefile .github/workflows/ci.yml README.md tests/test_foundation_contract.py
git commit -m "ci: verify AI HQ foundation bootstrap"
```

---

## Foundation completion gate

The Foundation Bootstrap slice is complete only when:

1. The full pytest suite passes.
2. Ruff passes with no errors.
3. `docker compose config` validates.
4. The web service starts with PostgreSQL and Redis available.
5. `/health/live` returns HTTP 200.
6. `/health/ready` returns HTTP 200 only when PostgreSQL and Redis are reachable.
7. Safe Mode and Simulation Mode are the default configuration.
8. Freeze mode prevents workers from consuming new work.
9. No repository file contains real credentials.
10. No AI HQ web/worker container has unrestricted Docker socket or root-host access.

After this gate passes, the next implementation slice is **Mission Engine + Agents + Operations Ledger**, followed by **Approval/Safety Engine**, **Knowledge Core**, and then the Phase 1 integrations.