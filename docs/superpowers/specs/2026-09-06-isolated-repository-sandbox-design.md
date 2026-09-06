# Isolated Repository Sandbox Design

**Status:** Approved in chat on 2026-09-06.

## Purpose

Give AI HQ a real, machine-verifiable way to create and test repository candidates without granting Developer or QA production execution authority. This milestone implements the repository-side execution boundary beneath the existing Developer → verified candidate → QA → Human Approval orchestration.

The first supported repository is AI HQ itself. The design keeps repository selection behind a registry so DripVid can be added later without changing the authority model.

## Non-negotiable security properties

1. Developer and QA receive no production deployment authority.
2. Developer and QA receive no arbitrary shell or command execution API.
3. The sandbox cannot invoke AI HQ's production host helper, service-management adapters, production Docker controls, or deployment adapters.
4. Repository work occurs only inside a disposable, non-production workspace rooted under a configured sandbox root.
5. File operations accept normalized repository-relative paths only. Absolute paths, `..` traversal, and symlink escapes fail closed.
6. Test commands are selected from a trusted repository profile. Models cannot provide command strings, executables, arguments, environment overrides, or working directories.
7. Candidate identity and evidence derive from machine-observed workspace state.
8. The sandbox cannot merge, push, deploy, restart services, or mutate production.
9. QA reviews the exact immutable candidate produced from the sandbox snapshot.
10. This milestone does not deploy AI HQ or any application.

## Architecture

### Repository registry

A trusted registry maps a logical repository key to a fixed `RepositoryProfile`. The first profile is `ai-hq`.

A profile contains trusted configuration such as:

- logical repository key
- source repository location known to AI HQ configuration
- permitted base reference
- fixed test profile
- sandbox workspace policy

Repository profiles are created by application configuration, not by model output. A model may request a logical repository key already present in the registry; it cannot supply a filesystem source path or arbitrary remote URL.

### Sandbox workspace

The concrete workspace service implements the existing `RepositoryWorkspaceService` boundary and owns all filesystem/process interaction required for candidate work.

`prepare()` creates a disposable workspace under the configured sandbox root from the trusted repository profile and records the base repository state. The returned `RepositoryWorkspace` contains only logical identity (`mission_id`, repository key, base ref, workspace id); it does not expose production paths to model-backed agents.

### Typed file changes

The service adds a narrow typed mutation boundary rather than a generic command API.

```python
@dataclass(frozen=True)
class FileChange:
    path: str
    operation: FileOperation
    content: str | None = None

class FileOperation(StrEnum):
    WRITE = "write"
    DELETE = "delete"
```

The workspace service exposes an operation equivalent to:

```python
def apply_changes(
    self,
    *,
    workspace: RepositoryWorkspace,
    changes: tuple[FileChange, ...],
) -> CandidateSnapshot: ...
```

Rules:

- `path` must be a normalized relative repository path.
- absolute paths and traversal are rejected.
- parent directories may be created only inside the workspace.
- writes through symlinks or paths resolving outside the workspace are rejected.
- `WRITE` requires text content.
- `DELETE` requires no content and may delete only files inside the workspace.
- no chmod, executable-bit manipulation, arbitrary rename, device access, socket access, or command execution is exposed.

The first milestone intentionally supports whole-file text writes/deletes rather than arbitrary patch programs. This is simpler to validate and keeps the model-facing authority narrow.

### Machine snapshot

After changes, `snapshot()` derives the actual changed-file set from workspace state rather than trusting model claims. It returns the existing immutable `CandidateSnapshot` contract:

- workspace id
- repository key
- base ref
- sorted changed files
- diff digest
- content digest

The snapshot is deterministic for identical repository state.

The service records an internal snapshot fingerprint so later operations can detect workspace mutation after verification.

### Fixed test execution

`run_tests()` runs only the test profile attached to the trusted `RepositoryProfile`. There is no `run(command)` method and no model-provided command input.

For AI HQ, the initial trusted verification profile mirrors CI gates needed for candidate validation:

1. Ruff lint over `src` and `tests`.
2. Full pytest suite.

Compose validation remains CI/integration verification rather than a Developer-controlled repository test because it crosses into container tooling and is not necessary for the model-facing coding capability.

The concrete process runner is private to the sandbox implementation. It receives only commands defined in trusted application code/configuration. The public Developer/QA interfaces never receive subprocess handles, command strings, environment mutation, shell flags, or executable paths.

Test output is bounded before becoming `TestEvidence`. The evidence contains pass/fail, exit code, bounded summary, and deterministic evidence digest. Raw unbounded logs are not persisted through the delivery boundary.

### Candidate verification integration

The existing `CandidateVerifier` remains the trust boundary for candidate identity. It receives the machine `CandidateSnapshot` and `TestEvidence` and derives `sha256:<digest>` from trusted state.

Model-supplied `change_ref`, changed-file claims, test counts, and evidence remain untrusted and do not enter candidate identity.

A failed machine test blocks verification. A stale or mutated workspace after snapshot fails closed and cannot silently become a different candidate under the same reference.

### Developer integration

The model-backed Developer remains a planner/reasoner. It may propose typed file changes for the selected registered repository. A coordinator validates the structured response and passes only `FileChange` values to the workspace service.

Developer never receives:

- sandbox filesystem paths
- arbitrary shell
- subprocess
- host helper
- deployment adapters
- systemd/service restart
- production Docker
- git push/merge authority

After mutation, the coordinator asks the sandbox for machine snapshot and test evidence, then hands those to `CandidateVerifier` and the existing delivery runtime.

### QA integration

QA receives the persisted immutable candidate reference plus machine-observed snapshot/test evidence. QA may inspect the candidate through read-only repository abstractions and produce its independent `PASSED`/`FAILED` result.

QA cannot modify the candidate, reroute it to a different workspace, alter candidate identity, deploy it, or run arbitrary commands.

### Human Approval

There is no authority change to Human Approval. A verified candidate that passes QA becomes eligible for the existing Human Approval workflow. Human Approval does not implicitly grant Developer or QA any production capability.

## Data flow

1. A mission reaches the Developer delivery stage.
2. AI HQ resolves logical repository key `ai-hq` through the trusted registry.
3. Sandbox prepares a disposable workspace from the trusted base repository state.
4. Developer returns structured whole-file write/delete proposals.
5. Coordinator validates the proposal and constructs typed `FileChange` values.
6. Sandbox applies changes inside the workspace.
7. Sandbox snapshots actual repository state and derives changed files/digests.
8. Sandbox runs the trusted AI HQ test profile.
9. `CandidateVerifier` derives immutable candidate identity from machine snapshot/test evidence.
10. `DeliveryRuntime` persists the verified candidate.
11. QA evaluates that exact candidate.
12. QA failure follows the existing failure flow; QA pass proceeds to existing Human Approval.
13. Nothing in this flow merges, pushes, deploys, restarts services, or mutates production.

## Failure handling

The sandbox fails closed when:

- repository key is not registered
- sandbox root is unavailable
- source repository/base state cannot be prepared
- a path is absolute, traverses upward, or escapes via symlink
- a requested operation is unsupported
- snapshot derivation fails
- trusted test execution cannot start or exceeds its configured timeout
- tests fail
- workspace state changes after the verified snapshot
- machine evidence is missing or inconsistent

Failure does not progress to QA as a verified candidate.

## Isolation boundary

The repository sandbox belongs under the delivery/repository-workspace area and must not import or depend on the production host-helper subsystem. Tests will inspect imports/source to enforce this.

The private fixed-command process runner is an implementation detail of the sandbox. Security depends on the absence of a public arbitrary-command surface and on commands being selected exclusively from trusted repository profiles.

The configured sandbox root must not be a production application/release directory. Production configuration must explicitly provide an isolated sandbox root; startup/config validation rejects unsafe overlap where it can be determined from configured paths.

## Testing strategy

Implementation follows TDD and preserves the current green CI baseline.

Required tests include:

- registered AI HQ profile resolves deterministically
- unknown repository fails closed
- workspace is created beneath sandbox root
- model/user values cannot choose arbitrary source filesystem path
- normalized relative writes succeed
- nested writes stay inside workspace
- deletes stay inside workspace
- absolute path is rejected
- `..` traversal is rejected
- symlink escape is rejected
- unsupported mutation operation is impossible through typed contract
- changed files come from actual workspace state, not model metadata
- snapshot digests are deterministic
- identical workspace state produces identical snapshot identity
- changed workspace state changes snapshot identity
- test command is selected from trusted AI HQ profile
- no model-provided command input exists
- test failure blocks candidate verification
- test evidence is bounded and machine-generated
- stale workspace after snapshot fails closed
- Developer/QA modules cannot import sandbox private process execution
- Developer/QA remain unable to import/invoke host helper, deployment adapters, service restart, production Docker, or arbitrary subprocess
- existing CandidateVerifier tests continue passing
- existing exact-candidate QA tests continue passing
- existing Human Approval transition remains unchanged
- full lint, pytest, and CI Compose validation pass before the milestone is considered ready

## Scope exclusions

This milestone does not add:

- DripVid repository execution (registry must make it straightforward later)
- autonomous merge or push
- production deployment
- production host access
- unrestricted shell
- arbitrary test commands
- package installation selected by a model
- generalized CI/CD orchestration
- secrets-management changes
- service restart authority
- production Docker authority

## Success criteria

The milestone succeeds when AI HQ can take a Developer's structured file-change proposal for the registered AI HQ repository, apply it only inside an isolated disposable workspace, derive the real changed-file/digest state, run a fixed trusted test profile, create machine evidence for the existing `CandidateVerifier`, and pass the exact immutable candidate to QA while automated security tests prove that Developer and QA still have no production execution authority.