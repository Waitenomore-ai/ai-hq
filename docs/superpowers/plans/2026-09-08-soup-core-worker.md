# Soup Core Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install `soup-cli==0.74.0` in the AI HQ worker image only while keeping the web image free of Soup and preserving all current security boundaries.

**Architecture:** Convert the existing single-stage Dockerfile into a shared `base` stage plus explicit `web` and `worker` targets. The worker target alone installs the pinned Soup light-core package; Compose selects the correct target for each service. Static regression tests enforce the image split and ensure no Soup MCP/training/runtime authority is introduced.

**Tech Stack:** Docker multi-stage builds, Docker Compose, Python 3.12, pytest, `soup-cli==0.74.0`.

**Spec:** `docs/superpowers/specs/2026-09-08-soup-core-worker-design.md`

## Global Constraints

- Soup version is pinned exactly to `0.74.0`.
- Install only the light `soup-cli` core; do not install `[train]`, `[all]`, `[mcp]`, GPU libraries, or model weights.
- Soup must exist in the worker image only, not the web image.
- Do not add Soup MCP, shell, restart, deployment, filesystem-write, or arbitrary execution authority.
- Keep Host Helper and DripVid MCP mounts/secrets/permissions unchanged.
- Production deployment remains a separate explicit action after merge and verification.

---

### Task 1: Add worker-only build contract tests

**Files:**
- Create: `tests/test_soup_worker_image.py`

**Interfaces:**
- Consumes: repository `Dockerfile` and `compose.yaml` as text.
- Produces: regression contract proving `web` and `worker` select separate Docker targets and Soup is pinned only in the worker stage.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()


def test_soup_is_pinned_in_worker_stage_only():
    assert "FROM base AS web" in DOCKERFILE
    assert "FROM base AS worker" in DOCKERFILE
    web_stage, worker_stage = DOCKERFILE.split("FROM base AS worker", 1)
    assert "soup-cli" not in web_stage
    assert 'pip install --no-cache-dir "soup-cli==0.74.0"' in worker_stage
    assert "soup-cli[" not in DOCKERFILE


def test_compose_selects_explicit_web_and_worker_targets():
    assert "target: web" in COMPOSE
    assert "target: worker" in COMPOSE
    assert COMPOSE.index("target: web") < COMPOSE.index("worker:")
    assert COMPOSE.index("target: worker") > COMPOSE.index("worker:")


def test_soup_install_does_not_add_runtime_authority():
    lowered = (DOCKERFILE + "\n" + COMPOSE).lower()
    assert "soup mcp" not in lowered
    assert "--allow-execute" not in lowered
    assert "soup-cli[train" not in lowered
    assert "soup-cli[all" not in lowered
```

- [ ] **Step 2: Run tests to verify RED**

Run: `pytest tests/test_soup_worker_image.py -q`

Expected: FAIL because the current Dockerfile has no `base`, `web`, or `worker` build stages and Compose does not select build targets.

- [ ] **Step 3: Commit the RED contract**

```bash
git add tests/test_soup_worker_image.py
git commit -m "test: require worker-only Soup image"
```

---

### Task 2: Implement the worker-only Soup image split

**Files:**
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Test: `tests/test_soup_worker_image.py`

**Interfaces:**
- Consumes: Task 1 regression contract.
- Produces: Docker build targets `web` and `worker`; worker contains `soup-cli==0.74.0`, web does not.

- [ ] **Step 1: Replace the Dockerfile with explicit shared and service stages**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md* ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker ./docker
RUN pip install --no-cache-dir .
RUN chmod +x /app/docker/entrypoint-web.sh /app/docker/entrypoint-worker.sh

FROM base AS web
CMD ["/app/docker/entrypoint-web.sh"]

FROM base AS worker
RUN pip install --no-cache-dir "soup-cli==0.74.0"
CMD ["/app/docker/entrypoint-worker.sh"]
```

- [ ] **Step 2: Make Compose select the appropriate build target**

Set `web.build` to:

```yaml
build:
  context: .
  target: web
```

Set `worker.build` to:

```yaml
build:
  context: .
  target: worker
```

Leave all current worker-only volumes, secrets, networks, commands, and service dependencies unchanged.

- [ ] **Step 3: Run focused tests to verify GREEN**

Run: `pytest tests/test_soup_worker_image.py -q`

Expected: PASS.

- [ ] **Step 4: Run complete verification**

Run:

```bash
ruff check .
pytest -q
docker compose -f compose.yaml config >/dev/null
```

Expected: all commands exit 0.

- [ ] **Step 5: Build both targets as an image-level smoke test**

Run:

```bash
docker build --target web -t ai-hq-soup-test-web .
docker build --target worker -t ai-hq-soup-test-worker .
docker run --rm ai-hq-soup-test-worker soup --help >/dev/null
if docker run --rm ai-hq-soup-test-web sh -c 'command -v soup >/dev/null'; then exit 1; fi
```

Expected: worker Soup CLI succeeds; web image has no `soup` executable.

- [ ] **Step 6: Commit implementation**

```bash
git add Dockerfile compose.yaml tests/test_soup_worker_image.py
git commit -m "feat: add Soup core to AI HQ worker"
```
