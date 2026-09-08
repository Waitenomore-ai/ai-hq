# AI HQ Recovery Status Observability Design

## Status

Approved in chat on 2026-09-07 for implementation planning. This design adds read-only recovery visibility only. It does not grant recovery authority, change recovery policy, or disable observe-only mode.

## Context

AI HQ already has a production recovery observation loop for DripVid. `DripVidRecoveryCycle` records a bounded `last_summary` containing reachability, HTTP status, readiness, incident-detected/resolved flags, and whether the cycle reported work. `RecoveryWorkerCoordinator` emits a sanitized structured heartbeat from that summary. The Operations Floor already polls `/api/hq/state` every 10 seconds.

The missing capability is durable, read-only presentation of the latest recovery condition after the worker cycle finishes. Logs alone are not an adequate operator surface, and in-memory `last_summary` is lost across worker restarts and is not visible to the web process.

## Goal

Show a compact DripVid recovery status on the AI HQ Operations Floor with:

- last probe time;
- last result;
- last known reachability/readiness and bounded HTTP status;
- consecutive failure count;
- active incident ID and state when one exists;
- recovery enabled state;
- observe-only state.

The status must survive worker restarts, remain safe to expose to an authenticated administrator, and add no mutation path.

## Non-goals

This milestone does not:

- enable active automatic recovery;
- grant `service.recover` to any agent;
- create or consume scoped recovery approval;
- add a restart/recover/deploy button;
- change failure thresholds, cooldowns, budgets, or incident policy;
- expose raw readiness payloads, service logs, exceptions, credentials, URLs, host paths, or diagnostic text;
- simulate a failure. Controlled failure simulation is a separate follow-up milestone.

## Architecture

### 1. Durable recovery-status record

Add a small database model dedicated to the latest operator-facing recovery observation. Use one row per recovery target, initially only `dripvid`.

Proposed model: `RecoveryStatus` in `src/ai_hq/recovery/models.py`.

Fields:

- `target: str` — primary key, currently `dripvid`;
- `last_probe_at: datetime | None`;
- `last_result: str` — one of `unknown`, `healthy`, `unhealthy`, `error`;
- `reachable: bool | None`;
- `status_code: int | None` — only a validated HTTP status code;
- `ready: bool | None`;
- `consecutive_failures: int` — zero when there is no active incident;
- `active_incident_id: str | None`;
- `active_incident_state: RecoveryIncidentState | None`;
- `updated_at: datetime`.

`recovery_enabled` and `observe_only` are intentionally not persisted. They are current configuration and must be overlaid by the authenticated HQ state endpoint so the UI cannot show stale configuration after a restart or config change.

A new Alembic migration must extend the current single migration chain. At implementation time, the executor must verify the latest migration head before naming the revision; based on the approved design baseline, the expected predecessor is `0015_mission_leases`.

### 2. RecoveryStatusService

Add `src/ai_hq/recovery/status.py` with a focused `RecoveryStatusService` responsible only for persisting and reading the bounded status record.

Public interface:

```python
class RecoveryStatusService:
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

The service must not persist arbitrary values from the probe. It whitelists only `reachable`, validated `status_code`, and `ready` from the cycle summary.

For a successful cycle it also queries the durable recovery incident records for the active DripVid incident, if any, and stores only:

- active incident ID;
- active incident state;
- consecutive failure count.

If no active incident exists, these values become `None`, `None`, and `0`.

`last_result` is derived as:

- `healthy` when `ready is True` and there is no active incident;
- `unhealthy` when `ready is False` or an active incident exists;
- `unknown` when the bounded summary cannot establish health;
- `error` only when the cycle raises before a successful summary can be recorded.

No exception text is stored.

### 3. Worker/coordinator integration

`RecoveryWorkerCoordinator` remains the interval gate and existing heartbeat logger. It gains an optional status recorder dependency so existing unit tests and isolated callers remain easy to construct.

On each due successful cycle:

1. run the existing `DripVidRecoveryCycle` unchanged in authority;
2. read its already-sanitized `last_summary`;
3. emit the existing bounded heartbeat;
4. persist the bounded status snapshot.

If the cycle raises:

1. preserve the current fail behavior and sanitized `recovery_cycle_failed` log;
2. persist only `last_probe_at` and `last_result=error` plus cleared probe fields;
3. re-raise exactly as today.

`build_recovery_coordinator()` wires `RecoveryStatusService` using the same database session factory already used by recovery.

This integration must not import or call ToolGateway, Host Helper mutation capabilities, service restart helpers, Docker, systemd, shell execution, or deployment code.

### 4. Authenticated HQ state API

Extend `HQStateService` to include a top-level `recovery` object in `/api/hq/state`.

`HQStateService` should receive the current recovery configuration values at snapshot time or receive a small callback/provider so the response contains current:

- `enabled`;
- `observe_only`.

The persisted recovery snapshot supplies:

- `last_probe_at`;
- `last_result`;
- `reachable`;
- `status_code`;
- `ready`;
- `consecutive_failures`;
- `active_incident_id`;
- `active_incident_state`.

When there is no status row yet, the API returns a stable default rather than omitting the object:

```json
{
  "enabled": false,
  "observe_only": true,
  "last_probe_at": null,
  "last_result": "unknown",
  "reachable": null,
  "status_code": null,
  "ready": null,
  "consecutive_failures": 0,
  "active_incident_id": null,
  "active_incident_state": null
}
```

The existing administrator authentication on `/api/hq/state` remains unchanged. No new write endpoint is added.

### 5. Operations Floor UI

Add one compact, non-interactive `DripVid Recovery` status card to the Operations Floor, visually adjacent to the existing Delivery Pipeline rather than pretending recovery is an agent room.

The card shows:

- overall state: Healthy / Unhealthy / Probe error / Waiting for first probe / Disabled;
- mode: Observe only / Active recovery configured;
- last probe time;
- consecutive failures;
- active incident state and shortened incident identifier when present.

The card contains no buttons and no click action that can mutate state.

`src/ai_hq/static/hq.js` continues to use the existing 10-second `/api/hq/state` polling loop. It adds a bounded normalizer and renderer for the `recovery` object. Unknown or malformed values render as `Unknown`; they must never be inserted as HTML. Existing DOM/textContent patterns remain the standard.

`src/ai_hq/static/hq.css` adds only styles needed for the compact card and its state presentation. Existing floor-room state semantics remain unchanged.

## Data flow

```text
Host Helper readiness probe
        ↓
DripVidRecoveryCycle
        ↓ bounded last_summary
RecoveryWorkerCoordinator
        ├── sanitized heartbeat log
        └── RecoveryStatusService
                ↓
          recovery_status DB row
                ↓
HQStateService + current Settings
                ↓ authenticated
          GET /api/hq/state
                ↓ existing 10 s poll
          Operations Floor card
```

## Error handling and staleness

- A cycle exception produces `last_result=error` without storing exception text.
- A missing row means `unknown`, not healthy.
- A disabled recovery loop remains visibly `Disabled`; the last historical probe may still be returned, but the UI's overall state is Disabled so historical data cannot be mistaken for a current heartbeat.
- The UI must show the actual `last_probe_at`; it must not invent a fresh timestamp from the browser poll time.
- This milestone does not introduce a separate stale-time threshold. Operators can see the exact last probe time, and a later milestone may add explicit stale classification if evidence shows it is needed.

## Security boundaries

The implementation must preserve all existing recovery safety boundaries:

- no new `service.recover` permission;
- no scoped approval creation/consumption;
- no mutation endpoint;
- no Host Helper mutation call;
- no direct shell, subprocess, Docker, systemd, or deploy imports in recovery status/UI code;
- no raw readiness payload, logs, environment, credentials, URLs, paths, or exception messages in the durable status row or API response;
- administrator authentication remains required for `/api/hq/state`.

The recovery status service is a database writer only for bounded observability state. It does not perform recovery.

## Testing strategy

Implementation follows TDD and adds coverage in these areas:

1. **Model/migration** — migration chain stays single-headed; defaults and nullable fields match the design.
2. **Status service** — healthy, unhealthy, active-incident, cleared-incident, unknown summary, and cycle-error snapshots persist only whitelisted data.
3. **Coordinator** — successful due cycles persist a status record; skipped cycles do not manufacture a fresh probe time; exceptions persist `error` without swallowing the exception.
4. **HQ state/API** — authenticated state includes stable recovery payload and current `enabled`/`observe_only`; unauthenticated behavior remains 401.
5. **UI** — template contains the read-only recovery card; JavaScript maps valid/malformed payloads safely; no recovery action/control exists.
6. **Security regression** — recovery status and HQ presentation files contain no new production mutation authority/import path.
7. **Full suite/CI** — lint, tests, migration graph, and Compose validation remain green before merge.

## Rollout

1. Implement on `feature/recovery-status-observability` from the verified main baseline.
2. Verify exact branch SHA in CI.
3. Review diff specifically for authority expansion and migration correctness.
4. Merge only after green CI.
5. Deploy through the existing AI HQ deployment process.
6. Run normal production smoke checks.
7. Confirm `/api/hq/state` reports recovery in observe-only mode and the Operations Floor displays a recent healthy probe.

Deployment must not change `AI_HQ_RECOVERY_OBSERVE_ONLY=true` or grant recovery execution authority.

## Follow-up milestone

After this telemetry surface is production-proven, design a separate controlled simulated-failure test while observe-only remains enabled. That milestone must prove detection, incident creation, and escalation without mutating DripVid production.