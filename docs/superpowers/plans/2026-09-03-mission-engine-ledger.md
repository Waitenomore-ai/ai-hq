# Mission Engine + Agents + Operations Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable mission state, the four Phase 1 agents, and an append-only operations ledger that records mission lifecycle events without enabling real-world mutations.

**Architecture:** Extend the existing modular FastAPI/SQLAlchemy monolith with focused mission, agent, and ledger modules. PostgreSQL remains the system of record; Redis remains transient. This slice does not implement the Tool Gateway or approvals, but it records risk and lifecycle data in a form those later subsystems can consume.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md`

## Global Constraints

- Mission states are exactly: `QUEUED`, `RUNNING`, `WAITING_APPROVAL`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Durable mission state and ledger records live in PostgreSQL.
- Phase 1 agents are exactly Commander, Communications, Calendar and SysAdmin.
- Safe Mode and Simulation Mode remain the defaults; this slice must not add real-world mutation capability.
- Commander cannot bypass specialist permissions, approval requirements, or the Tool Gateway.
- Operations must remain auditable and append-only at the application boundary.

---

### Task 1: Durable mission model and transition rules

**Files:**
- Create: `src/ai_hq/missions/models.py`
- Create: `src/ai_hq/missions/service.py`
- Create: `src/ai_hq/missions/__init__.py`
- Modify: `src/ai_hq/models/__init__.py`
- Create: `migrations/versions/0003_missions.py`
- Test: `tests/test_missions.py`

**Interfaces:**
- Produces: `MissionStatus`, `MissionPriority`, `MissionRisk`, `Mission`, `MissionService.create_mission()`, `MissionService.transition()`.

- [ ] **Step 1: Write failing tests** covering required fields, default `QUEUED`, valid transitions, rejection of invalid terminal-state transitions, and persisted result/error metadata.
- [ ] **Step 2: Run `python -m pytest tests/test_missions.py -q`** and verify RED because mission modules do not exist.
- [ ] **Step 3: Implement minimal models/service** with enum-backed SQLAlchemy columns and an explicit allowed-transition map.
- [ ] **Step 4: Add Alembic migration** creating the durable missions table with JSON objectives/dependencies and timestamps.
- [ ] **Step 5: Run mission tests and full suite**; both must pass.

### Task 2: Phase 1 agent registry

**Files:**
- Create: `src/ai_hq/agents/models.py`
- Create: `src/ai_hq/agents/registry.py`
- Create: `src/ai_hq/agents/__init__.py`
- Modify: `src/ai_hq/models/__init__.py`
- Create: `migrations/versions/0004_agents.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces: `Agent`, `AgentStatus`, `AgentRegistry.ensure_phase1_agents()`, `AgentRegistry.get_by_key()`.
- Consumes: mission identifiers from Task 1 for optional current-mission tracking.

- [ ] **Step 1: Write failing tests** asserting exactly four seeded agents with stable keys `commander`, `communications`, `calendar`, `sysadmin`, idle default status, and no sensitive permissions auto-granted.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Implement durable agent model and idempotent registry seeding** with role/display-name/capability metadata.
- [ ] **Step 4: Add migration** for agents and optional current mission foreign key.
- [ ] **Step 5: Run focused and full tests**.

### Task 3: Append-only Operations Ledger

**Files:**
- Create: `src/ai_hq/ledger/models.py`
- Create: `src/ai_hq/ledger/service.py`
- Create: `src/ai_hq/ledger/__init__.py`
- Modify: `src/ai_hq/models/__init__.py`
- Create: `migrations/versions/0005_operations_ledger.py`
- Test: `tests/test_operations_ledger.py`

**Interfaces:**
- Produces: `LedgerEventType`, `OperationsLedger.record()`, `OperationsLedger.for_mission()`.
- Consumes: mission ID and optional agent key.

- [ ] **Step 1: Write failing tests** for ordered append-only events, mission filtering, JSON metadata, and rejection of update/delete service APIs.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Implement immutable-at-service-boundary ledger records** with UUID, mission ID, agent key, event type, timestamp, summary and metadata.
- [ ] **Step 4: Add migration** with indexes on mission ID, event type and created time.
- [ ] **Step 5: Run focused and full tests**.

### Task 4: Mission lifecycle automatically records ledger events

**Files:**
- Modify: `src/ai_hq/missions/service.py`
- Modify: `src/ai_hq/app.py`
- Create: `src/ai_hq/missions/api.py`
- Test: `tests/test_mission_lifecycle.py`

**Interfaces:**
- `MissionService` accepts an `OperationsLedger` collaborator.
- Protected endpoints: `GET /api/missions`, `POST /api/missions`, `GET /api/missions/{mission_id}`.

- [ ] **Step 1: Write failing integration tests** asserting mission creation records `mission.created`, transitions record `mission.status_changed`, API routes require the existing admin session, and health routes remain public.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Wire ledger recording into mission service and add authenticated mission API routes** without adding execute/tool endpoints.
- [ ] **Step 4: Run focused tests, complete suite, Ruff, and Compose validation**.
- [ ] **Step 5: Verify the diff contains no secrets, no DripVid runtime changes, and no real-world mutation capability.**
