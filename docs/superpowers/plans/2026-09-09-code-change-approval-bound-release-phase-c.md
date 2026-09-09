# Approval-Bound Release Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an explicitly approved and already-published code-change candidate proceed to production deployment through an approval-bound release orchestration that reuses the existing deployment adapter boundary, exposes the deployment result in chat, and preserves enough trusted deployment metadata to identify the prior known-good release for rollback. Deployment remains fail-closed: no operation turns it on.

**Architecture:** Mirrors the Phase B publishing boundary. `DeliveryService.record_deployment` persists immutable release identity (deployment release id, prior known-good release id, deployed time) only after the same exact-boundary human approval is re-confirmed and the candidate is already published. A narrow `CandidateDeployer` in `code_changes/deployer.py` returns a validated `DeployedRelease`; the guarded operational deployer routes through the existing deployment-deploy transport and refuses to fabricate release identity. `CodeChangeService.deploy_approved_candidate` binds the exact approval + change_ref + published identity, invokes the injected deployer, verifies the returned identity, and records the deployment. Chat replies surface the deployed release and its prior known-good release.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, FastAPI worker runtime, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-07-chat-driven-code-changes-design.md` (Phase C).

## Global Constraints

- Deployment remains a separate approved operation and must be audit logged.
- Deployment remains behind the Tool Gateway/Approval Service boundary; this increment adds no new production authority.
- Only an exact QA-passed, human-approved, and already-published candidate can be deployed; a changed candidate, pending/denied/expired approval, or unknown repository fails closed before any mutation.
- Every successful deployment initiated through this flow records a trusted release id and the prior known-good release id for rollback.
- Release ids use the same bounded safe charset as the existing rollback adapter (ASCII alphanumeric plus `._-`, max 128).
- The deployer contract never accepts arbitrary release paths, host paths, commands, or model-supplied identities; unknown/missing release identity fails closed.
- No deployment is enabled by default in the worker or web runtime.
- No token, credential, environment dump, or secret content is persisted in deployment evidence.

---

### Task 1: Persist approval-bound deployment metadata on the delivery

**Files:**
- Modify: `src/ai_hq/delivery/models.py`
- Modify: `src/ai_hq/delivery/service.py`
- Create: `migrations/versions/0018_delivery_release.py`
- Test: `tests/test_delivery_deployment.py`
- Test: `tests/test_migration_graph.py`

**Interfaces:**
- Adds nullable delivery fields `deployment_release_id`, `deployment_prior_release_id`, `deployed_at`.
- Produces: `DeliveryService.record_deployment(mission_id, change_ref, release_id, prior_release_id) -> Delivery`.

- [x] **Step 1: Write failing persistence tests** requiring exact `change_ref`, QA PASSED, WAITING_APPROVAL, matching persisted approval, release id safe-charset validation, and idempotent replay only when release id + prior release id are identical. Mismatched second deployment must fail closed.
- [x] **Step 2: Run** `python -m pytest -q tests/test_delivery_deployment.py` and confirm RED.
- [x] **Step 3: Add migration/model/service implementation** with the same validation discipline as `record_publication`, without storing any secrets or raw adapter output.
- [x] **Step 4: Run focused tests + migration graph** and require all pass with one Alembic head.
- [x] **Step 5: Commit** with `feat: persist approval-bound code-change release metadata`.

### Task 2: Add a narrow candidate deployer contract

**Files:**
- Create: `src/ai_hq/code_changes/deployer.py`
- Test: `tests/test_code_change_deployer.py`

**Interfaces:**
- Produces: frozen `DeployedRelease(repository, change_ref, release_id, prior_release_id)` with strict validation.
- Produces: `CandidateDeployer.deploy(candidate) -> DeployedRelease` protocol.
- Produces: guarded `OperationalCandidateDeployer` that requires a registered target allowing `deployment.deploy` and a transport `deployment_deploy` result carrying a trusted `release_id` (and optional `prior_release_id`), raising on any fabricatable/missing identity.

- [x] **Step 1: Write failing contract tests** for a well-formed release, unknown repository rejection, unsafe release-id charset rejection, missing release identity failing closed, and target-capability denial.
- [x] **Step 2: Run** `python -m pytest -q tests/test_code_change_deployer.py` and confirm RED.
- [x] **Step 3: Implement the contract** reusing the exact operational target/transport when a deployer is constructed, defaulting to `None` everywhere so deployment stays off.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: define trusted code-change deployer`.

### Task 3: Gate deployment on the exact human approval and published candidate

**Files:**
- Modify: `src/ai_hq/code_changes/service.py`
- Test: `tests/test_code_change_deployment_service.py`

**Interfaces:**
- Adds injected optional `deployer: CandidateDeployer | None`.
- Produces: `CodeChangeService.deploy_approved_candidate(mission_id, approval_reference, change_ref) -> CodeChangeResult` with `deployed` flag and deployment identity on the result.

- [x] **Step 1: Write failing tests** proving pending/denied/mismatched approval blocks the deployer; QA failure blocks; missing publication blocks; unknown repository blocks; approved exact published candidate deploys once and records release metadata; replay returns the persisted deployment without a second mutation; missing/unconfigured deployer fails closed with `RuntimeError`.
- [x] **Step 2: Run focused service tests** and confirm RED.
- [x] **Step 3: Implement the orchestration** by first re-confirming the exact-boundary human approval and the persisted published identity, then invoking the deployer only for the exact candidate, validating the returned `DeployedRelease`, then persisting via `record_deployment`.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: deploy only approved published code-change candidates`.

### Task 4: Expose the deployment result and rollback metadata in chat

**Files:**
- Modify: `src/ai_hq/chat/controller.py`
- Modify: `tests/test_chat_code_change_wiring.py`

**Interfaces:**
- `_completed_code_change_reply` reports the deployed release and prior known-good release when present, and otherwise keeps the existing "No code was published or deployed." bound message.

- [x] **Step 1: Write failing wiring tests** for a deployed result surface and a non-deployed result keeping the existing bound text.
- [x] **Step 2: Run focused wiring tests** and confirm RED.
- [x] **Step 3: Update the chat reply** to render deployment state from the candidate result without changing authorization behavior.
- [x] **Step 4: Run focused tests** and require all pass.
- [x] **Step 5: Commit** with `feat: surface code-change deployment state in chat`.

### Task 5: Full Phase C verification and review

**Files:**
- Review all files changed by Tasks 1-4.
- Check: `src/ai_hq/code_changes/runtime.py` and `src/ai_hq/worker.py` still default to deployment disabled.

- [x] **Step 1: Run lint**: `python -m ruff check src tests`.
- [x] **Step 2: Run full tests**: `python -m pytest -q`.
- [x] **Step 3: Validate the worker/web default**: no `CandidateDeployer` is constructed in `build_code_change_service`, `build_code_change_queue_runner`, or `install_chat_routes`.
- [x] **Step 4: Verify authority boundaries**: no model-facing command/remote/release-path/token fields; deployment stays off unless an operator explicitly injects a guarded deployer with a granted target capability.
- [x] **Step 5: Review the final diff** against the approved Phase C spec and merge only after the full suite is green.