# Approval & Safety Engine Implementation Plan

**Goal:** Implement the already-approved Green/Blue/Amber/Red decision model, durable action-bound approvals, scoped approval rules, and fail-closed Safe/Freeze/Simulation enforcement without adding real tool execution.

**Architecture:** Add a policy evaluator and durable approval records alongside the existing Mission Engine and Operations Ledger. Policy evaluation is pure and deterministic; PostgreSQL stores approvals; SystemState supplies operating/simulation mode; the ledger records policy and approval decisions. This slice ends at an execution decision object and never invokes external tools.

## Task 1 — Policy evaluator
- Add action/risk decision models.
- Green: potentially automatic in Normal when policy allows.
- Blue: automatic only when a matching active scoped rule permits the exact action/target/conditions.
- Amber: approval required.
- Red: blocked by default.
- Safe Mode: deny external mutations regardless of Green/Blue/Amber approval state.
- Freeze: deny all new execution decisions.
- Simulation: may authorize simulation but never real-world mutation.
- Missing/unavailable authorization context: deny.
- TDD focused policy matrix before implementation.

## Task 2 — Durable action-bound approvals
- Add ApprovalRequest and ScopedApprovalRule models/migrations.
- Approval binds to a canonical action fingerprint so materially changed plans invalidate prior approval.
- Store action, target, risk, mission, requester agent, state, expiry, conditions and optional max execution count.
- Scoped rules include allowed action, target, expiry, conditions and execution count.
- No blanket wildcard permission for Red actions.
- TDD expiry, fingerprint mismatch and execution-count behavior.

## Task 3 — Safety service + audit integration
- SafetyService evaluates requested actions using SystemState + approval/rule store.
- Record `action.proposed`, `permission.checked`, `risk.checked`, and `approval.recorded` ledger events as applicable.
- Amber decisions create/reuse a pending approval request and return WAITING_APPROVAL semantics to callers.
- Expose authenticated read-only approval listing/detail APIs only; no approve/execute browser action in this slice.
- Verify no external tool calls, no DripVid runtime changes, no credentials, and full CI green before merge.
