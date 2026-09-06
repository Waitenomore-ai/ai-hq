# Verified Repository Candidate Execution Design

## Status
Approved for design by the user on 2026-09-06. This document defines the security and architecture contract for implementation.

## Purpose

AI HQ already has a Developer -> verified candidate -> QA -> Human Approval orchestration boundary. The current Developer and QA model-backed agents produce and review structured metadata, but the Developer can still only claim that files changed or tests ran. This design adds real, machine-verifiable repository work without granting Developer or QA production authority.

The goal is to let AI HQ create an isolated candidate workspace for a mission, allow the Developer role to propose repository changes inside that workspace, derive candidate identity and evidence from the actual workspace state, and let QA independently inspect and test that exact candidate before Human Approval becomes eligible.

## Non-negotiable security properties

1. Developer and QA MUST NOT gain production deployment authority.
2. Developer and QA MUST NOT invoke the production host helper.
3. Developer and QA MUST NOT restart services, mutate systemd, operate production Docker, or execute infrastructure/deployment actions.
4. Developer and QA MUST NOT receive unrestricted shell access to the production host.
5. Repository candidate work MUST occur in an isolated non-production workspace.
6. Candidate identity MUST be derived from machine-observed repository state, not model-supplied `change_ref` values.
7. Candidate evidence MUST distinguish machine-observed evidence from model assertions.
8. QA MUST evaluate the exact immutable candidate produced by the Developer stage.
9. Human Approval MUST remain a separate stage after QA passes.
10. No implementation in this milestone may deploy AI HQ or any other application.

## Existing architecture to preserve

The implementation must extend rather than replace the established delivery subsystem:

- `DeliveryService`
- `DeliveryRuntime`
- `DeliveryAgentRunner`
- `ModelBackedDeveloperAgent`
- `ModelBackedQAAgent`
- `CandidateVerifier`
- `VerifiedCandidate`
- persisted delivery state and real `ApprovalRequest` integration
- autonomous mission/delivery integration
- Developer/QA Operations Floor state

The current `DeliveryAgentRunner` is intentionally free of production execution capability. That remains true after this change.

## Recommended approach

Introduce a purpose-built repository workspace boundary under `src/ai_hq/delivery/` rather than routing Developer or QA through the general production operations/tool-gateway path.

This boundary exposes only the minimum repository capabilities required for candidate creation and review. It is not a generic shell abstraction.

The workspace service owns repository state; agents only request high-level candidate operations through typed interfaces. Machine-observed results are returned as immutable evidence structures.

## Components

### 1. RepositoryWorkspace

A small protocol/value boundary representing one isolated candidate workspace for one mission.

Required identity fields:

- `mission_id: str`
- `repository: str`
- `base_ref: str`
- `workspace_id: str`

A workspace must not expose production filesystem paths to model-backed agents.

### 2. RepositoryWorkspaceService

A controlled service responsible for creating and inspecting candidate workspaces.

Initial interface:

```python
class RepositoryWorkspaceService(Protocol):
    def prepare(self, *, mission_id: str) -> RepositoryWorkspace: ...
    def snapshot(self, *, workspace: RepositoryWorkspace) -> CandidateSnapshot: ...
    def run_tests(self, *, workspace: RepositoryWorkspace) -> TestEvidence: ...
```

The implementation may later support typed patch application, but this milestone must avoid generic `run(command)` or arbitrary shell APIs.

### 3. CandidateSnapshot

Machine-generated immutable evidence describing the actual repository candidate.

Required fields:

- `workspace_id: str`
- `repository: str`
- `base_ref: str`
- `changed_files: tuple[str, ...]`
- `diff_digest: str`
- `content_digest: str`

`diff_digest` and `content_digest` use SHA-256 canonical hashing.

### 4. TestEvidence

Machine-generated test execution evidence.

Required fields:

- `passed: bool`
- `exit_code: int`
- `summary: str`
- `evidence_digest: str`

The stored summary must be bounded in size and must not be treated as executable input.

### 5. CandidateVerifier evolution

`CandidateVerifier` currently derives identity from model-provided summary and changed file metadata. It must evolve so trusted identity is based on `CandidateSnapshot` plus the mission identifier.

The trusted candidate identity payload should include:

```json
{
  "mission_id": "...",
  "repository": "...",
  "base_ref": "...",
  "workspace_id": "...",
  "changed_files": ["..."],
  "diff_digest": "sha256:...",
  "content_digest": "sha256:..."
}
```

The resulting `change_ref` remains `sha256:<digest>`.

Model-supplied `change_ref`, claimed test counts, and claimed changed files do not become trusted evidence.

### 6. Developer boundary

The Developer model may still produce a concise implementation summary and intent metadata, but the trusted runtime must obtain the actual changed file list and candidate digests from the workspace service.

The Developer interface must not receive host-helper, tool-gateway, deployment, systemd, Docker-production, or arbitrary shell objects.

### 7. QA boundary

QA receives the persisted immutable `change_ref`, machine-generated candidate snapshot evidence, and machine-generated test evidence. QA may produce an independent review result and commentary, but it cannot alter the candidate identity.

Before a QA pass is persisted, the runtime must confirm that QA is reviewing the same `change_ref` produced by candidate verification.

### 8. Human Approval

No change to the authority model. A QA pass may make the delivery eligible for the existing Human Approval request. It does not authorize deployment.

## Data flow

1. Mission enters the Developer delivery stage.
2. AI HQ prepares an isolated repository workspace for the mission.
3. Developer proposes candidate changes inside the controlled workspace boundary.
4. AI HQ snapshots the workspace.
5. AI HQ runs the permitted test profile in that workspace.
6. `CandidateVerifier` derives the trusted immutable candidate reference from machine-observed repository state.
7. `DeliveryRuntime` persists the candidate and trusted evidence.
8. QA receives the exact persisted candidate reference and trusted evidence.
9. QA independently reviews the candidate and records PASSED or FAILED.
10. PASSED continues to the existing Human Approval stage; FAILED returns through the existing delivery flow.

## Error handling

Workspace failures, snapshot failures, invalid repository state, and test-runner failures must fail closed. A delivery must not progress to QA when trusted candidate evidence cannot be produced.

A model parsing failure remains a model failure and must never be converted into machine evidence.

If a workspace snapshot changes after candidate verification, QA must reject the stale candidate rather than silently re-hash and continue.

## Security enforcement

The implementation must include explicit tests that inspect the Developer/QA delivery modules for prohibited authority acquisition.

At minimum, the Developer/QA candidate path must not directly import or invoke:

- `ai_hq.host_helper`
- production deployment adapters
- service restart operations
- arbitrary subprocess execution
- production Docker controls

The repository workspace implementation itself must remain physically and logically separate from production host-helper execution.

## Testing strategy

Use TDD and preserve all existing delivery tests.

New tests must cover:

- deterministic repository snapshot identity
- changed files derived from workspace state rather than model output
- model-supplied `change_ref` ignored at the trusted boundary
- machine-generated test evidence persisted separately from model assertions
- QA receives and reviews the exact persisted candidate
- stale or changed workspace rejected after verification
- workspace/test failure blocks progression to QA
- Developer/QA modules cannot import prohibited production execution capabilities
- existing Human Approval transition remains unchanged

A complete regression run must pass before the branch is considered ready.

## Scope exclusions

This milestone does not add:

- autonomous production deployment
- unrestricted shell for Developer or QA
- production host access for Developer or QA
- generalized CI/CD orchestration
- remote repository push authority from AI agents
- automatic merging
- service restart authority
- secrets management changes

Those require separate designs and approvals.

## Success criteria

The milestone is complete when AI HQ can represent a real repository candidate using machine-observed workspace state, independently verify that exact candidate in QA, preserve Human Approval as the next authority boundary, and demonstrate through tests that Developer and QA still cannot execute production operations.
