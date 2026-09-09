# DripVid Automatic Recovery: Production Enablement Runbook

> **Operator-controlled.** Nothing in this document activates automatic recovery silently. Recovery is disabled and observe-only by default (`AI_HQ_RECOVERY_ENABLED=false`, `AI_HQ_RECOVERY_OBSERVE_ONLY=true`). Each stage below must be performed deliberately, verified, and documented.

## Prerequisites

- AI HQ is installed under `/opt/ai-hq` with a release linked at `/opt/ai-hq/app`.
- Production environment is managed through `/etc/ai-hq/ai-hq.env` and the recovery settings block from `.env.example`:

```text
AI_HQ_RECOVERY_ENABLED=false
AI_HQ_RECOVERY_OBSERVE_ONLY=true
AI_HQ_RECOVERY_OBSERVATION_SECONDS=30
AI_HQ_RECOVERY_FAILURE_THRESHOLD=3
AI_HQ_RECOVERY_COOLDOWN_SECONDS=300
AI_HQ_RECOVERY_ATTEMPT_BUDGET=2
AI_HQ_RECOVERY_BUDGET_WINDOW_SECONDS=3600
AI_HQ_RECOVERY_VERIFY_SECONDS=60
AI_HQ_RECOVERY_DRIPVID_READY_URL=http://127.0.0.1:3000/health/ready
```

- The DripVid service exposes `/health/live` and `/health/ready`, and the health contract is deployed (DripVid equivalent of release `>= 2.90`).
- Normal startup protections remain on: `OPERATING_MODE=safe` and `SIMULATION_MODE=true` at every start.
- The Host Helper service and the `ai-hq` worker are running.

### How to apply an environment change

Edit `/etc/ai-hq/ai-hq.env`, then restart the AI HQ service so the worker picks up the new settings:

```bash
sudo systemctl restart ai-hq.service
```

Verify the running worker sees the new settings by checking the AI HQ dashboard's recovery card (`/`), which reports `Mode`, `Last probe`, `Failures`, and `Incident`.

---

## Stage A — Observe only

Goal: prove incident detection, diagnostics, audits, and notifications run without any mutation.

Keep the default state:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

Deploy with these settings and watch at least one observation window (`AI_HQ_RECOVERY_OBSERVATION_SECONDS`, default 30s).

Acceptance checks:

- Dashboard recovery card reaches a steady state with `Mode: Observe only` and healthy probes.
- Inject a short-lived DripVid failure (for example, stop `dripvid.service` for a few seconds then start it) and confirm:
  - consecutive failure count increments;
  - an incident is created with diagnostics;
  - notifications fire;
  - zero recovery mutation occurs (no restart runs);
  - the operations ledger records the observations without secrets.
- Confirm the real-attempt budget is unchanged.

If observation is not stable or audits are wrong, do not continue. Roll back by leaving `AI_HQ_RECOVERY_ENABLED=false` until the code is fixed.

---

## Stage B — Simulation

Goal: prove the full recovery path end to end while every host mutation is simulated.

1. Grant the exact `service.recover` capability to the chosen `sysadmin` agent and nothing else.
2. Create a tightly scoped approval rule:
   - component: one intended component only (e.g. `app`);
   - explicit conditions (`component`, `mission` source, etc.) — never wildcard conditions;
   - bounded `max_execution_count` and a short expiration.
3. Run one controlled simulated failure. Step 2 must already produce:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=false
SIMULATION_MODE=true
```

Acceptance checks for the simulated cycle:

- the incident threshold fires (`AI_HQ_RECOVERY_FAILURE_THRESHOLD`, default 3);
- a BLUE-risk recovery mission is created;
- Tool Gateway returns `SIMULATED`;
- Host Helper performs zero real restarts;
- the real-attempt budget is unchanged;
- audit and notification records are correct and secret-free.

Only after simulation acceptance proceed to Stage C.

---

## Stage C — First real mutation

Goal: perform one explicitly controlled real recovery of a single component during a maintenance window.

1. Disable observe-only but keep recovery limited to one component initially (`app`):

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=false
```

2. Keep the scoped approval rule with a low `max_execution_count` and a short expiration. No other component is granted `service.recover`.
3. During the maintenance window, deliberately stop the DripVid app service:

```bash
sudo systemctl stop dripvid.service
```

4. Verify AI HQ detects, diagnoses, recovers, and verifies the component:
   - incident record opens and the recovery mission runs;
   - after recovery, `/health/ready` returns healthy and `verify_recovery` succeeds;
   - `SIMULATION_MODE` never reported a false "real" for this cycle — real recovery only runs while `SIMULATION_MODE=false` and the approval rule permits it.
5. Inspect the operations ledger and incident record to confirm the exact action that ran.
6. Verify ordinary manual `service.restart` still asks for approval and is not silently authorized by the recovery rule.

If the first real recovery fails verification or exhausts the budget, escalation must fire and no retry loop after cooldown may happen unbounded.

---

## Stage D — Expand allowlist

Only after the prior component has proven stable in production:

1. Enable `mcp`, then after a proven window `proxy`, then `tunnel`. Each step: update the scoped approval rule, run one controlled failure for that component, verify and inspect as in Stage C.
2. Enable `database` last, and preserve the inactive/failed-only rule — a healthy active database must never be recovered.
3. Run full suite verification in the AI HQ repo and `git diff --check` after each change set.

Never create automatic storage remediation in this release. Storage unavailable/unwritable must escalate without restart.

---

## Rollback

To disable automatic recovery at any time:

```text
AI_HQ_RECOVERY_ENABLED=false
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

Restart `ai-hq.service` and confirm the dashboard shows recovery disabled/observe-only. Withdraw any scoped `service.recover` approval rules and remove the capability grant if production is frozen (`OPERATING_MODE=freeze`).

---

## Safety recap

- Real recovery requires an exact `service.recover` capability grant plus an exact scoped approval rule; no wildcard conditions.
- Three consecutive failures are required before recovery is considered.
- Cooldown and the rolling real-attempt budget survive worker restart.
- One component cannot be recovered concurrently by two workers.
- Storage unavailable/unwritable and PostgreSQL active-but-unhealthy both escalate without restart.
- Recovery runs through a persisted BLUE-risk mission; the observer has no direct host mutation path.
- Every successful recovery (and every escalated failure) is recorded in the operations ledger without secrets.