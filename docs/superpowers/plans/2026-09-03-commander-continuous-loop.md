# Commander Continuous Task Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden AI HQ's existing worker into a production-grade, queue-driven Commander loop that continuously executes trusted queued missions one at a time, obeys durable runtime safety state, and recovers conservatively from worker restarts.

**Architecture:** Keep the existing `worker` container and `DepartmentRunner.run_once()` primitive. Add durable mission/agent recovery helpers, make every polling cycle read PostgreSQL `SystemState`, prevent new work while another mission is `RUNNING`, and fail closed on missing/invalid runtime state. PostgreSQL remains the source of truth; Redis remains only a startup dependency/health gate.

**Tech Stack:** Python 3.13, FastAPI project services, SQLAlchemy, PostgreSQL, Redis health check, pytest, Docker Compose, existing AI HQ Safety Engine / Operations Ledger / Host Helper.

**Spec:** `docs/superpowers/specs/2026-09-03-commander-continuous-loop-design.md`

## Global Constraints

- Queue-driven autonomous execution only; Commander does not create missions.
- One worker process/container and at most one `RUNNING` mission at a time.
- `WAITING_APPROVAL` missions are parked and do not block later queued work.
- Runtime execution authority comes from PostgreSQL `SystemState`, not cached startup settings.
- Missing or invalid runtime state fails closed and executes nothing.
- Interrupted `RUNNING` missions are paused on worker startup and are never automatically replayed.
- No new mutation/write capabilities.
- No arbitrary shell, root access, Docker socket, or new Host Helper authority.
- DripVid is a systemd/log target only, never a Docker target.
- Startup production configuration remains fail-closed.
- Use TDD for every production-code change and keep commits small.

---

### Task 1: Durable mission queries for active and interrupted work

**Files:**
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_missions.py`

**Interfaces:**
- Consumes: existing `Mission`, `MissionStatus`, `SessionFactory`, `MissionService.transition()`.
- Produces: `MissionService.running_missions() -> list[Mission]` and `MissionService.has_running() -> bool`.

- [ ] **Step 1: Write failing tests for running-mission queries**

Add tests that create queued and running missions and assert only `RUNNING` rows are returned, ordered by `created_at` then `id`, and that `has_running()` reflects whether any running mission exists.

```python
def test_running_missions_returns_only_running_in_stable_order(mission_service):
    first = mission_service.create_mission(
        title="first", description="", owner_agent="commander", source="test"
    )
    second = mission_service.create_mission(
        title="second", description="", owner_agent="commander", source="test"
    )
    mission_service.transition(first.id, MissionStatus.RUNNING)

    running = mission_service.running_missions()

    assert [mission.id for mission in running] == [first.id]
    assert mission_service.has_running() is True
    assert second.status is MissionStatus.QUEUED


def test_has_running_is_false_when_no_mission_is_running(mission_service):
    mission_service.create_mission(
        title="queued", description="", owner_agent="commander", source="test"
    )
    assert mission_service.has_running() is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_missions.py -k 'running_missions or has_running' -v
```

Expected: FAIL because `MissionService.running_missions` / `has_running` do not exist.

- [ ] **Step 3: Implement the minimal durable queries**

Add to `MissionService`:

```python
def running_missions(self) -> list[Mission]:
    with self.session_factory() as db:
        return list(
            db.scalars(
                select(Mission)
                .where(Mission.status == MissionStatus.RUNNING)
                .order_by(Mission.created_at, Mission.id)
            )
        )


def has_running(self) -> bool:
    with self.session_factory() as db:
        return (
            db.scalar(
                select(Mission.id)
                .where(Mission.status == MissionStatus.RUNNING)
                .limit(1)
            )
            is not None
        )
```

- [ ] **Step 4: Run focused and mission-service tests**

```bash
pytest tests/test_missions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/missions/service.py tests/test_missions.py
git commit -m "feat: query active missions"
```

---

### Task 2: Reusable stale-agent recovery

**Files:**
- Modify: `src/ai_hq/agents/registry.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `Agent`, `AgentStatus`, existing `AgentRegistry.set_state()`.
- Produces: `AgentRegistry.reset_working(keys: tuple[str, ...]) -> list[Agent]`.

- [ ] **Step 1: Write failing recovery tests**

Add tests proving only requested agents that are currently `WORKING` are reset, `current_mission_id` is cleared, and healthy non-working states are preserved.

```python
def test_reset_working_clears_only_stale_requested_agents(agent_registry):
    agent_registry.ensure_phase1_agents()
    agent_registry.set_state(
        "commander", AgentStatus.WORKING, current_mission_id="mission-1"
    )
    agent_registry.set_state(
        "sysadmin", AgentStatus.IDLE, current_mission_id=None
    )

    reset = agent_registry.reset_working(("commander", "sysadmin"))

    assert [agent.key for agent in reset] == ["commander"]
    commander = agent_registry.get_by_key("commander")
    sysadmin = agent_registry.get_by_key("sysadmin")
    assert commander.status is AgentStatus.IDLE
    assert commander.current_mission_id is None
    assert sysadmin.status is AgentStatus.IDLE
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
pytest tests/test_agents.py -k reset_working -v
```

Expected: FAIL because `reset_working` does not exist.

- [ ] **Step 3: Implement the minimal registry operation**

Use one database transaction, select only the supplied keys in `WORKING`, set status to `IDLE`, clear `current_mission_id`, commit, and return the changed rows in deterministic key order.

```python
def reset_working(self, keys: tuple[str, ...]) -> list[Agent]:
    with self.session_factory() as db:
        agents = list(
            db.scalars(
                select(Agent)
                .where(Agent.key.in_(keys), Agent.status == AgentStatus.WORKING)
                .order_by(Agent.key)
            )
        )
        for agent in agents:
            agent.status = AgentStatus.IDLE
            agent.current_mission_id = None
        db.commit()
        return agents
```

- [ ] **Step 4: Run agent tests**

```bash
pytest tests/test_agents.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/agents/registry.py tests/test_agents.py
git commit -m "feat: recover stale agent state"
```

---

### Task 3: Startup recovery for interrupted missions

**Files:**
- Modify: `src/ai_hq/worker.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_missions.py`

**Interfaces:**
- Consumes: `MissionService.running_missions()`, `MissionService.transition()`, `AgentRegistry.reset_working()`.
- Produces: `recover_worker_state(missions: MissionService, agents: AgentRegistry) -> int`, returning the number of interrupted missions paused.

- [ ] **Step 1: Write failing worker recovery tests**

Add tests using real test DB services where practical. Prove startup recovery pauses every pre-existing `RUNNING` mission, writes `error_state={"code": "worker_restart_recovery_required"}`, never invokes a department executor, and clears stale Commander/SysAdmin state.

```python
def test_recover_worker_state_pauses_interrupted_missions_and_clears_agents(
    mission_service, agent_registry
):
    mission = mission_service.create_mission(
        title="interrupted", description="", owner_agent="sysadmin", source="test"
    )
    mission_service.transition(mission.id, MissionStatus.RUNNING)
    agent_registry.ensure_phase1_agents()
    agent_registry.set_state(
        "commander", AgentStatus.WORKING, current_mission_id=mission.id
    )
    agent_registry.set_state(
        "sysadmin", AgentStatus.WORKING, current_mission_id=mission.id
    )

    recovered = worker.recover_worker_state(mission_service, agent_registry)

    updated = mission_service.get_mission(mission.id)
    assert recovered == 1
    assert updated.status is MissionStatus.PAUSED
    assert updated.error_state == {"code": "worker_restart_recovery_required"}
    assert agent_registry.get_by_key("commander").status is AgentStatus.IDLE
    assert agent_registry.get_by_key("sysadmin").status is AgentStatus.IDLE
```

- [ ] **Step 2: Run focused test and verify RED**

```bash
pytest tests/test_worker.py -k recover_worker_state -v
```

Expected: FAIL because `recover_worker_state` does not exist.

- [ ] **Step 3: Implement conservative startup recovery**

Add:

```python
def recover_worker_state(missions: MissionService, agents: AgentRegistry) -> int:
    interrupted = missions.running_missions()
    for mission in interrupted:
        missions.transition(
            mission.id,
            MissionStatus.PAUSED,
            error_state={"code": "worker_restart_recovery_required"},
        )
    agents.reset_working(("commander", "sysadmin"))
    return len(interrupted)
```

Do not execute or requeue interrupted missions.

- [ ] **Step 4: Run worker, mission, agent tests**

```bash
pytest tests/test_worker.py tests/test_missions.py tests/test_agents.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/worker.py tests/test_worker.py tests/test_missions.py
git commit -m "feat: recover interrupted missions"
```

---

### Task 4: Runtime SystemState gate re-read every polling cycle

**Files:**
- Modify: `src/ai_hq/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `SystemState` row id `1`, `OperatingMode`, worker `session_factory`.
- Produces: `runtime_execution_allowed(session_factory) -> bool` with fail-closed semantics.

- [ ] **Step 1: Write failing runtime-gate tests**

Cover `safe`, `normal`, `freeze`, missing row, invalid mode, and prove repeated calls see DB changes rather than a cached startup setting.

```python
def test_runtime_execution_allowed_rereads_system_state(session_factory):
    with session_factory() as db:
        state = db.get(SystemState, 1)
        state.operating_mode = OperatingMode.SAFE.value
        db.commit()
    assert worker.runtime_execution_allowed(session_factory) is True

    with session_factory() as db:
        state = db.get(SystemState, 1)
        state.operating_mode = OperatingMode.FREEZE.value
        db.commit()
    assert worker.runtime_execution_allowed(session_factory) is False
```

Also add separate tests for missing/invalid rows returning `False` without raising.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
pytest tests/test_worker.py -k runtime_execution_allowed -v
```

Expected: FAIL because the runtime DB gate does not exist.

- [ ] **Step 3: Implement fail-closed DB gate**

```python
def runtime_execution_allowed(session_factory) -> bool:
    try:
        with session_factory() as db:
            state = db.get(SystemState, 1)
            if state is None:
                return False
            try:
                mode = OperatingMode(state.operating_mode)
            except ValueError:
                return False
            return mode is not OperatingMode.FREEZE
    except Exception:
        return False
```

Keep exception scope local to the read so uncertain runtime state never authorizes execution.

- [ ] **Step 4: Run worker tests**

```bash
pytest tests/test_worker.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/worker.py tests/test_worker.py
git commit -m "feat: gate worker on runtime system state"
```

---

### Task 5: Enforce one running mission before queue claim

**Files:**
- Modify: `src/ai_hq/departments/runner.py`
- Test: `tests/test_department_runner.py`

**Interfaces:**
- Consumes: `MissionService.has_running()` and existing `run_once() -> bool` contract.
- Produces: `run_once()` returns `False` without routing/executing when a mission is already `RUNNING`.

- [ ] **Step 1: Write a failing active-mission guard test**

```python
def test_runner_does_not_start_queued_work_while_mission_is_running(runner_fixture):
    runner, missions, sysadmin = runner_fixture
    active = missions.create_mission(
        title="active", description="", owner_agent="sysadmin", source="test"
    )
    missions.transition(active.id, MissionStatus.RUNNING)
    queued = missions.create_mission(
        title="check ai hq health", description="", owner_agent="commander", source="test"
    )

    assert runner.run_once() is False
    assert missions.get_mission(queued.id).status is MissionStatus.QUEUED
    assert sysadmin.calls == []
```

Adapt fixture names to the existing `tests/test_department_runner.py` helpers rather than inventing parallel fixtures.

- [ ] **Step 2: Run focused test and verify RED**

```bash
pytest tests/test_department_runner.py -k 'while_mission_is_running' -v
```

Expected: FAIL because the current runner selects queued work without checking another `RUNNING` mission.

- [ ] **Step 3: Add the minimal guard at the start of `run_once()`**

```python
def run_once(self) -> bool:
    if self.mission_service.has_running():
        return False
    mission = self.mission_service.oldest_queued()
    ...
```

Do not treat `WAITING_APPROVAL` as running.

- [ ] **Step 4: Run department-runner tests**

```bash
pytest tests/test_department_runner.py -v
```

Expected: PASS, including existing approval behavior.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/departments/runner.py tests/test_department_runner.py
git commit -m "feat: enforce single active mission"
```

---

### Task 6: Harden the worker polling loop around runtime state and mission-local failures

**Files:**
- Modify: `src/ai_hq/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `runtime_execution_allowed(session_factory)`, `recover_worker_state()`, `DepartmentRunner.run_once()`.
- Produces: a resilient `run_worker()` loop that sleeps five seconds when frozen/blocked/idle, processes immediately when work completed, and keeps running after bounded mission-local exceptions.

- [ ] **Step 1: Replace startup-setting loop tests with runtime-state loop tests**

Write tests proving:

```python
# runtime safe -> run_once is called
# runtime freeze -> run_once is not called and sleep(5) occurs
# DB runtime changes safe -> freeze are observed without worker restart
# runner returns True -> next cycle happens without sleep
# runner returns False -> sleep(5)
```

Use injected/monkeypatched `runtime_execution_allowed` and a `StopProbe` exactly as existing worker tests already do.

- [ ] **Step 2: Add a failing test proving a bounded runner exception does not kill the loop**

Use a first `run_once()` call that raises a bounded `RuntimeError("mission execution failed")`, a second call that returns `False`, and terminate via `StopProbe` from sleep. Assert the loop reached the second cycle.

- [ ] **Step 3: Run `tests/test_worker.py` and verify RED**

```bash
pytest tests/test_worker.py -v
```

Expected: failures because current `run_worker()` checks `settings.operating_mode` once and lets runner exceptions escape.

- [ ] **Step 4: Rework `run_worker()` minimally**

Required flow:

```python
def run_worker() -> int:
    settings = get_settings()
    if not redis_ping():
        return 1

    runner = build_department_runner(settings)
    session_factory = get_session_factory()
    missions = runner.mission_service
    agents = runner.agent_registry
    recover_worker_state(missions, agents)

    while True:
        if not runtime_execution_allowed(session_factory):
            time.sleep(5)
            continue
        try:
            processed = runner.run_once()
        except Exception:
            processed = False
        if not processed:
            time.sleep(5)
```

Before committing, narrow the `except` to exceptions that represent mission-local execution failures if the existing service hierarchy exposes a suitable type. Do not swallow `KeyboardInterrupt`, `SystemExit`, or process-fatal exceptions; `except Exception` already excludes those. Database/runtime-state uncertainty is handled by `runtime_execution_allowed()` and should not authorize work.

- [ ] **Step 5: Run worker tests**

```bash
pytest tests/test_worker.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_hq/worker.py tests/test_worker.py
git commit -m "feat: harden autonomous worker loop"
```

---

### Task 7: Keep parked approvals non-blocking and preserve oldest-first processing

**Files:**
- Test: `tests/test_department_runner.py`
- Test: `tests/test_missions.py`
- Modify only if tests expose a defect: `src/ai_hq/departments/runner.py`, `src/ai_hq/missions/service.py`

**Interfaces:**
- Consumes: existing `oldest_queued()`, `WAITING_APPROVAL`, `run_once()`.
- Produces: regression proof that parked approvals do not count as active and queue ordering stays oldest-first.

- [ ] **Step 1: Add a regression test for parked approval plus later queued work**

Create one `WAITING_APPROVAL` mission and one later `QUEUED` supported mission. Assert `run_once()` processes the queued mission and leaves the parked mission untouched.

- [ ] **Step 2: Add a regression test for oldest-first selection**

Create two supported queued missions and assert the first call to `run_once()` completes/parks the earlier mission while the later one remains queued.

- [ ] **Step 3: Run focused tests**

```bash
pytest tests/test_department_runner.py tests/test_missions.py -k 'approval or oldest' -v
```

Expected: PASS if existing semantics already satisfy the spec. If RED, make only the minimal code correction required and rerun.

- [ ] **Step 4: Commit tests (and minimal fix if needed)**

```bash
git add tests/test_department_runner.py tests/test_missions.py src/ai_hq/departments/runner.py src/ai_hq/missions/service.py
git commit -m "test: lock autonomous queue semantics"
```

---

### Task 8: Remove stale DripVid Docker permission from worker construction

**Files:**
- Modify: `src/ai_hq/worker.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_host_helper_server.py` if needed for cross-contract proof

**Interfaces:**
- Consumes: `HostAllowLists`.
- Produces: worker-side containers exactly `{"ai-hq-web", "ai-hq-worker"}`.

- [ ] **Step 1: Write a failing allow-list test**

Extract or intercept the `HostAllowLists` passed to `SysAdminService` from `build_department_runner()` and assert:

```python
assert allow_lists.services == frozenset({"ai-hq", "nginx", "dripvid"})
assert allow_lists.containers == frozenset({"ai-hq-web", "ai-hq-worker"})
assert allow_lists.logs == frozenset({"ai-hq", "nginx", "dripvid"})
```

- [ ] **Step 2: Run focused test and verify RED**

```bash
pytest tests/test_worker.py -k dripvid -v
```

Expected: FAIL because current worker construction still includes `"dripvid"` in container targets.

- [ ] **Step 3: Remove `"dripvid"` from the worker-side container allow-list**

```python
containers=frozenset({"ai-hq-web", "ai-hq-worker"})
```

Keep DripVid in services and logs.

- [ ] **Step 4: Run Host Helper and worker tests**

```bash
pytest tests/test_worker.py tests/test_host_helper_executor.py tests/test_host_helper_server.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/worker.py tests/test_worker.py tests/test_host_helper_server.py
git commit -m "fix: align worker host allow lists"
```

---

### Task 9: Add bounded orchestration ledger visibility without polling spam

**Files:**
- Modify: `src/ai_hq/worker.py`
- Modify only if required: `src/ai_hq/ledger/models.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `OperationsLedger`, existing ledger event types and mission status transition events.
- Produces: durable visibility for startup/recovery/claim only where existing ledger contracts support it without an unnecessary schema expansion.

- [ ] **Step 1: Inspect existing `LedgerEventType` values before writing tests**

Use the existing closest event types when they can express startup/recovery/claim with bounded metadata. Do not add a new event enum merely to log an idle poll.

- [ ] **Step 2: Write failing tests for required useful events only**

At minimum prove interrupted mission recovery is visible through the normal `MISSION_STATUS_CHANGED` event produced by `MissionService.transition()`. If an existing general event type can cleanly represent mission claim, add one event at claim time; otherwise document claim visibility through the transition to `RUNNING` and do not expand the enum.

- [ ] **Step 3: Run ledger/worker tests and verify the intended RED only where code is missing**

```bash
pytest tests/test_worker.py tests/test_ledger.py -v
```

- [ ] **Step 4: Implement only the missing bounded visibility**

Do not emit any event from the five-second idle branch. Keep the ledger authoritative chain intact.

- [ ] **Step 5: Run ledger and worker tests**

```bash
pytest tests/test_worker.py tests/test_ledger.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_hq/worker.py src/ai_hq/ledger/models.py tests/test_worker.py tests/test_ledger.py
git commit -m "feat: record autonomous recovery events"
```

---

### Task 10: Full verification and production acceptance tooling

**Files:**
- Modify if needed: `deploy/check-production.sh`
- Create: `deploy/check-autonomous-loop.sh`
- Test: `tests/test_deploy_contract.py`
- Test: `tests/test_compose_contract.py`

**Interfaces:**
- Consumes: production env at `/etc/ai-hq/ai-hq.env`, active release symlink `/opt/ai-hq/app`, Docker Compose project `ai-hq`, `SystemState`, mission/ledger tables.
- Produces: a non-secret read-only acceptance script for verifying autonomous-loop deployment gates. The script must not change runtime mode or create missions; those deliberate acceptance actions remain explicit operator steps.

- [ ] **Step 1: Write a failing deploy-contract test for the new acceptance script**

Assert the script exists, uses `set -euo pipefail`, checks the worker/web containers, active release, Host Helper service/socket, and reads `SystemState` without printing secrets.

- [ ] **Step 2: Run deploy-contract test and verify RED**

```bash
pytest tests/test_deploy_contract.py -k autonomous -v
```

Expected: FAIL because `deploy/check-autonomous-loop.sh` does not exist.

- [ ] **Step 3: Create the read-only acceptance script**

The script must perform these checks:

```bash
#!/usr/bin/env bash
set -euo pipefail

APP=/opt/ai-hq/app
ENV=/etc/ai-hq/ai-hq.env

test -L "$APP"
test -f "$ENV"
sudo systemctl is-active --quiet ai-hq-host-helper.service
test -S /run/ai-hq/host-helper.sock

docker inspect ai-hq-web-1 --format '{{.State.Health.Status}}'
docker inspect ai-hq-worker-1 --format '{{.State.Status}}'

docker exec -i ai-hq-web-1 python - <<'PY'
from ai_hq.db import get_session_factory
from ai_hq.models.system_state import SystemState

with get_session_factory()() as db:
    state = db.get(SystemState, 1)
    if state is None:
        raise SystemExit("SystemState missing")
    print("OPERATING MODE:", state.operating_mode)
    print("SIMULATION MODE:", state.simulation_mode)
PY
```

Use the repository's current privilege conventions in deploy scripts; if production checks are always invoked under root, remove nested `sudo` from the script and test accordingly. Never output admin hash/session secret/helper credential.

- [ ] **Step 4: Run deploy-contract and compose tests**

```bash
pytest tests/test_deploy_contract.py tests/test_compose_contract.py tests/test_compose_security.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the complete verification suite**

```bash
pytest -q
```

Expected: all tests PASS.

Run lint using the repository CI command from `.github/workflows/ci.yml`, then validate Compose with the same CI command. Expected: both PASS.

- [ ] **Step 6: Inspect final diff against the approved spec**

Confirm:

```text
- no proactive mission creation
- no parallel worker design
- no mutation capability additions
- runtime DB state gates every cycle
- interrupted RUNNING missions pause, never replay
- WAITING_APPROVAL does not block queue
- stale agent WORKING state is cleared at startup
- DripVid absent from Docker allow-lists
- no idle polling ledger spam
```

- [ ] **Step 7: Commit verification tooling**

```bash
git add deploy/check-autonomous-loop.sh deploy/check-production.sh tests/test_deploy_contract.py tests/test_compose_contract.py
git commit -m "test: add autonomous loop production gates"
```

- [ ] **Step 8: Push feature branch and require fresh CI green before merge**

```bash
git push -u origin feature/commander-continuous-loop
```

Do not fast-forward `main` until the exact feature head has fresh successful Install, Lint, Test, and Validate Compose steps.

- [ ] **Step 9: Production acceptance after verified deployment**

Follow the approved spec exactly: deploy the exact CI-green SHA; verify active release and health; deliberately set runtime to Safe + Simulation ON; queue deterministic supported missions and prove automatic draining; include one approval-parking case; then deliberately set Safe + Simulation OFF and run exactly one real read-only mission. Verify exactly one real tool execution, Safe Mode remains ON, and no mutation capability is introduced.
