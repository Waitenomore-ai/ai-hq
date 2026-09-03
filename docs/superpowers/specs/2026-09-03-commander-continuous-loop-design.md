# Commander Continuous Task Loop — Design

Date: 2026-09-03
Status: Approved design pending implementation plan

## Purpose

Turn AI HQ's existing worker and DepartmentRunner into a production-grade, queue-driven autonomous Commander loop without giving Commander permission to invent new missions.

The goal of this phase is for trusted sources to create missions and for the AI HQ worker to process those missions continuously, safely, visibly, and one at a time. This phase does not add new mutation capabilities, proactive mission creation, parallel execution, or a new scheduler service.

## Existing foundation

AI HQ already has:

- a durable Mission model and mission lifecycle;
- ordered queued mission selection through `MissionService.oldest_queued()`;
- a `DepartmentRunner.run_once()` primitive that routes a queued mission through Commander, assigns the department owner, executes SysAdmin work, and transitions the mission to `COMPLETED`, `WAITING_APPROVAL`, or `FAILED`;
- a worker container that already loops around `run_once()` and sleeps when no work exists;
- PostgreSQL-backed runtime `SystemState`;
- the Safety Engine, approvals, Operations Ledger, Agent Registry, and Host Helper;
- production-proven read-only host execution;
- a corrected host model where DripVid is a systemd/log target and is not a Docker container.

This phase hardens and formalizes the existing worker loop instead of introducing a second orchestrator.

## Scope

### In scope

1. Queue-driven autonomous execution only.
2. One active `RUNNING` mission at a time.
3. Runtime safety decisions based on durable PostgreSQL `SystemState`.
4. Fail-closed behavior when runtime state is missing or invalid.
5. Safe restart recovery for interrupted `RUNNING` missions.
6. Recovery of stale Commander/SysAdmin agent `WORKING` state.
7. `WAITING_APPROVAL` missions are parked and do not block later queued work.
8. Unsupported or failed missions do not terminate the worker loop.
9. Minimal orchestration-level ledger visibility without idle-loop spam.
10. Remove the stale DripVid Docker permission from worker-side Host Helper allow-lists.
11. Production acceptance first in Simulation Mode, then one real read-only mission.

### Out of scope

- Commander creating missions on its own.
- recurring schedules or trigger-created missions;
- parallel/concurrent mission execution;
- Redis as mission ownership or source of truth;
- new mutation/write capabilities;
- new service/container for orchestration;
- richer HQ animation or dashboard redesign;
- automatic retry of interrupted external actions;
- priority-based queue ordering.

## Architectural decision

Keep the existing `worker` container as the only autonomous mission executor.

The worker polls approximately every five seconds. On every execution cycle it reads the durable runtime `SystemState` from PostgreSQL before deciding whether work may proceed.

PostgreSQL remains the source of truth for mission ownership and runtime operating state. Redis may remain a health/dependency check, but it does not determine which mission is claimed or running.

## Runtime operating modes

### Freeze

When runtime `SystemState.operating_mode` is `freeze`, the worker must not claim or execute queued missions.

If the `SystemState` row is missing, malformed, or contains an invalid operating mode, the worker must behave as if the system is in Freeze. It must not guess, fall back to the startup environment, or execute work.

### Safe and Normal

When runtime state is valid and the operating mode is `safe` or `normal`, the worker may process queued missions subject to the existing Safety Engine and approval rules.

Startup environment validation remains fail-closed and unchanged. Startup configuration still requires production-safe defaults. The ongoing execution authority, however, is the durable database state.

## Queue semantics

### Queue source

The worker processes only missions already present in the durable mission queue. Those missions may be created by the user, the current UI/API, or future trusted schedules/triggers.

Commander must not create new maintenance or diagnostic missions in this phase.

### Ordering

Queued missions remain oldest-first using the existing `MissionService.oldest_queued()` behavior.

Priority-based scheduling is deliberately deferred.

### Single-mission execution

At most one mission may be in `RUNNING` state at a time.

Before starting a queued mission, the orchestration layer must check for an existing `RUNNING` mission. If one exists during normal operation, the worker must not start another mission.

`WAITING_APPROVAL` is considered parked, not active. A parked approval mission does not block later queued safe work.

`PAUSED`, `COMPLETED`, `FAILED`, and `CANCELLED` do not block the queue.

## Mission execution flow

For each runnable queued mission:

1. Read and validate runtime `SystemState`.
2. If execution is frozen or runtime state is invalid, execute nothing.
3. Confirm no other mission is currently `RUNNING`.
4. Select the oldest queued mission.
5. Mark Commander `WORKING` while routing.
6. Route using the existing deterministic Commander route.
7. If unsupported, fail that mission with a bounded `unsupported_mission` error and continue the worker loop later.
8. Assign the routed owner while the mission is still queued.
9. Transition the mission to `RUNNING`.
10. Mark the destination agent `WORKING`.
11. Execute through the existing department service and Safety Engine.
12. Transition to one of:
    - `COMPLETED` with result;
    - `WAITING_APPROVAL` when approval is required;
    - `FAILED` with bounded error state.
13. Return active agents to `IDLE` and clear their current mission IDs.
14. Continue polling for later work.

No new path may bypass the existing Safety Engine, approval logic, Host Helper contract, or Operations Ledger.

## Restart and crash recovery

Automatic replay of interrupted external actions is not safe for v1.

On worker startup, if one or more missions are found in `RUNNING` state, the worker must treat them as interrupted work. Each interrupted mission must be moved to `PAUSED` with an explicit recovery reason such as:

`worker_restart_recovery_required`

The worker must not call the department executor for those missions during recovery and must not assume whether the previous external action completed.

This is intentionally conservative and prevents duplicate host actions after a crash or container restart.

After interrupted missions are paused, the worker may resume processing other queued missions.

The recovery operation must be ledgered through the normal mission status transition path.

## Agent state recovery

The Agent Registry can retain stale `WORKING` state after a process crash because the normal `finally` cleanup may never run.

On worker startup, Commander and SysAdmin agent records that are still marked `WORKING` from a previous process must be reset to `IDLE` and their `current_mission_id` cleared before ordinary queue processing begins.

This startup cleanup must not alter healthy non-working states unnecessarily.

Future departments should use the same recovery contract when they become executable.

## Error handling

### Mission-local failures

A malformed, unsupported, blocked, or tool-failed mission must affect only that mission. The worker process must remain alive and continue polling after the failure is durably recorded.

### Host Helper failures

Temporary or bounded Host Helper failures must become bounded mission failures through the existing SysAdmin error path. They must not crash the worker loop.

### Runtime state/database failures

If the worker cannot reliably read or interpret runtime `SystemState`, execution must stop for that cycle. No mission should be claimed or executed until durable runtime state is trustworthy again.

Database errors that make mission ownership or state transitions uncertain must not be converted into guessed success or automatic replay.

### Redis

Redis availability may remain a startup dependency/health gate for this release. Redis is not the mission queue source of truth and is not used as an ownership lock in v1.

## Operations Ledger visibility

Existing mission and action events remain authoritative.

Add only a small number of orchestration-level events where they provide operational value, such as:

- worker startup/restart;
- interrupted mission paused for recovery;
- mission claimed for autonomous processing;
- execution blocked because system runtime state is unavailable/fail-closed, if recorded in a way that does not create polling noise.

Do not emit a ledger record every five seconds when there is no work. Idle polling must remain quiet.

If a dedicated orchestration event type would expand the ledger schema unnecessarily, use existing event types plus bounded metadata rather than creating a broad new event family.

## Host Helper allow-lists

Production evidence confirms:

- DripVid runs as `dripvid.service`;
- DripVid logs are read from the systemd journal for `dripvid.service`;
- there is no DripVid Docker container;
- AI HQ web/worker remain Docker targets;
- Nginx remains `nginx.service`.

The worker-built `HostAllowLists` must therefore contain:

- services: `ai-hq`, `nginx`, `dripvid`;
- containers: `ai-hq-web`, `ai-hq-worker`;
- logs: `ai-hq`, `nginx`, `dripvid`.

No `dripvid` container target is permitted.

## Expected code boundaries

Implementation should preserve current separation of concerns:

- `src/ai_hq/worker.py` owns process lifecycle, polling, runtime gating, and startup recovery coordination.
- `src/ai_hq/missions/service.py` owns durable mission queries and transitions, including queries needed to detect `RUNNING` work.
- `src/ai_hq/departments/runner.py` remains the one-mission execution primitive and should not become a daemon/scheduler itself.
- `src/ai_hq/agents/registry.py` should own any reusable stale-state reset operation rather than worker code mutating agent rows directly.
- `src/ai_hq/safety/*` remains the authority for action risk/approval decisions.
- `src/ai_hq/host_helper/*` remains the only host execution boundary.

If implementation discovers that atomic mission claiming requires a broader database concurrency redesign, stop and upgrade the design rather than silently adding a second ownership mechanism.

## Concurrency model

Production v1 assumes one worker process/container and one autonomous executor.

The worker enforces one active `RUNNING` mission at a time at the application/database level. This phase does not attempt to support multiple competing worker replicas.

Compose must continue to run a single worker service instance. Horizontal worker scaling is out of scope.

## Polling

Use simple bounded polling rather than Redis event wakeups.

The existing approximately five-second idle sleep is acceptable for v1. A mission completion may immediately be followed by another `run_once()` cycle without an unnecessary sleep; sleep is needed only when there is no runnable work or when execution is currently frozen/blocked.

The loop must avoid a busy spin when runtime state is Freeze or unavailable.

## Acceptance tests

Automated tests must prove at minimum:

1. Freeze mode executes no queued missions.
2. Safe mode processes queued missions.
3. Normal mode processes queued missions.
4. Missing `SystemState` executes nothing.
5. Invalid `SystemState` executes nothing.
6. Runtime state is re-read during the loop rather than cached solely from startup settings.
7. A `WAITING_APPROVAL` mission does not block a later queued mission.
8. The worker does not start a second mission while another mission is `RUNNING`.
9. Worker startup pauses interrupted `RUNNING` missions with an explicit recovery reason and does not re-execute them.
10. Startup recovery clears stale Commander and SysAdmin `WORKING` state and current mission IDs.
11. Unsupported missions fail cleanly without terminating the worker loop.
12. Department/tool failures fail the affected mission without terminating the worker loop.
13. Oldest queued mission is processed before later queued missions.
14. DripVid is accepted as a systemd/log target and rejected as a Docker target.
15. Existing approval and Safety Engine tests remain green.
16. Existing Host Helper isolation/security tests remain green.
17. Full test suite passes.
18. Compose validation passes.

## Production acceptance sequence

Deployment must remain gated by the normal verified-release process.

After deployment:

1. Confirm active release SHA, web health, worker health, Host Helper socket/service, and current runtime `SystemState`.
2. Set runtime to `Safe` with `Simulation Mode ON` for autonomous acceptance.
3. Queue a small deterministic set of known missions.
4. Prove the worker drains those missions without manual execution calls.
5. Include a mission that reaches `WAITING_APPROVAL` and prove a later safe queued mission can still execute.
6. Verify agent UI state and Operations Ledger reflect the autonomous work.
7. Verify Simulation Mode caused no real Host Helper execution for simulated actions where existing policy requires simulation.
8. After the simulated acceptance passes, explicitly switch runtime to `Safe` with `Simulation Mode OFF`.
9. Queue exactly one real read-only mission, such as Nginx service status or DripVid recent logs.
10. Prove exactly one real tool execution occurred and the mission completed.
11. Confirm Safe Mode remains ON and no mutation capability was introduced.

If any production gate fails, stop and investigate before further autonomous missions are enabled.

## Security properties preserved

- No arbitrary shell.
- No unrestricted root access.
- No Docker socket inside AI HQ.
- Host Helper remains narrow, authenticated, allow-listed, and read-only for current capabilities.
- Destructive/security/financial/externally-visible/production-affecting actions remain subject to existing approval policy.
- Missing or invalid permissions/runtime state fails closed.
- Runtime Safe Mode remains the production default operating mode.
- Startup environment remains fail-closed even when durable runtime state is later changed deliberately.
- No new paid AI provider use is introduced.

## Deferred follow-on phases

After this loop is proven in production, subsequent phases may add, separately:

1. Communications department execution.
2. Calendar department execution.
3. recurring and triggered mission creation.
4. proactive Commander-created maintenance missions.
5. priority scheduling.
6. richer multi-department routing.
7. controlled retries/idempotency for selected capabilities.
8. parallel workers only after a deliberate atomic-claim/concurrency design.
9. richer game-like HQ activity visualization.

Each of those changes requires its own scoped design/approval because they expand authority or concurrency beyond this v1 contract.
