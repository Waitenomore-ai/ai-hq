# Approval-Bound Rollback Phase D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an explicitly approved already-deployed code-change candidate be rolled back to its prior known-good release through an approval-bound rollback orchestration that mirrors the Phase C deployment boundary. The rollback target is never invented by the model: it is derived exclusively from trusted persisted deployment history (`deployment_prior_release_id`), routed through the existing `deployment.rollback` transport, and persisted on the delivery for audit and idle replay. Everything remains fail-closed by default.

**Architecture:** Mirrors the Phase B/C boundaries. `DeliveryService.record_rollback` persists immutable rollback identity (the restored release id, rollback time) only after the same exact-boundary human approval is re-confirmed, the candidate was published, and a deployment was already recorded. A narrow `CandidateRollbacker` in `code_changes/rollbacker.py` returns a validated `RolledBackRelease`; the guarded operational rollbacker routes through the existing `deployment.rollback` transport, confirms the exact trusted release id, and refuses to fabricate identity. `CodeChangeService.rollback_approved_deployment` binds the exact approval + change_ref + persisted deployment, derives the rollback target, invokes the injected rollbacker, verifies the returned identity, and records the rollback. Chat replies surface the restored release.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, FastAPI worker runtime, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-07-chat-driven-code-changes-design.md` (Phase D, Rollback section).

## Global Constraints

- Rollback remains a separate approved operation and must be audit logged.
- Rollback remains behind the Tool Gateway/Approval Service boundary; this increment adds no new production authority.
- Only an exact QA-passed, human-approved, published and already-deployed candidate can be rolled back; a changed candidate, pending/denied/expired approval, unknown repository, or missing deployment fails closed before any mutation.
- The rollback release id is derived from the persisted `deployment_prior_release_id` (trusted known-good history), never from model output, arbitrary paths, or commands.
- Release ids use the same bounded safe charset as the existing rollback adapter (ASCII alphanumeric plus `._-`, max 128).
- The rollbacker contract never accepts arbitrary release paths, host paths, commands, or model-supplied identities; unknown/missing release identity fails closed.
- A delivery can record at most one rollback; replay is idempotent only for the exact same restored release.
- No rollbacker is enabled by default in the worker or web runtime.
- No token, credential, environment dump, or secret content is persisted in rollback evidence.

---

### Task 1: Persist approval-bound rollback metadata on the delivery

**Files:**
- Modify: `src/ai_hq/delivery/models.py`
- Modify: `src/ai_hq/delivery/service.py`
- Create: `migrations/versions/0019_delivery_rollback.py`
- Test: `tests/test_delivery_rollback.py`
- Test: `tests/test_migration_graph.py`

**Interfaces:**
- Adds nullable delivery fields `rollback_release_id`, `rolled_back_at`.
- Produces: `DeliveryService.record_rollback(mission_id, change_ref, release_id) -> Delivery`.

- [x] **Step 1: Write failing persistence tests** requiring exact `change_ref`, QA PASSED, WAITING_APPROVAL, matching persisted approval, an already-persisted deployment identity, a release id equal to the persisted `deployment_prior_release_id`, release id safe-charset validation, and idempotent replay only for the exact same restored release. A mismatched second rollback must fail closed.
- [x] **Step 2: Run** `python -m pytest -q tests/test_delivery_rollback.py` and confirm RED.
- [x] **Step 3: Add migration/model/service implementation** with the same validation discipline as `record_publication`/`record_deployment`, without storing any secrets or raw adapter output.
- [x] **Step 4: Run focused tests + migration graph** and require all pass with one Alembic head.
- [x] **Step 5: Commit** with `feat: persist approval-bound code-change rollback metadata`.

### Task 2: Add a narrow candidate rollbacker contract

**Files:**
- Create: `src/ai_hq/code_changes/rollbacker.py`
- Test: `tests/test_code_change_rollbacker.py`

**Interfaces:**
- Produces: frozen `RollbackTarget(repository, change_ref)` and `RolledBackRelease(repository, change_ref, release_id)` with strict validation.
- Produces: `CandidateRollbacker.rollback(target, release_id) -> RolledBackRelease` protocol.
- Produces: guarded `OperationalCandidateRollbacker` that requires a registered target allowing `deployment.rollback` and a transport `deployment_rollback` result carrying the exact trusted `release_id`, raising on any fabricatable/missing/mismatched identity.

- [x] **Step 1: Write failing contract tests** for a well-formed rollback, unknown repository rejection, unsafe release-id charset rejection, missing/mismatched transport release identity failing closed, and target-capability denial.
- [x] **Step 2: Run** `python -m pytest -q tests/test_code_change_rollbacker.py` and confirm RED.
- [x] **Step 3: Implement the contract** reusing the exact operational target/transport when a rollbacker is constructed, defaulting to `None` everywhere so rollback stays off.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: define trusted code-change rollbacker`.

### Task 3: Gate rollback on the exact human approval and trusted deployment history

**Files:**
- Modify: `src/ai_hq/code_changes/service.py`
- Test: `tests/test_code_change_rollback_service.py`

**Interfaces:**
- Adds injected optional `rollbacker: CandidateRollbacker | None`.
- Produces: `CodeChangeService.rollback_approved_deployment(mission_id, approval_reference, change_ref) -> CodeChangeResult` with `rolled_back` flag and `rollback_release_id` on the result.

- [x] **Step 1: Write failing tests** proving pending/denied/mismatched approval blocks the rollbacker; QA failure blocks; missing publication blocks; missing deployment blocks; unknown repository blocks; approved exact deployed candidate rolls back once to the persisted prior release and records rollback metadata; replay returns the persisted rollback without a second mutation; missing/unconfigured rollbacker fails closed with `RuntimeError`.
- [x] **Step 2: Run focused service tests** and confirm RED.
- [x] **Step 3: Implement the orchestration** by first re-confirming the exact-boundary human approval and the persisted published + deployed identity, deriving the rollback target only from `deployment_prior_release_id`, then invoking the rollbacker for the exact candidate, validating the returned `RolledBackRelease`, then persisting via `record_rollback`.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: roll back only approved previously-deployed code-change candidates`.

### Task 4: Expose the rollback result in chat

**Files:**
- Modify: `src/ai_hq/chat/controller.py`
- Modify: `tests/test_chat_code_change_wiring.py`

**Interfaces:**
- `_code_change_outcome` reports the restored release when present, and otherwise keeps the existing "No code was published or deployed." bound message.

- [x] **Step 1: Write failing wiring tests** for a rolled-back result surface and a non-rolled-back result keeping the existing bound text.
- [x] **Step 2: Run focused wiring tests** and confirm RED.
- [x] **Step 3: Update the chat reply** to render rollback state from the candidate result without changing authorization behavior.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: surface code-change rollback state in chat`.

### Task 5: Full Phase D verification and review

**Files:**
- Review all files changed by Tasks 1-4.
- Check: `src/ai_hq/code_changes/runtime.py` and `src/ai_hq/worker.py` still default to rollback disabled.

- [x] **Step 1: Run lint**: `python -m ruff check src tests`.
- [x] **Step 2: Run full tests**: `python -m pytest -q`.
- [x] **Step 3: Validate the worker/web default**: no `CandidateRollbacker` is constructed in `build_code_change_service`, `build_code_change_queue_runner`, or `install_chat_routes`.
- [x] **Step 4: Verify authority boundaries**: no model-facing command/remote/release-path/token fields; rollback stays off unless an operator explicitly injects a guarded rollbacker with a granted target capability.
- [x] **Step 5: Review the final diff** against the approved Phase D spec and merge only after the full suite is green.