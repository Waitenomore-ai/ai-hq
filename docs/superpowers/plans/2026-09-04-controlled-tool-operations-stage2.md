# Controlled Real-World Tool Gateway Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give AI HQ allowlisted real operational capabilities while preserving Tool Gateway permissions, safety, approval, simulation, auditability, and mission isolation.

**Architecture:** Extend the existing Tool Gateway and Host Helper rather than creating another privileged execution path. Logical targets resolve through trusted server-side configuration; capability-specific adapters validate bounded inputs; mutations require approval; workers execute persisted mission steps only through MissionExecutor and ToolGateway.

**Tech Stack:** Python, SQLAlchemy, FastAPI, Tool Gateway, Safety Service, Approval Service, Operations Ledger, Host Helper, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-controlled-tool-operations-stage2-design.md`

## Global Constraints

- Tool Gateway is the mandatory execution boundary.
- Initial logical targets are `ai-hq` and `dripvid`.
- No arbitrary shell commands, executables, service units, filesystem paths, hosts, or network targets.
- Unknown capabilities and targets fail closed.
- Permissions are exact capability permissions.
- `service.restart`, `deployment.deploy`, and `deployment.rollback` require approval before real mutation.
- Simulation causes no external mutation.
- OS operations use fixed executables and argument vectors; never `shell=True`.
- Automated tests use fakes/test doubles and never restart or deploy production services.
- Concurrent workers cannot independently execute the same mutating mission step.
- Stage 3 dashboard work is excluded.

## Development Method

Every task follows the same TDD gate:

- [ ] Write the focused failing test described by the task.
- [ ] Run that focused test and confirm the expected failure.
- [ ] Implement the smallest change satisfying the contract.
- [ ] Run the focused test and relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit using the task's specified commit message.

---

### Task 1: Trusted operational target registry

**Files:** `src/ai_hq/operations/targets.py`

**Tests:** `tests/test_operational_targets.py`

**Contract:** Create immutable OperationalTarget and OperationalTargetRegistry contracts. Register only trusted logical targets such as ai-hq and dripvid. Reject unknown targets, duplicate keys, empty service units, and capabilities not explicitly enabled for a target.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: add trusted operational target registry`.

---

### Task 2: Bounded operational adapters

**Files:** `src/ai_hq/operations/adapters.py`

**Tests:** `tests/test_operational_adapters.py`

**Contract:** Create capability-specific adapters for system.health.read, service.status.read, service.logs.read, and service.restart. Resolve logical targets through the trusted registry. Logs accept only an integer lines parameter from 1 through 500. Health, status, and restart accept no mission-controlled unit, hostname, path, executable, or command parameters.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: add bounded operational adapters`.

---

### Task 3: Restricted host transport

**Files:** `src/ai_hq/host_helper/`

**Tests:** `tests/test_host_helper.py tests/test_operational_adapters.py`

**Contract:** Extend the existing Host Helper only where required. Use fixed executables, argv semantics, trusted target configuration, bounded output, and timeouts. Never use shell=True, os.system, os.popen, or mission-controlled executable/service values.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: add restricted operational host transport`.

---

### Task 4: Tool Gateway registration

**Files:** `src/ai_hq/operations/bootstrap.py`

**Tests:** `tests/test_operational_gateway.py`

**Contract:** Create register_operational_tools and register one explicit adapter for each Stage 2 capability. Preserve existing ToolRegistry duplicate protection. Unknown capabilities must remain unavailable and there must be no wildcard or generic command fallback.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: register controlled operational tools`.

---

### Task 5: Exact permissions and fail-closed targets

**Files:** `src/ai_hq/tool_gateway/service.py`

**Tests:** `tests/test_operational_gateway.py`

**Contract:** Verify ToolGateway exact permission checks for each operational capability. Prove service.status.read does not authorize service.restart, unknown targets execute no transport operation, and targets cannot use capabilities outside their allowlist.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `test: enforce operational gateway boundaries`.

---

### Task 6: Mandatory restart approval

**Files:** `src/ai_hq/operations/`

**Tests:** `tests/test_operational_restart_approval.py`

**Contract:** Route service.restart through the existing Safety Service and Approval Service with mutates_external_state=True. The first request must wait for approval and execute zero restarts. Only the exact approved persisted request may execute after Tool Gateway re-evaluation. Rejected, expired, or mismatched approvals must not mutate.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: require approval for service restart`.

---

### Task 7: Simulation no-mutation guarantee

**Files:** `src/ai_hq/tool_gateway/service.py`

**Tests:** `tests/test_operational_restart_approval.py`

**Contract:** Prove SIMULATE_ONLY returns before adapter execution. A simulated restart, deployment, or rollback must produce a simulated ToolOutcome and zero mutation calls.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `test: guarantee simulation cannot mutate services`.

---

### Task 8: Atomic autonomous mission step claiming

**Files:** `src/ai_hq/missions/service.py src/ai_hq/missions/executor.py`

**Tests:** `tests/test_mission_step_claiming.py tests/test_autonomous_missions.py`

**Contract:** Add MissionService.claim_next_step(mission_id). Claim exactly one persisted PENDING step using a database conditional transition to RUNNING. Two independent workers must not claim the same step. Update MissionExecutor to consume the claimed step rather than separately reading PENDING and then transitioning it.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `fix: atomically claim autonomous mission steps`.

---

### Task 9: Operational audit coverage

**Files:** `src/ai_hq/tool_gateway/service.py src/ai_hq/ledger/`

**Tests:** `tests/test_operational_audit.py`

**Contract:** Verify the Operations Ledger can reconstruct mission id, agent key, capability, logical target, safety/approval outcome, execution state, and structured result/failure without recording credentials, tokens, environment dumps, or other secrets. Add only missing events rather than duplicating Safety or Approval events.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: audit controlled operational outcomes`.

---

### Task 10: Autonomous worker integration

**Files:** `src/ai_hq/worker.py`

**Tests:** `tests/test_autonomous_worker_operations.py`

**Contract:** Wire the existing worker through MissionExecutor and ToolGateway. The permitted path is worker -> MissionExecutor -> ToolGateway. The worker must never call an adapter, Host Helper, subprocess, or privileged transport directly. Approval-waiting and completed steps must remain persisted across worker reconstruction.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: run autonomous missions through tool gateway worker`.

---

### Task 11: Security boundary regression suite

**Files:** `tests/test_operational_security_boundary.py`

**Tests:** `tests/test_operational_security_boundary.py`

**Contract:** Add static and behavioral tests prohibiting direct host execution from missions/workers, shell=True, os.system, os.popen, arbitrary service selection, arbitrary host selection, arbitrary paths, and arbitrary command fragments.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `test: enforce controlled operations security boundary`.

---

### Task 12: Controlled deployment and rollback

**Files:** `src/ai_hq/operations/`

**Tests:** `tests/test_deployment_operations.py`

**Contract:** Add deployment.deploy and deployment.rollback as explicit adapters. Command prefixes come only from trusted target configuration. Both operations require exact permission and mandatory approval. Rollback release identifiers allow only ASCII letters, digits, dot, underscore, and hyphen with a maximum length of 128 characters. No mission may supply an executable, command, or filesystem path.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `feat: add approved deployment and rollback operations`.

---

### Task 13: Stage 2 acceptance and regression

**Files:** `tests/`

**Tests:** `all Stage 2 tests plus python -m pytest -q`

**Contract:** Run all Stage 2 tests, existing Tool Gateway/Host Helper/autonomous mission tests, git diff --check, security-boundary checks, and the complete pytest suite. Review every Stage 2 specification acceptance criterion before any merge. Automated tests must perform no production mutation.

**Required verification:**

- [ ] Add explicit tests for this task's contract.
- [ ] Verify the new test fails before implementation.
- [ ] Implement only through the existing approved security boundaries.
- [ ] Verify the new test passes.
- [ ] Run relevant existing regression tests.
- [ ] Run `git diff --check`.
- [ ] Commit with `test: verify controlled operations stage 2`.

---

## Final Stage 2 Acceptance Gate

Before merge, verify all of these:

- [ ] `system.health.read` executes only through Tool Gateway.
- [ ] `service.status.read` executes only through Tool Gateway.
- [ ] `service.logs.read` is bounded and executes only through Tool Gateway.
- [ ] `service.restart` cannot execute without required approval.
- [ ] `deployment.deploy` cannot execute without required approval.
- [ ] `deployment.rollback` cannot execute without required approval.
- [ ] Unknown capabilities fail closed.
- [ ] Unknown targets fail closed.
- [ ] Missions cannot select arbitrary services, hosts, executables, paths, or commands.
- [ ] Simulation causes zero external mutation.
- [ ] Operational results are structured and auditable.
- [ ] Concurrent workers cannot execute the same mutating step twice.
- [ ] Autonomous missions remain behind Tool Gateway.
- [ ] Automated tests perform no production mutation.
- [ ] Full `python -m pytest -q` regression suite passes.
- [ ] `git diff --check origin/main...HEAD` passes.

## Production Enablement Gate

Completing Stage 2 code does not automatically enable real production operations.

After feature acceptance: push and review the feature branch, verify trusted production target configuration separately, merge only after review, rerun the full suite from `main`, deploy through the existing controlled release process, verify read-only operations first, and perform the first real mutation only as an explicitly approved operational test.

Stage 3 dashboard work remains separate.
