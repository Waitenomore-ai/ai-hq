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

Add fixtures using the repository's existing SQLAlchemy test session factory pattern. Create a helper that records a healthy status with `RecoveryStatusService.record_successful_cycle(target="dripvid", observed_at=now, summary={"reachable": True, "status_code": 200, "ready": True})`.

Cover these exact cases:

```python
def test_drill_refuses_when_recovery_disabled(...):
    result = service.run(settings=settings.model_copy(update={"recovery_enabled": False}))
    assert result == {"ok": False, "code": "recovery_disabled"}


def test_drill_refuses_when_observe_only_disabled(...):
    result = service.run(settings=settings.model_copy(update={"recovery_observe_only": False}))
    assert result == {"ok": False, "code": "observe_only_required"}


def test_drill_refuses_in_freeze_mode(...):
    result = service.run(settings=settings.model_copy(update={"operating_mode": OperatingMode.FREEZE}))
    assert result == {"ok": False, "code": "freeze_mode"}


def test_drill_requires_fresh_healthy_status(...):
    # unknown/unhealthy/missing and >5-second-old healthy snapshots all fail closed.
    ...


def test_drill_refuses_any_existing_active_dripvid_incident(...):
    ...
```

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

Test that a second invocation while the drill incident is active returns `active_incident_present`, and simulate an integrity conflict so the result is the fixed code `drill_conflict` with no exception text.

- [ ] **Step 4: Extend the security-boundary regression**

In `tests/test_recovery_security_boundary.py`, inspect `src/ai_hq/recovery/drill.py` source and fail if it contains imports/calls for `subprocess`, `os.system`, `docker`, `systemctl`, `service_restart`, `service.recover`, deployment helpers, or Host Helper mutation executors. Also assert the CLI exposes no configurable target/component/url/command/threshold options.

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
- Consumes: `SessionFactory`, `Settings`, `OperatingMode`, `RecoveryIncident`, `RecoveryIncidentState`, `RecoveryAttempt`, `RecoveryStatusService`.
- Produces: `RecoveryDrillService(session_factory, *, clock=None)`, `RecoveryDrillService.run(*, settings: Settings) -> dict[str, object]`.

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

Add `_failure(code: str) -> dict[str, object]` returning only `{"ok": False, "code": code}`.

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

Read `RecoveryStatusService.snapshot("dripvid")`. Require `last_result == "healthy"`, `ready is True`, no active incident metadata, a non-null `last_probe_at`, and age in `[0, 5]` seconds. Use timezone-normalized UTC comparison; future timestamps fail with `fresh_healthy_probe_required`.

- [ ] **Step 3: Implement the atomic incident insertion**

Within one SQLAlchemy session/transaction, query for **any** row where `RecoveryIncident.target == "dripvid"` and `active_key IS NOT NULL`; if one exists return `active_incident_present` before writing.

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

Commit and refresh. Catch only database integrity/concurrency failure at the transaction boundary and return `drill_conflict`; do not include exception text.

- [ ] **Step 4: Project existing bounded recovery status**

After the incident commits, call:

```python
snapshot = RecoveryStatusService(session_factory).record_successful_cycle(
    target="dripvid",
    observed_at=now,
    summary=_UNHEALTHY_SUMMARY,
)
```

Verify snapshot is unhealthy, `ready is False`, active incident ID matches, active state is `suspect`, and consecutive failures equal `settings.recovery_failure_threshold`.

- [ ] **Step 5: Verify no mutation artifacts were created**

Read the incident again and query `RecoveryAttempt` count for its ID. Require `recovery_mission_id is None` and attempt count `0`. If not, return `status_verification_failed`; do not invoke cleanup/recovery mutation from the drill.

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

Unexpected exceptions must collapse to `{"ok": False, "code": "drill_failed"}` without printing or persisting exception text.

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
- Consumes: `get_settings()`, application session factory used by recovery bootstrap, `RecoveryDrillService.run()`.
- Produces: `python -m ai_hq.recovery.drill` and optional `--json` output formatting only.

- [ ] **Step 1: Write failing CLI tests**

Test parser behavior so these are rejected with non-zero status: `--target`, `--component`, `--url`, `--command`, `--threshold`, positional arguments, and unknown flags. Only no arguments and optional `--json` are accepted.

Test that JSON output contains only the bounded service result fields and never settings/environment/diagnostics.

- [ ] **Step 2: Implement minimal CLI**

Use `argparse.ArgumentParser` with only:

```python
parser.add_argument("--json", action="store_true")
```

Build the production session factory using the same database/bootstrap mechanism already used by recovery runtime. Load `get_settings()`. Invoke `RecoveryDrillService.run(settings=settings)` once. Return exit code `0` only when `result["ok"] is True`; otherwise non-zero.

For `--json`, print `json.dumps(result, sort_keys=True)`. For normal output, print a bounded one-line success/failure summary assembled only from keys in `result`.

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
- Consumes: deployed recovery cycle/coordinator healthy-resolution behavior, `RecoveryStatusService.snapshot()`.
- Produces: regression proof that the drill leaves resolution to normal recovery and cannot reach mutation authority.

- [ ] **Step 1: Add integration test for healthy resolution**

Arrange a fresh healthy status, run the drill, assert the status is unhealthy with an active synthetic incident, then drive the existing normal healthy recovery cycle once using its existing fake readiness probe. Assert afterward:

```python
snapshot = RecoveryStatusService(session_factory).snapshot("dripvid")
assert snapshot["last_result"] == "healthy"
assert snapshot["ready"] is True
assert snapshot["active_incident_id"] is None
assert snapshot["active_incident_state"] is None
assert snapshot["consecutive_failures"] == 0
```

Also assert the drill incident is `RESOLVED` and still has no mission/attempt.

- [ ] **Step 2: Strengthen security assertions**

Assert the drill module does not import `RecoveryObserver`, Tool Gateway execution, Host Helper executors, deployment modules, `subprocess`, or service mutation adapters. Assert no new `service.recover` permission or approval path was added anywhere in files changed by this feature.

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

- [ ] **Step 1: Run full local verification where a runner is available**

```bash
python -m ruff check src tests
python -m pytest -q
docker compose config >/dev/null
```

Expected: all pass.

- [ ] **Step 2: Self-review the branch diff**

Verify changed functional scope is limited to the drill module/tests and docs. Confirm no config default, recovery permission, approval policy, Host Helper capability, service mapping, deployment script, or UI mutation control changed.

- [ ] **Step 3: Push/open draft PR and use GitHub Actions as authoritative runner**

Create a draft PR from `feature/recovery-drill` to `main`. Record exact branch head SHA and CI run ID. Require Install, Lint, Test, and Validate Compose to all succeed for that exact SHA/merge result.

- [ ] **Step 4: Review CI logs**

Confirm Ruff passes, full pytest count is green, and Compose validation succeeds. If a failure appears, use systematic debugging; do not weaken the drill safety assertions to make CI pass.

- [ ] **Step 5: Integration gate**

Do not merge automatically. Present the verified PR/head SHA for human integration choice. After merge, verify the exact `main` merge SHA CI again before production deployment.

---

## Production Drill Procedure After Merge and Explicit Deploy Authorization

Deployment is separate from implementation/merge. After the exact merged SHA is deployed through `deploy/ai-hq-deploy` and `deploy/check-production.sh` passes:

1. Verify `AI_HQ_RECOVERY_ENABLED=true` and `AI_HQ_RECOVERY_OBSERVE_ONLY=true`.
2. Verify DripVid is healthy and AI HQ Recovery card is healthy.
3. Run the drill **inside the worker container only**:

```bash
docker compose -p ai-hq --env-file /etc/ai-hq/ai-hq.env -f /opt/ai-hq/app/compose.yaml exec -T worker \
  python -m ai_hq.recovery.drill --json
```

4. Confirm returned result is bounded and `ok=true`.
5. Confirm DripVid remains continuously reachable; do not restart or alter it.
6. Confirm Recovery card briefly shows unhealthy/active incident.
7. Confirm no recovery mission or attempt appears.
8. Allow the normal healthy worker cycle to resolve the synthetic incident.
9. Confirm Recovery card returns to healthy.
10. Stop. Do not disable observe-only or authorize real recovery as part of this milestone.
