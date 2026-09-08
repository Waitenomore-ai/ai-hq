# AI HQ Recovery Status Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the latest bounded DripVid recovery observation and expose it read-only through `/api/hq/state` and a compact Operations Floor status card.

**Architecture:** Reuse the existing sanitized `DripVidRecoveryCycle.last_summary` and `RecoveryWorkerCoordinator` heartbeat path. Add one durable `RecoveryStatus` row per target, a focused `RecoveryStatusService`, coordinator persistence hooks, a top-level `recovery` object in HQ state, and a non-interactive UI card rendered by the existing 10-second poll.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest, vanilla JavaScript, Jinja2, CSS, GitHub Actions CI.

**Spec:** `docs/superpowers/specs/2026-09-07-recovery-status-observability-design.md`

## Global Constraints

- Read-only observability only; do not add any recovery mutation endpoint or UI control.
- Do not change `AI_HQ_RECOVERY_OBSERVE_ONLY=true` as part of this milestone.
- Do not grant `service.recover` or create/consume scoped recovery approval.
- Do not persist raw readiness payloads, service logs, exceptions, credentials, URLs, host paths, or diagnostic text.
- Only persist whitelisted `reachable`, validated `status_code`, `ready`, incident ID/state, consecutive failures, timestamps, and derived result.
- `/api/hq/state` must remain authenticated and POST must remain disallowed.
- No shell, subprocess, Docker, systemd, deployment, or Host Helper mutation imports in recovery status/UI code.
- Existing recovery policy, thresholds, cooldowns, budgets, and failure behavior remain unchanged.
- Follow TDD for every code task and verify the exact branch SHA in CI before merge.

---

## File Structure

- `migrations/versions/0016_recovery_status.py` — single-head schema migration for durable bounded recovery status.
- `src/ai_hq/recovery/models.py` — add `RecoveryStatus` ORM model and result enum/type if needed.
- `src/ai_hq/recovery/status.py` — focused read/write service for the latest safe recovery snapshot.
- `src/ai_hq/recovery/bootstrap.py` — wire status recording into successful and failed due cycles.
- `src/ai_hq/hq/state.py` — project the persisted snapshot into HQ state without adding mutation behavior.
- `src/ai_hq/hq/api.py` — supply current `recovery_enabled` and `recovery_observe_only` settings to the HQ state service.
- `src/ai_hq/templates/home.html` — add one read-only DripVid Recovery card.
- `src/ai_hq/static/hq.js` — normalize/render the bounded recovery payload using `textContent` only.
- `src/ai_hq/static/hq.css` — style the compact card and state variants.
- `tests/test_recovery_models.py` — model and migration-facing expectations.
- `tests/test_recovery_status.py` — service persistence and sanitization coverage.
- `tests/test_recovery_observability.py` — coordinator persistence/error behavior.
- `tests/test_hq_state.py` — recovery projection/defaults.
- `tests/test_hq_api.py` — authenticated API contract and secret exclusion.
- `tests/test_hq_interface.py` and/or `tests/test_ui_redesign.py` — card presence and no mutation controls.
- `tests/test_recovery_security_boundary.py` — regression guard against authority expansion.
- `tests/test_migration_graph.py` — confirm single Alembic head remains intact.

---

### Task 1: Add the durable `RecoveryStatus` model and migration

**Files:**
- Modify: `src/ai_hq/recovery/models.py`
- Create: `migrations/versions/0016_recovery_status.py`
- Modify: `tests/test_recovery_models.py`
- Modify: `tests/test_migration_graph.py`

**Interfaces:**
- Consumes: existing `RecoveryIncidentState` and SQLAlchemy `Base` conventions.
- Produces: `RecoveryStatus` ORM model keyed by `target` with fields `last_probe_at`, `last_result`, `reachable`, `status_code`, `ready`, `consecutive_failures`, `active_incident_id`, `active_incident_state`, and `updated_at`.

- [ ] **Step 1: Write failing model tests**

Add tests equivalent to:

```python
from ai_hq.recovery.models import RecoveryStatus


def test_recovery_status_defaults_are_bounded_and_unknown():
    row = RecoveryStatus(target="dripvid")
    assert row.last_result == "unknown"
    assert row.consecutive_failures == 0
    assert row.reachable is None
    assert row.status_code is None
    assert row.ready is None
    assert row.active_incident_id is None
    assert row.active_incident_state is None
```

Also assert the model exposes no JSON/raw payload field such as `details`, `diagnostics`, `readiness`, or `error_text`.

- [ ] **Step 2: Run the focused model test and verify RED**

Run:

```bash
pytest tests/test_recovery_models.py -q
```

Expected: failure because `RecoveryStatus` does not exist yet.

- [ ] **Step 3: Add the ORM model**

Implement the smallest model matching the spec. Use ordinary scalar columns only. `target` is the primary key. `status_code` is nullable integer. `active_incident_state` uses the existing `recovery_state_type()` helper. Keep `last_result` bounded to `unknown|healthy|unhealthy|error` either with a `StrEnum` plus non-native SQLAlchemy enum or a string constrained in service code; prefer an enum for DB-level consistency.

- [ ] **Step 4: Add migration graph RED test for the next revision**

Update the migration test so the expected head becomes `0016_recovery_status` and verify the new revision has exactly:

```python
down_revision = "0015_mission_leases"
```

Run:

```bash
pytest tests/test_migration_graph.py -q
```

Expected: failure until the migration exists.

- [ ] **Step 5: Create `0016_recovery_status.py`**

Create the `recovery_status` table with the exact model fields and a downgrade that drops only this table. Do not modify existing recovery incident tables.

- [ ] **Step 6: Verify model and migration tests GREEN**

Run:

```bash
pytest tests/test_recovery_models.py tests/test_migration_graph.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ai_hq/recovery/models.py migrations/versions/0016_recovery_status.py tests/test_recovery_models.py tests/test_migration_graph.py
git commit -m "feat: add durable recovery status model"
```

---

### Task 2: Implement `RecoveryStatusService` with strict sanitization

**Files:**
- Create: `src/ai_hq/recovery/status.py`
- Create: `tests/test_recovery_status.py`

**Interfaces:**
- Consumes: `RecoveryStatus`, `RecoveryIncident`, `RecoveryIncidentState`, SQLAlchemy session factory.
- Produces:

```python
class RecoveryStatusService:
    def __init__(self, session_factory): ...

    def record_successful_cycle(
        self,
        *,
        target: str,
        observed_at: datetime,
        summary: Mapping[str, Any],
    ) -> dict: ...

    def record_cycle_error(
        self,
        *,
        target: str,
        observed_at: datetime,
    ) -> dict: ...

    def snapshot(self, target: str) -> dict: ...
```

- [ ] **Step 1: Write failing healthy snapshot test**

Construct an in-memory DB, create `RecoveryStatusService`, call:

```python
service.record_successful_cycle(
    target="dripvid",
    observed_at=observed_at,
    summary={
        "reachable": True,
        "status_code": 200,
        "ready": True,
        "secret": "must-not-persist",
        "raw": {"password": "must-not-persist"},
    },
)
```

Assert `snapshot("dripvid")` returns only the designed keys, `last_result == "healthy"`, no active incident, and no secret/raw values.

- [ ] **Step 2: Run the new test and verify RED**

```bash
pytest tests/test_recovery_status.py -q
```

Expected: import failure because the service is absent.

- [ ] **Step 3: Implement minimal row upsert and snapshot defaults**

`record_successful_cycle()` must:

1. validate only boolean `reachable`, integer 100..599 `status_code` excluding bool, and boolean `ready`;
2. query the active DripVid recovery incident using the same active definition already used by `RecoveryService`;
3. derive `last_result` exactly from the spec;
4. write only the bounded fields;
5. commit once;
6. return `snapshot(target)`.

`snapshot()` must return a stable dictionary even when no row exists:

```python
{
    "last_probe_at": None,
    "last_result": "unknown",
    "reachable": None,
    "status_code": None,
    "ready": None,
    "consecutive_failures": 0,
    "active_incident_id": None,
    "active_incident_state": None,
}
```

- [ ] **Step 4: Add RED tests for active incidents and malformed summary values**

Cover:

```python
{"reachable": "yes", "status_code": True, "ready": 1}
```

Expected persisted bounded values: all `None` and `last_result == "unknown"` unless an active incident exists, in which case `last_result == "unhealthy"`.

Create an active `RecoveryIncident` with `consecutive_failures=2` and assert the snapshot stores only its ID, state value, and count.

- [ ] **Step 5: Implement active incident projection and result derivation**

Do not copy incident diagnostics, verification, escalation reason, mission result, or timestamps other than the status record's own probe/update timestamps.

- [ ] **Step 6: Add RED cycle-error test**

Call:

```python
service.record_cycle_error(target="dripvid", observed_at=observed_at)
```

Assert `last_result == "error"`, probe fields are cleared to `None`, no exception text parameter exists, and active incident metadata may remain projected from the database.

- [ ] **Step 7: Implement cycle-error persistence**

No exception object/string may be accepted or stored.

- [ ] **Step 8: Verify the status service GREEN**

```bash
pytest tests/test_recovery_status.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/ai_hq/recovery/status.py tests/test_recovery_status.py
git commit -m "feat: persist bounded recovery status"
```

---

### Task 3: Persist status from `RecoveryWorkerCoordinator`

**Files:**
- Modify: `src/ai_hq/recovery/bootstrap.py`
- Modify: `tests/test_recovery_observability.py`
- Modify: `tests/test_recovery_worker.py` only if constructor/wiring coverage requires it

**Interfaces:**
- Consumes: `RecoveryStatusService.record_successful_cycle()` and `.record_cycle_error()`.
- Produces: optional status recorder dependency on `RecoveryWorkerCoordinator`; `build_recovery_coordinator()` wires a real recorder.

- [ ] **Step 1: Write failing successful-cycle persistence test**

Use a fake recorder:

```python
class Recorder:
    def __init__(self):
        self.successes = []
        self.errors = []

    def record_successful_cycle(self, **kwargs):
        self.successes.append(kwargs)

    def record_cycle_error(self, **kwargs):
        self.errors.append(kwargs)
```

Construct `RecoveryWorkerCoordinator(cycle, clock=..., status_recorder=recorder)` and assert exactly one success record is written for a due cycle with target `dripvid` and the cycle's bounded summary.

- [ ] **Step 2: Run focused test and verify RED**

```bash
pytest tests/test_recovery_observability.py -q
```

Expected: constructor does not yet accept `status_recorder`.

- [ ] **Step 3: Add optional recorder and successful persistence**

Add an optional protocol/dependency. Preserve old constructor behavior when no recorder is supplied. Use `datetime.now(UTC)` once per due cycle as the observation timestamp and pass that same timestamp to the log/status record where practical.

- [ ] **Step 4: Add skipped-cycle test**

Call the coordinator twice inside the observation interval and assert the second call writes no status row and does not create a new `last_probe_at`.

- [ ] **Step 5: Add cycle-exception RED test**

For a cycle that raises, assert:

- `record_cycle_error(target="dripvid", observed_at=...)` is called once;
- the original `RuntimeError` is still raised;
- exception text is not passed to the recorder;
- existing sanitized `recovery_cycle_failed` log behavior remains.

- [ ] **Step 6: Implement exception recording without altering failure semantics**

Call the recorder before re-raising. If status persistence itself fails, log a fixed sanitized status persistence failure marker and still preserve the original recovery-cycle exception as the primary failure. Do not log persistence exception text.

- [ ] **Step 7: Wire real `RecoveryStatusService` in `build_recovery_coordinator()`**

Use the same `session_factory` already passed to recovery services:

```python
status = RecoveryStatusService(session_factory)
return RecoveryWorkerCoordinator(cycle, clock=clock, status_recorder=status)
```

- [ ] **Step 8: Verify coordinator tests GREEN**

```bash
pytest tests/test_recovery_observability.py tests/test_recovery_worker.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/ai_hq/recovery/bootstrap.py tests/test_recovery_observability.py tests/test_recovery_worker.py
git commit -m "feat: record recovery cycle status"
```

---

### Task 4: Add recovery status to authenticated HQ state

**Files:**
- Modify: `src/ai_hq/hq/state.py`
- Modify: `src/ai_hq/hq/api.py`
- Modify: `tests/test_hq_state.py`
- Modify: `tests/test_hq_api.py`

**Interfaces:**
- Consumes: `RecoveryStatusService.snapshot("dripvid")`, current `Settings.recovery_enabled`, current `Settings.recovery_observe_only`.
- Produces: top-level `payload["recovery"]` in `/api/hq/state`.

- [ ] **Step 1: Write failing HQ state default test**

Instantiate `HQStateService` with a status provider and configuration provider, or with explicit dependencies chosen during implementation, then assert:

```python
snapshot["recovery"] == {
    "enabled": False,
    "observe_only": True,
    "last_probe_at": None,
    "last_result": "unknown",
    "reachable": None,
    "status_code": None,
    "ready": None,
    "consecutive_failures": 0,
    "active_incident_id": None,
    "active_incident_state": None,
}
```

- [ ] **Step 2: Run HQ state tests and verify RED**

```bash
pytest tests/test_hq_state.py -q
```

Expected: no `recovery` key yet.

- [ ] **Step 3: Extend `HQStateService` with focused providers**

Prefer constructor dependencies that keep DB access testable:

```python
HQStateService(
    session_factory,
    *,
    recovery_status_service,
    recovery_settings_provider,
)
```

where the settings provider returns current booleans each snapshot. Do not copy the entire `Settings` object into persisted state.

- [ ] **Step 4: Add API RED test for configured observe-only state**

Use existing `build_client()` with settings set to recovery enabled + observe-only. After login, assert `/api/hq/state` includes:

```python
response.json()["recovery"]["enabled"] is True
response.json()["recovery"]["observe_only"] is True
```

Also insert a `RecoveryStatus` row and verify bounded values appear.

- [ ] **Step 5: Update `install_hq_routes()` wiring**

Construct `RecoveryStatusService(session_factory)` and supply a small settings callback that reads the already-provided current `settings` object:

```python
lambda: {
    "enabled": bool(getattr(settings, "recovery_enabled", False)),
    "observe_only": bool(getattr(settings, "recovery_observe_only", True)),
}
```

Keep the existing authentication check exactly in front of `state.snapshot()`.

- [ ] **Step 6: Add secret-exclusion and read-only regression assertions**

Extend `tests/test_hq_api.py` so helper secret sentinels and raw-body sentinels remain absent even when recovery data is present. Keep the existing POST `405` assertion.

- [ ] **Step 7: Verify HQ state/API GREEN**

```bash
pytest tests/test_hq_state.py tests/test_hq_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ai_hq/hq/state.py src/ai_hq/hq/api.py tests/test_hq_state.py tests/test_hq_api.py
git commit -m "feat: expose read-only recovery status in HQ state"
```

---

### Task 5: Render a non-interactive DripVid Recovery card

**Files:**
- Modify: `src/ai_hq/templates/home.html`
- Modify: `src/ai_hq/static/hq.js`
- Modify: `src/ai_hq/static/hq.css`
- Modify: `tests/test_hq_interface.py`
- Modify: `tests/test_ui_redesign.py` only if its layout contract is the established assertion location

**Interfaces:**
- Consumes: top-level `payload.recovery` from the existing `/api/hq/state` poll.
- Produces: compact recovery card with overall state, mode, last probe, consecutive failures, and active incident details.

- [ ] **Step 1: Write failing template contract test**

Require stable hooks such as:

```html
data-recovery-card
data-recovery-state
data-recovery-mode
data-recovery-last-probe
data-recovery-failures
data-recovery-incident
```

Also assert the recovery card contains no `<button>`, `<form>`, `data-action`, or recovery POST control.

- [ ] **Step 2: Run interface tests and verify RED**

```bash
pytest tests/test_hq_interface.py tests/test_ui_redesign.py -q
```

Expected: missing recovery card hooks.

- [ ] **Step 3: Add minimal read-only card markup**

Place it adjacent to the Delivery Pipeline. Initial server-rendered copy should be safe before the first poll:

```text
DripVid Recovery
Waiting for first probe
Observe only
Last probe: —
Failures: 0
Incident: None
```

No room button semantics; it is not an agent room.

- [ ] **Step 4: Write failing JS contract test or static-source assertions**

Require a `normalizeRecovery`/equivalent function path that:

- accepts only `healthy|unhealthy|error|unknown` results;
- treats malformed booleans/status codes as unknown;
- shortens incident ID only for display;
- writes only through `.textContent`;
- never uses `innerHTML` for recovery fields.

- [ ] **Step 5: Implement recovery normalization/rendering inside the existing poll**

Overall copy rules:

```text
enabled=false                    -> Disabled
last_result=healthy              -> Healthy
last_result=unhealthy            -> Unhealthy
last_result=error                -> Probe error
otherwise                        -> Waiting for first probe
```

Mode rules:

```text
observe_only=true  -> Observe only
observe_only=false -> Active recovery configured
```

Use `new Date(last_probe_at)` only when valid; otherwise display `—`. Do not substitute browser refresh time.

- [ ] **Step 6: Add CSS for bounded state presentation**

Reuse existing visual language where practical. Keep selectors scoped under the recovery card. Do not alter room positioning/state behavior unrelated to this feature.

- [ ] **Step 7: Verify UI contract GREEN**

```bash
pytest tests/test_hq_interface.py tests/test_ui_redesign.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ai_hq/templates/home.html src/ai_hq/static/hq.js src/ai_hq/static/hq.css tests/test_hq_interface.py tests/test_ui_redesign.py
git commit -m "feat: show DripVid recovery status in HQ"
```

---

### Task 6: Add explicit security-boundary regression coverage

**Files:**
- Modify: `tests/test_recovery_security_boundary.py`
- Test: `src/ai_hq/recovery/status.py`, `src/ai_hq/hq/state.py`, `src/ai_hq/hq/api.py`, `src/ai_hq/static/hq.js`, `src/ai_hq/templates/home.html`

**Interfaces:**
- Consumes: completed observability implementation.
- Produces: automated guard that this milestone adds no production mutation authority.

- [ ] **Step 1: Write security assertions**

Read source text and fail if recovery status/presentation files introduce any of these production-authority tokens/imports:

```python
for forbidden in (
    "subprocess",
    "os.system",
    "service.recover",
    "service_restart",
    "docker",
    "systemctl",
    "deploy/",
    "HostHelperOperationalTransport",
    "ServiceRecoverAdapter",
):
    assert forbidden not in status_and_hq_observability_source
```

Keep allowances precise: existing unrelated files may legitimately contain some tokens, so scope assertions only to the new status/presentation paths.

- [ ] **Step 2: Add UI mutation-control assertions**

Assert the recovery card has no form action, POST fetch, recovery button, or click handler capable of issuing a mutation request.

- [ ] **Step 3: Run security test**

```bash
pytest tests/test_recovery_security_boundary.py -q
```

Expected: PASS only when the completed implementation has no authority expansion.

- [ ] **Step 4: Commit**

```bash
git add tests/test_recovery_security_boundary.py
git commit -m "test: guard recovery observability boundary"
```

---

### Task 7: Full verification and exact-SHA CI gate

**Files:**
- No production file changes expected unless verification reveals a defect.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: merge-ready branch evidence.

- [ ] **Step 1: Run formatting/lint checks**

Use the repository's CI-equivalent commands from `pyproject.toml`/workflow. At minimum:

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 2: Run focused recovery/HQ tests**

```bash
pytest \
  tests/test_recovery_models.py \
  tests/test_recovery_status.py \
  tests/test_recovery_observability.py \
  tests/test_recovery_worker.py \
  tests/test_hq_state.py \
  tests/test_hq_api.py \
  tests/test_hq_interface.py \
  tests/test_ui_redesign.py \
  tests/test_recovery_security_boundary.py \
  tests/test_migration_graph.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete test suite**

```bash
pytest -q
```

Expected: all tests PASS with no failures/skips newly introduced by this feature.

- [ ] **Step 4: Validate Compose**

```bash
docker compose config >/dev/null
```

Expected: exit 0.

- [ ] **Step 5: Inspect the final authority diff**

```bash
git diff main...HEAD -- \
  src/ai_hq/recovery \
  src/ai_hq/hq \
  src/ai_hq/templates/home.html \
  src/ai_hq/static/hq.js \
  src/ai_hq/static/hq.css \
  migrations \
  tests
```

Confirm there is no new recover/restart/deploy/Host Helper mutation path and no raw diagnostic persistence.

- [ ] **Step 6: Push branch and capture exact HEAD SHA**

```bash
git rev-parse HEAD
git push -u origin feature/recovery-status-observability
```

Record the exact SHA returned by `git rev-parse HEAD`.

- [ ] **Step 7: Verify GitHub Actions against that exact SHA**

Do not rely on branch name alone. Confirm CI run SHA equals the recorded HEAD and all required jobs are green: install, lint, tests, and Compose validation.

- [ ] **Step 8: Review merge diff and merge only after green CI**

Use a normal non-force merge/fast-forward path according to current repo state. Do not deploy from an unverified branch SHA.

---

### Task 8: Production rollout verification without changing recovery authority

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: merged, green main SHA.
- Produces: production evidence that the new read-only recovery status works while observe-only remains enabled.

- [ ] **Step 1: Deploy the exact merged main SHA using the existing release process**

Use the repository's current `deploy/ai-hq-deploy` flow and existing smoke checker. Do not alter recovery environment values during deployment.

- [ ] **Step 2: Run production smoke checks**

```bash
sudo bash /opt/ai-hq/current/deploy/check-production.sh
```

Expected: DripVid root, AI HQ login/liveness/readiness/local readiness, Host Helper authenticated health, and worker-only Host Helper isolation all pass.

- [ ] **Step 3: Verify recovery environment remains observe-only**

Confirm production still reports:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

If observe-only is not true, stop and do not proceed with any active-recovery test.

- [ ] **Step 4: Verify authenticated HQ state payload**

Using the normal authenticated administrator session, confirm `/api/hq/state` contains `recovery` with a recent `last_probe_at`, bounded health values, and `observe_only: true`.

- [ ] **Step 5: Verify Operations Floor presentation**

Confirm the DripVid Recovery card appears, has no action controls, and reflects the same bounded values as the API.

- [ ] **Step 6: Stop at the next approval gate**

Do not simulate a real production outage and do not enable active recovery. The next milestone is a separately designed controlled failure simulation while observe-only remains enabled.

---

## Self-Review Results

- **Spec coverage:** Durable persistence, sanitized recording, coordinator integration, current config overlay, authenticated API, read-only UI, error handling, security boundaries, migration, CI, rollout, and explicit follow-up gate are all mapped to tasks.
- **Placeholder scan:** No TBD/TODO/"implement later" steps remain; each task names concrete files, interfaces, commands, and expected outcomes.
- **Type consistency:** `RecoveryStatusService.record_successful_cycle`, `record_cycle_error`, and `snapshot` signatures are consistent across service, coordinator, and HQ tasks. Recovery API keys match the approved design exactly.
- **Scope check:** Controlled failure simulation is intentionally excluded and remains a separate milestone.
