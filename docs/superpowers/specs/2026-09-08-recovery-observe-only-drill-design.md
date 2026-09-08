# AI HQ Observe-Only Recovery Drill Design

## Purpose

Add a one-shot internal diagnostic drill that proves AI HQ can detect and persist a simulated DripVid application failure, surface the incident through existing recovery observability, and then return to healthy status without interrupting DripVid or entering any real recovery mutation path.

The drill is an operator diagnostic, not a new recovery feature. It must not broaden production authority.

## Scope

The drill covers only the DripVid `app` recovery component and only the existing observe-only recovery path. It will exercise:

1. synthetic unhealthy readiness observation;
2. recovery incident creation/update;
3. consecutive failure threshold handling;
4. bounded recovery status persistence;
5. HQ state/UI visibility through the existing recovery card;
6. clean exit without creating a recovery mission or invoking any mutation tool;
7. subsequent resolution by the normal real healthy observation cycle.

The drill does not test or authorize real automatic recovery.

## Safety Invariants

The drill must fail closed unless every invariant below is true:

- `recovery_enabled` is true.
- `recovery_observe_only` is true.
- operating mode is not freeze.
- no active recovery incident already exists for any DripVid component.
- the target is fixed to `dripvid` and the component is fixed to `app`.
- no caller-supplied URL, service name, host, component, command, tool, or mutation target is accepted.
- no recovery approval is created, consumed, or bypassed.
- no `service.recover`, `service_restart`, Docker, systemd, deployment, shell, subprocess, or Host Helper mutation capability is imported or called.
- no DripVid process, container, service, network path, readiness endpoint, media path, or host configuration is modified.
- no existing real incident is overwritten, resolved, or merged into the drill.

If any precondition fails, the drill exits without writing a synthetic incident.

## Recommended Architecture

Introduce a focused internal module:

`src/ai_hq/recovery/drill.py`

It contains a `RecoveryDrillService` that depends only on the existing recovery persistence/status services and an injected clock/sleep abstraction for testability. The drill does not call the production readiness probe and does not alter `RecoveryWorkerCoordinator` behavior.

The service runs a bounded sequence of synthetic observations that mirrors what the normal recovery observer would persist for an unhealthy DripVid application. It uses the existing `RecoveryService.observe_failure()` and `RecoveryStatusService.record_successful_cycle()` APIs so the same durable incident/status records are exercised.

The synthetic readiness summary is fixed in code:

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

No arbitrary payload is accepted.

## Drill Sequence

### 1. Preconditions

Load current `Settings` and verify:

- recovery enabled;
- observe-only enabled;
- non-freeze operating mode.

Query all existing active DripVid recovery incidents. If any exist, abort with a fixed operator-safe reason such as `active_incident_present`.

### 2. Create Synthetic Failure Observations

Use the configured recovery failure threshold and observation interval.

For each synthetic observation:

- call `RecoveryService.observe_failure("app", diagnostics={"drill": True})`;
- persist the bounded recovery status using `RecoveryStatusService.record_successful_cycle()` with the fixed unhealthy summary;
- do not invoke `RecoveryObserver.create_recovery_mission()`;
- do not call policy mutation execution paths.

The drill waits between observations using an injected sleeper so production timing respects the normal observation interval and tests can use a no-op sleeper.

The number of observations is exactly the configured failure threshold. This proves the incident can reach the same persistent-failure count that would normally make recovery policy relevant, while observe-only remains enforced.

### 3. Verify Durable Drill Result

After the final observation, read the persisted recovery status and active incident and require:

- `last_result == "unhealthy"`;
- `ready is False`;
- active incident exists;
- active incident component is `app`;
- consecutive failures are at least the configured threshold;
- no recovery mission ID exists;
- no recovery attempts were created by the drill.

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

## Exit and Recovery

The drill intentionally leaves the synthetic incident active so the existing live recovery worker can prove the second half of the path: a normal healthy DripVid observation should resolve the synthetic incident through the already-deployed recovery logic.

The drill itself must not force-resolve the incident because that would bypass the real healthy observation path we want to verify.

Operator verification after the drill should confirm the HQ Recovery card transitions:

`Healthy -> Unhealthy / active incident -> Healthy`

If the normal worker does not resolve the synthetic incident after healthy observations, stop and investigate. Do not manually trigger real recovery.

## Invocation Surface

Add a one-shot CLI module executable only from inside the AI HQ worker container, for example:

```bash
python -m ai_hq.recovery.drill
```

The CLI accepts no target/component/URL/command arguments. Optional `--json` may be supported solely to format the bounded result for operator verification.

There is deliberately:

- no HTTP endpoint;
- no UI button;
- no recurring scheduler;
- no Host Helper capability;
- no recovery permission or approval change.

This keeps the drill unavailable to ordinary HQ web users and avoids permanent production attack surface.

## Concurrency and Idempotency

The drill is single-run and fail-closed.

Before the first synthetic observation and again before each subsequent one, verify that the active incident is either absent on the first pass or is the exact incident created by this drill. If a different incident appears, abort immediately.

Use a drill marker only inside bounded recovery diagnostics (`{"drill": True}`) and never as authority. The incident ID remains the durable identity for the run.

Repeated invocation while the synthetic incident remains active must fail with `active_incident_present`. A new drill may only start after the normal worker has resolved the previous incident.

## Error Handling

All operator-visible errors use fixed bounded codes/messages. Internal exception text is not printed or persisted by the drill.

Examples:

- `recovery_disabled`
- `observe_only_required`
- `freeze_mode`
- `active_incident_present`
- `drill_incident_changed`
- `status_verification_failed`

Unexpected exceptions produce a generic `drill_failed` result and non-zero exit status without exposing exception text.

## Testing

Use TDD and cover at minimum:

- refuses to run when recovery is disabled;
- refuses to run when observe-only is false;
- refuses in freeze mode;
- refuses when any real active DripVid incident exists;
- uses only fixed target `dripvid` and component `app`;
- creates exactly the threshold number of synthetic failure observations;
- respects configured observation interval through injected sleeper;
- persists unhealthy bounded recovery status;
- reaches threshold consecutive failures;
- creates no recovery mission;
- creates no recovery attempt;
- accepts no arbitrary target/URL/command input;
- returns no raw diagnostic or secret values;
- repeated invocation with active drill incident fails closed;
- security-boundary regression rejects mutation imports/calls.

The full existing test suite, Ruff, Compose validation, and exact-SHA GitHub Actions verification remain required before merge.

## Production Rollout

Deployment follows the existing guarded AI HQ release process.

After deployment, verify production still has:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

Then run the drill once from the worker container. Confirm:

1. DripVid remains continuously reachable and untouched;
2. HQ Recovery card shows the synthetic unhealthy incident;
3. no recovery mission/attempt is created;
4. normal healthy recovery observations resolve the incident;
5. HQ Recovery card returns to healthy.

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
- change recovery thresholds, cooldowns, budgets, or policy decisions.
