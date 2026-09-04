# Autonomous Missions Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent, restart-safe autonomous mission plans that execute one ordered step at a time exclusively through the existing Tool Gateway.

**Architecture:** Mission plans and step state are persisted in SQLAlchemy. Mission execution selects one pending step, constructs an exact ToolRequest, and delegates all permission, safety, approval, simulation, adapter and audit decisions to ToolGateway. Approval-required operations pause both the mission and step and must be re-evaluated by the gateway when resumed.

**Tech Stack:** Python 3.13, SQLAlchemy, FastAPI, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-autonomous-missions-design.md`

## Global Constraints

- Existing mission lifecycle remains the source of truth.
- Every executable mission step references an exact Tool Gateway capability.
- Mission code never executes shell, host-helper, adapter, or infrastructure operations directly.
- Tool Gateway remains authoritative for permission, safety, simulation and approval decisions.
- Risky operations pause for approval and cannot silently bypass that state.
- Mission and step progress persists across worker/service restarts.
- Completed steps are never selected for execution again.
- Existing operations ledger remains the audit boundary for gateway execution.
- Existing tests must remain green.

---

### Task 1: Persist mission plans and ordered steps

**Files:**
- Modify: `src/ai_hq/missions/models.py`
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_mission_plans.py`

**Interfaces:**
- Produces: `MissionStep`, `MissionStepStatus`, `MissionService.create_plan()`.

- [x] Write persistence tests.
- [x] Verify RED.
- [x] Implement mission-step persistence.
- [x] Verify GREEN.
- [x] Commit.

### Task 2: Validate exact Tool Gateway capabilities

**Files:**
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_mission_plans.py`

**Interfaces:**
- Consumes: `ToolRegistry.resolve(capability)`.
- Produces: fail-closed plan validation.

- [x] Write unregistered-capability test.
- [x] Verify RED.
- [x] Implement exact registry validation.
- [x] Verify GREEN.
- [x] Commit.

### Task 3: Add deterministic step lifecycle

**Files:**
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_mission_plans.py`

**Interfaces:**
- Produces: `next_pending_step()`, `transition_step()`.

- [x] Write lifecycle tests.
- [x] Verify RED.
- [x] Implement explicit transitions.
- [x] Verify GREEN.
- [x] Commit.

### Task 4: Execute steps through Tool Gateway

**Files:**
- Create: `src/ai_hq/missions/executor.py`
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_autonomous_missions.py`
- Test: `tests/test_autonomous_mission_boundary.py`

**Interfaces:**
- Consumes: `ToolGateway.execute(ToolRequest)`.
- Produces: `MissionExecutor.run_next()`.

- [x] Route exactly one selected step through Tool Gateway.
- [x] Map executed/simulated outcomes to succeeded steps.
- [x] Map blocked/failed outcomes to failed mission state.
- [x] Prevent completed-step re-execution.

### Task 5: Approval pause and resume

**Files:**
- Modify: `src/ai_hq/missions/executor.py`
- Test: `tests/test_autonomous_missions.py`

**Interfaces:**
- Consumes: gateway `WAITING_APPROVAL`.
- Produces: persisted waiting state and `resume_approved()`.

- [x] Persist approval reference.
- [x] Pause mission and step.
- [x] Prevent execution around approval.
- [x] Re-evaluate exact request through gateway on resume.

### Task 6: Restart safety and idempotency

**Files:**
- Modify: `src/ai_hq/missions/service.py`
- Test: `tests/test_autonomous_missions.py`

**Interfaces:**
- Produces: persisted plan queries and completion checks.

- [x] Read plan from database.
- [x] Select pending steps only.
- [x] Verify new service instance sees completed state.

### Task 7: Mission API plan visibility

**Files:**
- Modify: `src/ai_hq/missions/api.py`
- Test: `tests/test_mission_lifecycle.py`

**Interfaces:**
- Produces: `plan` in authenticated mission detail response.

- [x] Expose ordered plan steps.
- [x] Expose status/result/error/approval reference.
- [x] Preserve authentication boundary.

### Task 8: Safety and regression verification

**Files:**
- Test: `tests/test_autonomous_mission_boundary.py`

- [x] Assert no direct shell/host-helper execution exists in mission executor.
- [x] Assert execution crosses Tool Gateway.
- [x] Run complete test suite.
- [x] Run diff/syntax verification.
- [ ] Commit complete Stage 1 implementation.
