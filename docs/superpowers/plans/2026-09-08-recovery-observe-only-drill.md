# AI HQ Observe-Only Recovery Drill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot, production-safe DripVid recovery drill that injects one synthetic app incident at the configured failure threshold, surfaces it through existing recovery observability, and relies on the normal healthy worker cycle to resolve it without any DripVid interruption or recovery mutation.

**Architecture:** Add a focused `ai_hq.recovery.drill` module. `RecoveryDrillService` validates current settings and a fresh healthy recovery snapshot, performs a single guarded database transaction that inserts a fixed `dripvid:app` incident, then uses the existing `RecoveryStatusService` to project bounded unhealthy status. A CLI wrapper exposes only this fixed drill from inside the worker container; it accepts no target, URL, service, component, threshold, command, or mutation arguments.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Pydantic Settings, pytest, Ruff, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-08-recovery-observe-only-drill-design.md`

## Global Constraints

- Production recovery must remain `AI_HQ_RECOVERY_ENABLED=true` and `AI_HQ_RECOVERY_OBSERVE_ONLY=true` during the drill.
- Production operating mode remains `safe`; the drill refuses `freeze` mode.
- Target is fixed to `dripvid`; component is fixed to `app`.
- The drill accepts no caller-supplied URL, service name, host, component, command, threshold, tool, or mutation target.
- No recovery approval is created, consumed, or bypassed.
- No `service.recover`, `service_restart`, Docker, systemd, deployment, shell, subprocess, or Host Helper mutation capability may be imported or called from drill code.
- No DripVid process, service, container, network path, readiness endpoint, media path, or host configuration may be modified.
- No existing active recovery incident may be overwritten, resolved, or merged into the drill.
- The synthetic incident must have no recovery mission and no recovery attempts.
- Operator-visible failures use fixed bounded codes; raw exception text, diagnostics, credentials, URLs, paths, logs, and environment values are never returned.
- The drill leaves the synthetic incident active so the normal healthy worker cycle proves resolution.

---

### Task 1: Lock the Drill Contract With Failing Tests

**Files:**
- Create: `tests/test_recovery_drill.py`
- Modify: `tests/test_recovery_security_boundary.py`

**Interfaces:**
- Consumes: `Settings`, `OperatingMode`, `RecoveryIncident`, `RecoveryIncidentState`, `RecoveryAttempt`, `RecoveryStatusService`.
- Produces test contract for `RecoveryDrillService.run() -> dict[str, object]` and fixed failure codes.

- [ ] **Step 1: Write failing service contract tests**

Follow the existing SQLAlchemy test session factory pattern in the recovery tests. Add a helper:

```python
def record_healthy_status(status_service, now):
    return status_service.record_successful_cycle(
        target="dripvid",
        observed_at=now,
        summary={"reachable": True, "status_code": 200, "ready": True},
    )
```

Add explicit tests with deterministic `now` and an injected clock:

```python
def test_drill_refuses_when_recovery_disabled(settings, service):
    result = service.run(
        settings=settings.model_copy(update={"recovery_enabled": False})
    )
    assert result == {"ok": False, "code": "recovery_disabled"}


def test_drill_refuses_when_observe_only_disabled(settings, service):
    result = service.run(
        settings=settings.model_copy(update={"recovery_observe_only": False})
    )
    assert result == {"ok": False, "code": "observe_only_required"}


def test_drill_refuses_in_freeze_mode(settings, service):
    result = service.run(
        settings=settings.model_copy(update={"operating_mode": OperatingMode.FREEZE})
    )
    assert result == {"ok": False, "code": "freeze_mode"}
```

Add separate explicit tests for missing status, unhealthy status, stale healthy status older than five seconds, a future healthy timestamp, and any existing active DripVid incident. Expected codes are respectively `healthy_status_required`, `healthy_status_required`, `fresh_healthy_probe_required`, `fresh_healthy_probe_required`, and `active_incident_present`.

- [ ] **Step 2: Write failing success-path assertions**

Require exactly one active incident with:

```python
assert incident.active_key == "dripvid:app"
assert incident.target == "dripvid"
assert incident.component == "app"
assert incident.state is RecoveryIncidentState.SUSPECT
assert incident.consecutive_failures == settings.recovery_failure_threshold
assert incident.diagnostics == {"drill": True}
assert incident.verification == {}
assert incident.recovery_mission_id is None
```

Require zero `RecoveryAttempt` rows for that incident and bounded result:

```python
assert result == {
    "ok": True,
    "target": "dripvid",
    "component": "app",
    "incident_id": incident.id,
    "incident_state": "suspect",
    "consecutive_failures": settings.recovery_failure_threshold,
    "status": "unhealthy",
    "observe_only": True,
}
```

- [ ] **Step 3: Write failing idempotency/race tests**

Run the drill once successfully, then call it again before healthy resolution and assert:

```python
assert second_result == {"ok": False, "code": "active_incident_present"}
```

Patch the insert/commit boundary to raise SQLAlchemy `IntegrityError` and assert:

```python
assert result == {"ok": False, "code": "drill_conflict"}
```

Also assert the rendered/serialized result contains neither the exception class name nor the database message.

- [ ] **Step 4: Extend the security-boundary regression**

In `tests/test_recovery_security_boundary.py`, read `src/ai_hq/recovery/drill.py` and assert forbidden tokens/imports are absent: `subprocess`, `os.system`, `docker`, `systemctl`, `service_restart`, `service.recover`, deployment helper imports, Host Helper mutation executor imports, and `RecoveryObserver`. Assert the CLI parser defines only `--json` beyond built-in help.

- [ ] **Step 5: Run RED verification**

Run:

```bash
python -m pytest -q tests/test_recovery_drill.py tests/test_recovery_security_boundary.py
```

Expected: new drill tests fail because `ai_hq.recovery.drill` does not exist; existing unrelated security tests remain green.

- [ ] **Step 6: Commit the RED contract**

```bash
git add tests/test_recovery_drill.py tests/test_recovery_security_boundary.py
git commit -m "test: define observe-only recovery drill contract"
```

---

### Task 2: Implement the Guarded Drill Service

**Files:**
- Create: `src/ai_hq/recovery/drill.py`
- Test: `tests/test_recovery_drill.py`

**Interfaces:**
- Consumes: session factory callable, `Settings`, `OperatingMode`, `RecoveryIncident`, `RecoveryIncidentState`, `RecoveryAttempt`, `RecoveryStatusService`.
- Produces: `RecoveryDrillService(session_factory, *, clock=None)` and `RecoveryDrillService.run(*, settings: Settings) -> dict[str, object]`.

- [ ] **Step 1: Add fixed constants and bounded result helpers**

Implement only fixed internal values:

```python
_TARGET = "dripvid"
_COMPONENT = "app"
_ACTIVE_KEY = "dripvid:app"
_FRESH_HEALTHY_SECONDS = 5
_DRILL_DIAGNOSTICS = {"drill": True}
_UNHEALTHY_SUMMARY = {
    "reachable": True,
    "status_code": 503,
    "ready": False,
    "incident_detected": True,
    "incident_resolved": False,
    "worked": True,
}
```

Add:

```python
def _failure(code: str) -> dict[str, object]:
    return {"ok": False, "code": code}
```

- [ ] **Step 2: Implement fail-closed preconditions**

`run(settings=...)` must return fixed codes in this order:

```python
if not settings.recovery_enabled:
    return _failure("recovery_disabled")
if not settings.recovery_observe_only:
    return _failure("observe_only_required")
if settings.operating_mode is OperatingMode.FREEZE:
    return _failure("freeze_mode")
```

Read `RecoveryStatusService(session_factory).snapshot("dripvid")`. Require `last_result == "healthy"`, `ready is True`, no active incident metadata, and non-null `last_probe_at`. If the snapshot is missing/unhealthy/unknown/error return `healthy_status_required`. Normalize both timestamps to UTC, compute `age = now - last_probe_at`, and require `0 <= age.total_seconds() <= 5`; otherwise return `fresh_healthy_probe_required`.

- [ ] **Step 3: Implement the atomic incident insertion**

Within one SQLAlchemy session, query:

```python
select(RecoveryIncident).where(
    RecoveryIncident.target == "dripvid",
    RecoveryIncident.active_key.is_not(None),
).limit(1)
```

If a row exists, rollback/exit without writes and return `active_incident_present`.

Insert exactly:

```python
incident = RecoveryIncident(
    active_key="dripvid:app",
    target="dripvid",
    component="app",
    state=RecoveryIncidentState.SUSPECT,
    consecutive_failures=settings.recovery_failure_threshold,
    first_failure_at=now,
    last_failure_at=now,
    last_observed_at=now,
    diagnostics={"drill": True},
    verification={},
    recovery_mission_id=None,
)
```

Commit and refresh. Catch `sqlalchemy.exc.IntegrityError` at this transaction boundary, rollback, and return `drill_conflict`; never include exception text.

- [ ] **Step 4: Project existing bounded recovery status**

After the incident commits, call:

```python
snapshot = RecoveryStatusService(session_factory).record_successful_cycle(
    target="dripvid",
    observed_at=now,
    summary=_UNHEALTHY_SUMMARY,
)
```

Require:

```python
snapshot["last_result"] == "unhealthy"
snapshot["ready"] is False
snapshot["active_incident_id"] == incident.id
snapshot["active_incident_state"] == "suspect"
snapshot["consecutive_failures"] == settings.recovery_failure_threshold
```

If any requirement fails, return `status_verification_failed`.

- [ ] **Step 5: Verify no mutation artifacts were created**

Read the incident again and query:

```python
select(func.count()).select_from(RecoveryAttempt).where(
    RecoveryAttempt.incident_id == incident.id
)
```

Require `incident.recovery_mission_id is None` and attempt count equals `0`. If either fails, return `status_verification_failed`; do not invoke cleanup or recovery mutation from the drill.

- [ ] **Step 6: Return bounded success result**

Return exactly:

```python
{
    "ok": True,
    "target": "dripvid",
    "component": "app",
    "incident_id": incident.id,
    "incident_state": "suspect",
    "consecutive_failures": settings.recovery_failure_threshold,
    "status": "unhealthy",
    "observe_only": True,
}
```

Wrap the public `run()` boundary so unexpected exceptions collapse to `{"ok": False, "code": "drill_failed"}` without printing or persisting exception text.

- [ ] **Step 7: Run GREEN verification**

```bash
python -m pytest -q tests/test_recovery_drill.py tests/test_recovery_security_boundary.py
python -m ruff check src/ai_hq/recovery/drill.py tests/test_recovery_drill.py tests/test_recovery_security_boundary.py
```

Expected: PASS.

- [ ] **Step 8: Commit the service**

```bash
git add src/ai_hq/recovery/drill.py tests/test_recovery_drill.py tests/test_recovery_security_boundary.py
git commit -m "feat: add guarded observe-only recovery drill"
```

---

### Task 3: Add the One-Shot Worker CLI

**Files:**
- Modify: `src/ai_hq/recovery/drill.py`
- Test: `tests/test_recovery_drill.py`

**Interfaces:**
- Consumes: `get_settings()`, the application session factory used by recovery bootstrap, `RecoveryDrillService.run()`.
- Produces: `python -m ai_hq.recovery.drill` and optional `--json` output formatting only.

- [ ] **Step 1: Write failing CLI tests**

Parameterize invalid argument vectors:

```python
[
    ["--target", "dripvid"],
    ["--component", "app"],
    ["--url", "http://127.0.0.1"],
    ["--command", "restart"],
    ["--threshold", "2"],
    ["dripvid"],
    ["--unknown"],
]
```

Each must be rejected by the parser with non-zero status. No arguments and `--json` must be accepted. Test that JSON output contains only the bounded service result keys and never settings, environment values, diagnostics, URLs, paths, logs, or exception text.

- [ ] **Step 2: Implement minimal CLI**

Use `argparse.ArgumentParser` with only:

```python
parser.add_argument("--json", action="store_true")
```

Build the production session factory using the same database/bootstrap mechanism already used by recovery runtime. Load `get_settings()`. Invoke `RecoveryDrillService.run(settings=settings)` once. Return exit code `0` only when `result["ok"] is True`; otherwise return a non-zero code.

For `--json`, print `json.dumps(result, sort_keys=True)`. For normal output, print one bounded line assembled only from keys already present in `result`.

- [ ] **Step 3: Run focused tests**

```bash
python -m pytest -q tests/test_recovery_drill.py
python -m ruff check src/ai_hq/recovery/drill.py tests/test_recovery_drill.py
```

Expected: PASS.

- [ ] **Step 4: Commit CLI support**

```bash
git add src/ai_hq/recovery/drill.py tests/test_recovery_drill.py
git commit -m "feat: expose one-shot recovery drill cli"
```

---

### Task 4: Prove Normal Healthy Resolution and Security Isolation

**Files:**
- Modify: `tests/test_recovery_drill.py`
- Modify: `tests/test_recovery_observability.py`
- Modify: `tests/test_recovery_security_boundary.py`

**Interfaces:**
- Consumes: existing normal recovery cycle/coordinator healthy-resolution behavior and `RecoveryStatusService.snapshot()`.
- Produces: regression proof that the drill leaves resolution to normal recovery and cannot reach mutation authority.

- [ ] **Step 1: Add integration test for healthy resolution**

Arrange a fresh healthy status, run the drill, assert the status is unhealthy with an active synthetic incident, then drive the existing normal healthy recovery cycle once using its current fake readiness probe fixture. Assert afterward:

```python
snapshot = RecoveryStatusService(session_factory).snapshot("dripvid")
assert snapshot["last_result"] == "healthy"
assert snapshot["ready"] is True
assert snapshot["active_incident_id"] is None
assert snapshot["active_incident_state"] is None
assert snapshot["consecutive_failures"] == 0
```

Reload the drill incident and assert:

```python
assert incident.state is RecoveryIncidentState.RESOLVED
assert incident.active_key is None
assert incident.recovery_mission_id is None
assert attempt_count == 0
```

- [ ] **Step 2: Strengthen security assertions**

Assert the drill module does not import `RecoveryObserver`, Tool Gateway execution code, Host Helper executors, deployment modules, `subprocess`, or service mutation adapters. Compare the feature branch diff to `main` and assert no config defaults, recovery permissions, approval policy, Host Helper capabilities, service mappings, deployment scripts, or UI controls changed.

- [ ] **Step 3: Run recovery-focused suite**

```bash
python -m pytest -q \
  tests/test_recovery_drill.py \
  tests/test_recovery_observability.py \
  tests/test_recovery_status.py \
  tests/test_recovery_security_boundary.py
```

Expected: PASS.

- [ ] **Step 4: Commit integration/security proof**

```bash
git add tests/test_recovery_drill.py tests/test_recovery_observability.py tests/test_recovery_security_boundary.py
git commit -m "test: prove recovery drill resolves through healthy worker"
```

---

### Task 5: Full Verification and Pull Request

**Files:**
- No functional files beyond Tasks 1-4 unless verification exposes a defect.

**Interfaces:**
- Produces exact-SHA evidence suitable for merge/deployment review.

- [ ] **Step 1: Run full verification where a runner is available**

```bash
python -m ruff check src tests
python -m pytest -q
docker compose config >/dev/null
```

Expected: all pass.

- [ ] **Step 2: Self-review the branch diff**

Verify changed functional scope is limited to the drill module/tests and docs. Confirm no config default, recovery permission, approval policy, Host Helper capability, service mapping, deployment script, or UI mutation control changed.

- [ ] **Step 3: Open a draft PR and use GitHub Actions as authoritative runner**

Create a draft PR from `feature/recovery-drill` to `main`. Record exact branch head SHA and CI run ID. Require Install, Lint, Test, and Validate Compose to all succeed for that exact SHA or GitHub merge result.

- [ ] **Step 4: Review CI logs**

Confirm Ruff passes, the full pytest suite is green, and Compose validation succeeds. If a failure appears, use systematic debugging; do not weaken drill safety assertions merely to make CI pass.

- [ ] **Step 5: Integration gate**

Do not merge automatically. Present the verified PR/head SHA for human integration choice. After merge, verify exact `main` merge SHA CI again before production deployment.

---

## Production Drill Procedure After Merge and Explicit Deploy Authorization

Deployment is separate from implementation and merge. After the exact merged SHA is deployed through `deploy/ai-hq-deploy` and `deploy/check-production.sh` passes:

1. Verify `AI_HQ_RECOVERY_ENABLED=true` and `AI_HQ_RECOVERY_OBSERVE_ONLY=true`.
2. Verify DripVid is healthy and the AI HQ Recovery card is healthy.
3. Run the drill inside the worker container only:

```bash
docker compose -p ai-hq --env-file /etc/ai-hq/ai-hq.env -f /opt/ai-hq/app/compose.yaml exec -T worker \
  python -m ai_hq.recovery.drill --json
```

4. Confirm the returned result is bounded and `ok=true`.
5. Confirm DripVid remains continuously reachable; do not restart or alter it.
6. Confirm the Recovery card briefly shows unhealthy with an active incident.
7. Confirm no recovery mission or attempt appears.
8. Allow the normal healthy worker cycle to resolve the synthetic incident.
9. Confirm the Recovery card returns to healthy.
10. Stop. Do not disable observe-only or authorize real recovery as part of this milestone.
