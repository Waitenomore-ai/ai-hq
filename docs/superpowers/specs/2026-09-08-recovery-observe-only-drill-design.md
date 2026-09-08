# AI HQ Observe-Only Recovery Drill Design

## Purpose

Add a one-shot internal diagnostic drill that proves AI HQ can persist and surface a simulated DripVid application failure, then lets the normal live recovery worker prove the healthy-resolution path, without interrupting DripVid or entering any real recovery mutation path.

The drill is an operator diagnostic, not a new recovery feature. It must not broaden production authority.

## Scope

The drill covers only the DripVid `app` recovery component and only the existing observe-only recovery path. It will exercise:

1. guarded synthetic incident injection at the configured persistent-failure threshold;
2. bounded recovery status persistence;
3. HQ state/UI visibility through the existing recovery card;
4. clean exit without creating a recovery mission or invoking any mutation tool;
5. subsequent resolution by the normal real healthy observation cycle.

The drill does not test or authorize real automatic recovery. It also does not pretend to prove the live readiness probe can fail; that path is already covered by the ordinary recovery worker and unit/integration tests. This drill specifically proves the durable incident/status/UI and healthy-resolution path in production.

## Safety Invariants

The drill must fail closed unless every invariant below is true:

- `recovery_enabled` is true.
- `recovery_observe_only` is true.
- operating mode is not freeze.
- the latest durable DripVid recovery status is healthy.
- the latest healthy probe is recent enough to create a safe visibility window before the next normal worker cycle.
- no active recovery incident already exists for any DripVid component.
- the target is fixed to `dripvid` and the component is fixed to `app`.
- no caller-supplied URL, service name, host, component, command, tool, threshold, or mutation target is accepted.
- no recovery approval is created, consumed, or bypassed.
- no `service.recover`, `service_restart`, Docker, systemd, deployment, shell, subprocess, or Host Helper mutation capability is imported or called.
- no DripVid process, container, service, network path, readiness endpoint, media path, or host configuration is modified.
- no existing real incident is overwritten, resolved, or merged into the drill.

If any precondition fails, the drill exits without writing a synthetic incident.

## Recommended Architecture

Introduce a focused internal module:

`src/ai_hq/recovery/drill.py`

It contains a `RecoveryDrillService` that depends only on the SQLAlchemy session factory, current `Settings`, and the existing bounded `RecoveryStatusService` snapshot contract. It does not call the production readiness probe and does not alter `RecoveryWorkerCoordinator` behavior.

The drill performs one atomic diagnostic injection: it creates a `RecoveryIncident` for `dripvid:app` in `suspect` state with `consecutive_failures` set exactly to the configured `recovery_failure_threshold`, then writes the bounded recovery status as unhealthy. This deliberately avoids waiting between synthetic observations, because the normal healthy worker would otherwise race the drill and resolve the synthetic incident between steps.

The injection is not a production detection algorithm. It is a controlled diagnostic fixture persisted into the real recovery tables so the already-deployed observability and healthy-resolution paths can be verified safely.

## Fresh-Healthy Window

Before creating the drill incident, the service reads `RecoveryStatusService.snapshot("dripvid")` and requires:

- `last_result == "healthy"`;
- `ready is True`;
- no active incident metadata;
- `last_probe_at` is present;
- the probe age is no more than a fixed safe limit.

The safe limit is fixed in code to 5 seconds and is not caller-configurable. If the latest healthy probe is older than 5 seconds, the command exits with `fresh_healthy_probe_required` and the operator can retry after the next normal worker heartbeat.

This gives the synthetic incident most of the normal 30-second observation interval to be visible in HQ before the next healthy cycle resolves it, without pausing or modifying the worker.

## Atomic Drill Injection

Inside one database transaction:

1. Re-check there is no active recovery incident for any DripVid component.
2. Create exactly one `RecoveryIncident` with:
   - `active_key="dripvid:app"`;
   - `target="dripvid"`;
   - `component="app"`;
   - `state=RecoveryIncidentState.SUSPECT`;
   - `consecutive_failures=settings.recovery_failure_threshold`;
   - `first_failure_at=now`;
   - `last_failure_at=now`;
   - `last_observed_at=now`;
   - `diagnostics={"drill": True}`;
   - `verification={}`;
   - no recovery mission ID;
   - no recovery attempt.
3. Commit the incident.
4. Persist the bounded status using the existing `RecoveryStatusService.record_successful_cycle()` with this fixed summary:

```python
{
    "reachable": True,
    "status_code": 503,
    "ready": False,
    "incident_detected": True,
    "incident_resolved": False,
    "worked": True,
}
```

No arbitrary readiness payload is accepted.

Because the status service projects the active incident from the database, the resulting snapshot should report unhealthy status, the synthetic incident ID/state, and threshold consecutive failures.

## Durable Verification

After injection, read the persisted recovery status and incident and require:

- `last_result == "unhealthy"`;
- `ready is False`;
- active incident exists;
- active incident component is `app`;
- consecutive failures equal the configured threshold;
- no recovery mission ID exists;
- no `RecoveryAttempt` rows exist for the incident.

Return only bounded operator-facing fields:

```python
{
    "ok": True,
    "target": "dripvid",
    "component": "app",
    "incident_id": "...",
    "incident_state": "suspect",
    "consecutive_failures": 3,
    "status": "unhealthy",
    "observe_only": True,
}
```

No diagnostics, logs, readiness body, credentials, URLs, host paths, exception text, or environment values are returned.

## Exit and Normal Resolution

The drill intentionally leaves the synthetic incident active. The existing live recovery worker then performs a real healthy DripVid observation. Its already-deployed healthy path should resolve the synthetic incident and update the durable Recovery Status back to healthy.

The drill itself must not force-resolve the incident because that would bypass the normal healthy observation path we want to verify.

Operator verification should confirm the HQ Recovery card transitions:

`Healthy -> Unhealthy / active incident -> Healthy`

If the normal worker does not resolve the synthetic incident after healthy observations, stop and investigate. Do not manually trigger real recovery.

## Invocation Surface

Add a one-shot CLI module executable only from inside the AI HQ worker container:

```bash
python -m ai_hq.recovery.drill
```

The CLI accepts no target/component/URL/command/threshold arguments. Optional `--json` may be supported solely to format the bounded result for operator verification.

There is deliberately:

- no HTTP endpoint;
- no UI button;
- no recurring scheduler;
- no Host Helper capability;
- no recovery permission or approval change.

This keeps the drill unavailable to ordinary HQ web users and avoids permanent production attack surface.

## Concurrency and Idempotency

The drill is single-run and fail-closed.

The active-incident check is performed both before entering the transaction and again inside the transaction. The existing unique `active_key` constraint provides an additional database guard against duplicate `dripvid:app` incidents.

Repeated invocation while the synthetic incident remains active must fail with `active_incident_present`. A new drill may only start after the normal worker has resolved the previous incident and a fresh healthy status has been recorded.

If a different incident appears between the pre-check and transaction, the injection must fail rather than modifying that incident.

## Error Handling

All operator-visible errors use fixed bounded codes/messages. Internal exception text is not printed or persisted by the drill.

Examples:

- `recovery_disabled`
- `observe_only_required`
- `freeze_mode`
- `active_incident_present`
- `healthy_status_required`
- `fresh_healthy_probe_required`
- `drill_conflict`
- `status_verification_failed`

Unexpected exceptions produce a generic `drill_failed` result and non-zero exit status without exposing exception text.

## Testing

Use TDD and cover at minimum:

- refuses to run when recovery is disabled;
- refuses to run when observe-only is false;
- refuses in freeze mode;
- refuses when durable status is not healthy;
- refuses when the healthy probe is older than 5 seconds;
- refuses when any real active DripVid incident exists;
- uses only fixed target `dripvid` and component `app`;
- creates exactly one synthetic incident at the configured threshold;
- persists unhealthy bounded recovery status;
- creates no recovery mission;
- creates no recovery attempt;
- accepts no arbitrary target/URL/command/threshold input;
- returns no raw diagnostic or secret values;
- repeated invocation with active drill incident fails closed;
- simulated database race/uniqueness conflict fails closed;
- existing normal healthy recovery cycle resolves the drill incident in an integration test;
- security-boundary regression rejects mutation imports/calls.

The full existing test suite, Ruff, Compose validation, and exact-SHA GitHub Actions verification remain required before merge.

## Production Rollout

Deployment follows the existing guarded AI HQ release process.

After deployment, verify production still has:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

Then:

1. Confirm DripVid is healthy.
2. Wait for a fresh healthy Recovery Status heartbeat if needed.
3. Run the drill once from the worker container.
4. Confirm DripVid remains continuously reachable and untouched.
5. Confirm HQ Recovery card shows the synthetic unhealthy incident.
6. Confirm no recovery mission or attempt was created.
7. Confirm the next normal healthy recovery observation resolves the incident.
8. Confirm HQ Recovery card returns to healthy.

Stop after this verification. Do not disable observe-only or authorize real recovery as part of this milestone.

## Non-Goals

This milestone does not:

- enable active automatic recovery;
- grant `service.recover`;
- add or consume recovery approvals;
- simulate database/storage failures;
- stop/restart DripVid;
- alter Host Helper capabilities;
- add a web/API simulation control;
- test production mutation execution;
- change recovery thresholds, cooldowns, budgets, or policy decisions;
- replace or modify the real DripVid readiness probe.
