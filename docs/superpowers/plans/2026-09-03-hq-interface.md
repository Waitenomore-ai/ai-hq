# HQ Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary authenticated home page with the first live top-down AI HQ floor where room/agent visuals reflect durable backend state.

**Architecture:** Keep FastAPI/Jinja as the authenticated shell, add a read-only `/api/hq/state` projection over durable Agent and Mission records, and render a responsive CSS/JS floor plan that polls that projection. The first floor has Commander, Communications, Calendar, SysAdmin, Approvals, and Knowledge rooms; only real Phase 1 agents receive agent avatars/status. Shared rooms expose system state without pretending to be agents.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy, vanilla JavaScript, CSS Grid, pytest/TestClient.

**Spec:** `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md`

## Global Constraints

- Real backend state is the source of truth; animations never invent work.
- The current `/ai-hq` authenticated session boundary remains unchanged.
- No tool-execution endpoint is added.
- The first floor must work under the `/ai-hq` root path and on phone/tablet/desktop.
- Missing durable agent rows render as `OFFLINE`, not as fake activity.
- Expandability is represented by stable room keys and floor metadata so future wings/floors can be added without replacing the state API.

---

### Task 1: HQ state projection

**Files:**
- Create: `src/ai_hq/hq/__init__.py`
- Create: `src/ai_hq/hq/state.py`
- Test: `tests/test_hq_state.py`

**Interfaces:**
- Consumes: SQLAlchemy session factory, `Agent`, `AgentStatus`, `Mission`, `MissionStatus`.
- Produces: `HQStateService.snapshot() -> dict` containing `floor`, `rooms`, and room-level real state.

- [ ] **Step 1:** Write tests proving the four Phase 1 agent rooms map durable `Agent.status/current_mission_id` to UI states and missing agents are `OFFLINE`.
- [ ] **Step 2:** Run `pytest tests/test_hq_state.py -q`; expect failure because `ai_hq.hq` is absent.
- [ ] **Step 3:** Implement stable room definitions and state projection. Map `IDLE -> IDLE`, `WORKING -> WORKING`, `WAITING_APPROVAL -> WAITING_APPROVAL`, `FAILED -> FAILED`, `COMPLETED -> IDLE`. Include current mission title when linked.
- [ ] **Step 4:** Add shared Approval and Knowledge rooms without agent avatars; Approval reports waiting approval count, Knowledge reports durable memory count.
- [ ] **Step 5:** Run tests and commit.

### Task 2: Authenticated HQ state API

**Files:**
- Create: `src/ai_hq/hq/api.py`
- Modify: `src/ai_hq/app.py`
- Test: `tests/test_hq_api.py`

**Interfaces:**
- Produces: authenticated GET `/api/hq/state`; no POST/PUT/PATCH/DELETE route.

- [ ] **Step 1:** Add RED tests for unauthenticated 401, authenticated 200, stable room keys, and POST 405.
- [ ] **Step 2:** Implement the API using the existing `resolve_request_session` boundary.
- [ ] **Step 3:** Install the route in `create_app` and verify tests.

### Task 3: Top-down floor shell

**Files:**
- Modify: `src/ai_hq/templates/home.html`
- Create: `src/ai_hq/static/hq.css`
- Create: `src/ai_hq/static/hq.js`
- Modify: `src/ai_hq/app.py`
- Test: `tests/test_hq_interface.py`

**Interfaces:**
- Browser consumes GET `/api/hq/state` every 10 seconds.
- Room elements use `data-room-key`; agent state uses `data-agent-state` and accessible text.

- [ ] **Step 1:** Add RED tests that authenticated `/` includes the HQ viewport, six stable room keys, CSS/JS root-path URLs, status legend, Safe/Simulation indicators, and sign-out form.
- [ ] **Step 2:** Mount `StaticFiles` at `/static` and preserve `/ai-hq/static/...` externally via Jinja `root_path`.
- [ ] **Step 3:** Build a CSS Grid top-down floor with central Commander room, surrounding department rooms, corridor treatment, pixel/retro visual language, room labels, agent desk/avatar blocks, and status lights.
- [ ] **Step 4:** Add responsive behavior: desktop floor fits viewport; phones use horizontally/vertically pannable floor with minimum room sizes and large tap targets; reduced-motion disables avatar animation.
- [ ] **Step 5:** Add JS polling that updates only from API state, shows disconnected/offline if polling fails, and opens a room detail panel on click/tap.
- [ ] **Step 6:** Run tests and commit.

### Task 4: Interface safety and accessibility contract

**Files:**
- Test: `tests/test_hq_interface.py`
- Modify as needed: `src/ai_hq/templates/home.html`, `src/ai_hq/static/hq.css`, `src/ai_hq/static/hq.js`

- [ ] **Step 1:** Test that rooms are keyboard-focusable buttons, status is conveyed in text as well as styling, and no UI control exposes execute/send/restart/delete actions.
- [ ] **Step 2:** Test that shared rooms cannot masquerade as active agents and unknown API states fall back to `OFFLINE`.
- [ ] **Step 3:** Verify mobile viewport metadata and reduced-motion CSS.

### Task 5: Exact-head phase verification

**Files:** none unless verification finds defects.

- [ ] **Step 1:** Run full Ruff, pytest, and Compose validation through GitHub Actions.
- [ ] **Step 2:** Compare feature branch against `main`; confirm only HQ interface/state/API/static/test changes plus this plan.
- [ ] **Step 3:** Fast-forward `main` only to the exact CI-green SHA.
- [ ] **Step 4:** Verify feature branch and `main` are identical.
