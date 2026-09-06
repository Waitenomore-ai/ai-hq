# Verified Repository Candidate Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI HQ derive Developer candidate identity and trusted evidence from an isolated repository workspace, then require QA to review that exact immutable candidate before Human Approval.

**Architecture:** Add a narrow repository-workspace abstraction inside `ai_hq.delivery`, separate from host-helper and production operations. Candidate verification will consume machine-observed `CandidateSnapshot` data instead of model-supplied file metadata; the runner will persist only machine-generated repository/test evidence and will fail closed if the workspace cannot be prepared, snapshotted, or tested.

**Tech Stack:** Python 3.12+, dataclasses, Protocol typing, SHA-256 canonical JSON hashing, pytest, existing SQLAlchemy delivery persistence.

**Spec:** `docs/superpowers/specs/2026-09-06-verified-repository-candidate-execution-design.md`

## Global Constraints

- Developer and QA MUST NOT gain production deployment authority.
- Developer and QA MUST NOT invoke the production host helper.
- Developer and QA MUST NOT restart services, mutate systemd, operate production Docker, or execute infrastructure/deployment actions.
- Developer and QA MUST NOT receive unrestricted shell access to the production host.
- Repository candidate work MUST occur in an isolated non-production workspace.
- Candidate identity MUST be derived from machine-observed repository state, not model-supplied `change_ref` values.
- Candidate evidence MUST distinguish machine-observed evidence from model assertions.
- QA MUST evaluate the exact immutable candidate produced by the Developer stage.
- Human Approval MUST remain a separate stage after QA passes.
- No implementation in this milestone may deploy AI HQ or any other application.

---

### Task 1: Repository workspace evidence contracts

**Files:**
- Create: `src/ai_hq/delivery/repository_workspace.py`
- Create: `tests/test_delivery_repository_workspace.py`

**Interfaces:**
- Produces `RepositoryWorkspace`, `CandidateSnapshot`, `TestEvidence`, and `RepositoryWorkspaceService`.
- `CandidateSnapshot.identity_payload(mission_id: str) -> dict[str, object]` returns canonical machine-observed identity inputs.
- No generic command execution interface is exposed.

- [ ] **Step 1: Write failing tests** for immutable dataclasses, required identity payload fields, digest-prefix validation, bounded test summary, and absence of generic `run`/`execute_shell` methods on the protocol.
- [ ] **Step 2: Run** `pytest tests/test_delivery_repository_workspace.py -v` and confirm failure because the module does not exist.
- [ ] **Step 3: Implement** frozen dataclasses and protocol with validation in `__post_init__`; require non-empty mission/repository/base/workspace IDs, tuple-only changed files, SHA-256-prefixed digests, boolean pass state, integer exit code, and a bounded non-empty summary.
- [ ] **Step 4: Run** `pytest tests/test_delivery_repository_workspace.py -v` and confirm pass.
- [ ] **Step 5: Commit** with message `feat: add repository workspace evidence contracts`.

### Task 2: Candidate verifier consumes machine snapshot

**Files:**
- Modify: `src/ai_hq/delivery/candidate_verifier.py`
- Modify: `tests/test_delivery_candidate_verifier.py`

**Interfaces:**
- `CandidateVerifier.verify(*, mission_id: str, proposal: Mapping[str, Any], snapshot: CandidateSnapshot, test_evidence: TestEvidence) -> VerifiedCandidate`
- `VerifiedCandidate.changed_files` remains a list for compatibility with persistence.
- Trusted evidence contains candidate identity fields and machine test evidence; model-provided change refs, changed files, and test claims are excluded.

- [ ] **Step 1: Add failing tests** proving `changed_files` and identity come from `CandidateSnapshot`, two identical snapshots hash identically, snapshot changes alter `change_ref`, model-supplied `change_ref` is ignored, and model evidence is excluded.
- [ ] **Step 2: Run** `pytest tests/test_delivery_candidate_verifier.py -v` and confirm failures against the old signature/behavior.
- [ ] **Step 3: Implement** canonical hashing over `snapshot.identity_payload(mission_id)` only. Preserve the human-readable proposal summary as untrusted descriptive metadata, but construct trusted evidence from snapshot fields plus `TestEvidence`.
- [ ] **Step 4: Run** `pytest tests/test_delivery_candidate_verifier.py -v` and confirm pass.
- [ ] **Step 5: Commit** with message `feat: verify candidates from repository snapshots`.

### Task 3: Runner orchestrates workspace -> snapshot -> tests -> verification

**Files:**
- Modify: `src/ai_hq/delivery/agent_runner.py`
- Modify: `tests/test_delivery_agent_runner.py`

**Interfaces:**
- `DeliveryAgentRunner(..., workspace_service: RepositoryWorkspaceService, candidate_verifier: CandidateVerifier)`
- `run_developer(mission_id: str)` prepares a workspace, invokes Developer planning, snapshots the workspace, runs the fixed test profile, verifies the machine state, then persists the candidate.
- Existing QA call continues to receive exact persisted `change_ref` and evidence.

- [ ] **Step 1: Add failing tests** with a fake workspace service proving prepare/snapshot/test are called in order, persisted files come from snapshot not model output, test failures are persisted as machine evidence but do not masquerade as model evidence, workspace/snapshot/test exceptions prevent runtime handoff, and QA gets exact persisted candidate identity.
- [ ] **Step 2: Run** `pytest tests/test_delivery_agent_runner.py -v` and confirm expected failures.
- [ ] **Step 3: Implement** workspace orchestration without adding any subprocess, host-helper, deployment, service-management, Docker, or production operations dependency to the runner.
- [ ] **Step 4: Run** `pytest tests/test_delivery_agent_runner.py -v` and confirm pass.
- [ ] **Step 5: Commit** with message `feat: orchestrate verified repository candidates`.

### Task 4: Trust-boundary and approval regression coverage

**Files:**
- Create: `tests/test_delivery_repository_security_boundary.py`
- Modify: `tests/test_delivery_orchestration.py`
- Modify only if required for compatibility: `src/ai_hq/delivery/runtime.py`, `src/ai_hq/delivery/service.py`

**Interfaces:**
- Delivery persistence keeps the immutable `change_ref`, machine-derived `changed_files`, and trusted evidence.
- Existing `record_qa_result` exact-reference validation remains unchanged.
- QA PASS still creates a real Human Approval request and never deploys.

- [ ] **Step 1: Add failing/guard tests** that AST-inspect Developer/QA candidate modules for prohibited imports/calls (`ai_hq.host_helper`, deployment adapters, `subprocess`, service restart, production Docker) and verify a QA pass still transitions to `WAITING_APPROVAL` with the same `change_ref`.
- [ ] **Step 2: Run** focused security and orchestration tests.
- [ ] **Step 3: Make only compatibility changes** required by the new evidence shape; do not broaden authority or modify production execution paths.
- [ ] **Step 4: Run** focused delivery suite: `pytest tests/test_delivery_repository_workspace.py tests/test_delivery_candidate_verifier.py tests/test_delivery_agent_runner.py tests/test_delivery_orchestration.py tests/test_delivery_runtime.py tests/test_delivery_repository_security_boundary.py -v`.
- [ ] **Step 5: Commit** with message `test: enforce repository candidate trust boundary`.

### Task 5: Full regression and final verification

**Files:**
- No feature files unless verification exposes a defect.

**Interfaces:**
- Branch must preserve all existing production and approval boundaries.

- [ ] **Step 1: Run** full `pytest` suite.
- [ ] **Step 2: Run** AST/security boundary checks for delivery modules.
- [ ] **Step 3: Review** final diff for accidental production authority, imports, generic shell APIs, deployment behavior, automatic merge/push/deploy behavior, or changes outside the approved scope.
- [ ] **Step 4: Verify** branch CI/status is green for the final commit.
- [ ] **Step 5: Do not deploy.** Report final commit, tests/status, remaining limitations, and the next human decision only if one is genuinely required.
