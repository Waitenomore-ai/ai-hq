# Isolated Repository Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give AI HQ a concrete isolated repository sandbox that can apply typed file changes, derive machine snapshots, and run a fixed trusted test profile without granting Developer or QA production authority.

**Architecture:** Extend the existing `ai_hq.delivery.repository_workspace` contracts with typed file changes and a repository profile registry, then add a concrete sandbox service that owns all filesystem/process interaction under a configured sandbox root. The public boundary exposes only trusted high-level operations; command selection remains internal to repository profiles, while existing `CandidateVerifier`, `DeliveryAgentRunner`, QA, and Human Approval boundaries remain unchanged.

**Tech Stack:** Python 3.12+, dataclasses, StrEnum, Protocol typing, pathlib, tempfile/shutil, hashlib, subprocess used only inside the private sandbox implementation, pytest, Ruff 0.15.x, existing delivery orchestration.

**Spec:** `docs/superpowers/specs/2026-09-06-isolated-repository-sandbox-design.md`

## Global Constraints

- Developer and QA receive no production deployment authority.
- Developer and QA receive no arbitrary shell or command execution API.
- The sandbox cannot invoke AI HQ's production host helper, service-management adapters, production Docker controls, or deployment adapters.
- Repository work occurs only inside a disposable, non-production workspace rooted under a configured sandbox root.
- File operations accept normalized repository-relative paths only. Absolute paths, `..` traversal, and symlink escapes fail closed.
- Test commands are selected from a trusted repository profile. Models cannot provide command strings, executables, arguments, environment overrides, or working directories.
- Candidate identity and evidence derive from machine-observed workspace state.
- The sandbox cannot merge, push, deploy, restart services, or mutate production.
- QA reviews the exact immutable candidate produced from the sandbox snapshot.
- This milestone does not deploy AI HQ or any application.
- First supported repository is `ai-hq`; DripVid is out of scope for this milestone.

## File Structure

- Modify `src/ai_hq/delivery/repository_workspace.py` — typed mutation contracts (`FileOperation`, `FileChange`) and protocol extension.
- Create `src/ai_hq/delivery/repository_profiles.py` — trusted `RepositoryProfile` and `RepositoryProfileRegistry`, including the AI HQ profile.
- Create `src/ai_hq/delivery/repository_sandbox.py` — concrete isolated workspace service, path validation, snapshot/digest logic, private trusted test runner.
- Modify `src/ai_hq/config.py` — sandbox root and AI HQ source repository configuration with production-safe validation.
- Modify `src/ai_hq/delivery/agent_runner.py` — apply Developer typed file changes through the workspace service before snapshot/test verification.
- Modify `src/ai_hq/delivery/model_agents.py` — Developer structured output includes typed `changes`; no commands or paths outside repository-relative file names.
- Modify `src/ai_hq/worker.py` only if required to wire the trusted profile/sandbox service into the autonomous delivery runner.
- Create `tests/test_delivery_repository_profiles.py` — profile registry tests.
- Create `tests/test_delivery_repository_sandbox.py` — workspace isolation, path safety, snapshot, and test-profile tests.
- Modify `tests/test_delivery_repository_workspace.py` — typed mutation contract tests.
- Modify `tests/test_delivery_agent_runner.py` — apply-changes orchestration tests.
- Modify `tests/test_delivery_model_agents.py` — Developer typed change parsing tests.
- Modify `tests/test_delivery_repository_security_boundary.py` — enforce private subprocess boundary and prohibited production authority.
- Modify `tests/test_config.py` only if existing config tests are located there; otherwise add focused sandbox config tests in the current config test module.

---

### Task 1: Typed repository mutation contracts

**Files:**
- Modify: `src/ai_hq/delivery/repository_workspace.py`
- Modify: `tests/test_delivery_repository_workspace.py`

**Interfaces:**
- Produces `FileOperation(StrEnum)` with `WRITE` and `DELETE`.
- Produces immutable `FileChange(path: str, operation: FileOperation, content: str | None = None)`.
- Extends `RepositoryWorkspaceService` with `apply_changes(*, workspace: RepositoryWorkspace, changes: tuple[FileChange, ...]) -> CandidateSnapshot`.
- `FileChange` validates only data-shape invariants; filesystem containment remains the concrete sandbox's responsibility.

- [ ] **Step 1: Add failing tests for typed mutation values**

```python
from dataclasses import FrozenInstanceError

import pytest

from ai_hq.delivery.repository_workspace import FileChange, FileOperation


def test_file_change_is_immutable_and_write_requires_content():
    change = FileChange(
        path="src/example.py",
        operation=FileOperation.WRITE,
        content="print('ok')\n",
    )

    with pytest.raises(FrozenInstanceError):
        change.path = "other.py"

    with pytest.raises(ValueError, match="content"):
        FileChange(path="src/example.py", operation=FileOperation.WRITE)


def test_delete_rejects_content():
    with pytest.raises(ValueError, match="content"):
        FileChange(
            path="src/example.py",
            operation=FileOperation.DELETE,
            content="not allowed",
        )
```

- [ ] **Step 2: Add a protocol guard proving no arbitrary command API exists**

```python

def test_workspace_protocol_exposes_typed_changes_not_shell():
    names = set(RepositoryWorkspaceService.__dict__)

    assert "apply_changes" in names
    assert "run" not in names
    assert "execute" not in names
    assert "execute_shell" not in names
    assert "command" not in names
```

- [ ] **Step 3: Run focused tests**

Run: `pytest tests/test_delivery_repository_workspace.py -v`

Expected: FAIL because `FileOperation`, `FileChange`, and `apply_changes` do not exist.

- [ ] **Step 4: Implement the minimal contracts**

```python
from enum import StrEnum


class FileOperation(StrEnum):
    WRITE = "write"
    DELETE = "delete"


@dataclass(frozen=True)
class FileChange:
    path: str
    operation: FileOperation
    content: str | None = None

    def __post_init__(self) -> None:
        path = _required(self.path, field="path")
        if not isinstance(self.operation, FileOperation):
            raise TypeError("operation must be a FileOperation")
        if self.operation is FileOperation.WRITE:
            if not isinstance(self.content, str):
                raise ValueError("write content is required")
        elif self.content is not None:
            raise ValueError("delete content must be empty")
        object.__setattr__(self, "path", path)
```

Extend the protocol exactly as specified in the Interfaces block.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_delivery_repository_workspace.py -v`

Expected: PASS.

Commit: `feat: add typed repository file changes`

---

### Task 2: Trusted AI HQ repository profile registry

**Files:**
- Create: `src/ai_hq/delivery/repository_profiles.py`
- Create: `tests/test_delivery_repository_profiles.py`

**Interfaces:**
- Produces frozen `RepositoryProfile(key: str, source_path: Path, base_ref: str, test_commands: tuple[tuple[str, ...], ...], test_timeout_seconds: float)`.
- Produces `RepositoryProfileRegistry(profiles: tuple[RepositoryProfile, ...])`.
- Produces `RepositoryProfileRegistry.get(key: str) -> RepositoryProfile`, raising `KeyError` for unknown keys.
- Produces `build_ai_hq_repository_profile(*, source_path: Path, base_ref: str = "HEAD") -> RepositoryProfile` with fixed commands `((sys.executable, "-m", "ruff", "check", "src", "tests"), (sys.executable, "-m", "pytest", "-q"))`.
- Models never construct or modify a profile.

- [ ] **Step 1: Write failing registry tests**

```python
from pathlib import Path

import pytest

from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
)


def test_ai_hq_profile_has_fixed_trusted_test_commands(tmp_path):
    profile = build_ai_hq_repository_profile(source_path=tmp_path)

    assert profile.key == "ai-hq"
    assert profile.source_path == tmp_path.resolve()
    assert profile.base_ref == "HEAD"
    assert len(profile.test_commands) == 2
    assert profile.test_commands[0][1:4] == ("-m", "ruff", "check")
    assert profile.test_commands[1][1:3] == ("-m", "pytest")


def test_unknown_repository_fails_closed(tmp_path):
    registry = RepositoryProfileRegistry(
        (build_ai_hq_repository_profile(source_path=tmp_path),)
    )

    with pytest.raises(KeyError, match="unknown repository"):
        registry.get("dripvid")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_delivery_repository_profiles.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement frozen profile and registry**

Use `Path.resolve()` at profile construction, reject missing/non-directory sources, reject duplicate keys, reject empty/non-tuple test commands, reject non-positive timeout, and keep command tuples immutable.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_delivery_repository_profiles.py -v`

Expected: PASS.

Commit: `feat: add trusted repository profile registry`

---

### Task 3: Sandbox configuration boundary

**Files:**
- Modify: `src/ai_hq/config.py`
- Modify: existing config tests (find exact module before editing; likely `tests/test_config.py` or `tests/test_security_config.py`)

**Interfaces:**
- Adds `repository_sandbox_root: str | None = None`.
- Adds `ai_hq_repository_source: str | None = None`.
- Production validation requires both values before repository sandbox wiring is enabled by the worker; the settings object itself may remain valid without them while the feature is not wired.
- Adds helper properties returning resolved `Path` values when configured.
- Rejects a sandbox root equal to the configured source path or nested inside it; rejects source path nested inside sandbox root.

- [ ] **Step 1: Locate current Settings tests and add focused failing cases**

Required assertions:

```python
assert settings.repository_sandbox_root_path == Path(root).resolve()
assert settings.ai_hq_repository_source_path == Path(source).resolve()
```

and construction/config validation rejects overlapping source/sandbox paths with `ValueError` containing `sandbox`.

- [ ] **Step 2: Run only the discovered config test module**

Expected: FAIL because the new fields/properties do not exist.

- [ ] **Step 3: Implement path properties and overlap validation**

Use `Path(...).expanduser().resolve()` for configured values. Implement a validator that rejects equality or parent/child overlap between the source and sandbox root. Do not create directories inside Settings validation.

- [ ] **Step 4: Run config tests and commit**

Commit: `feat: configure isolated repository sandbox`

---

### Task 4: Concrete isolated sandbox workspace preparation and path safety

**Files:**
- Create: `src/ai_hq/delivery/repository_sandbox.py`
- Create: `tests/test_delivery_repository_sandbox.py`

**Interfaces:**
- Produces `IsolatedRepositorySandbox(RepositoryWorkspaceService)` initialized with `profile_registry: RepositoryProfileRegistry`, `repository_key: str`, and `sandbox_root: Path`.
- Maintains private mapping from `workspace_id` to internal workspace path/profile/base snapshot.
- `prepare(mission_id: str) -> RepositoryWorkspace` copies the trusted source repository into a fresh workspace beneath sandbox root.
- `apply_changes(...) -> CandidateSnapshot` validates containment before write/delete.
- No public command method exists.

- [ ] **Step 1: Write failing prepare/isolation tests**

Test that a prepared workspace:

```python
workspace = sandbox.prepare(mission_id="mission-1")
assert workspace.repository == "ai-hq"
assert workspace.workspace_id
assert all(str(path).startswith(str(sandbox_root.resolve())) for path in sandbox._test_workspace_paths())
```

Expose `_test_workspace_paths()` only if needed as a clearly test-only read-only helper; prefer testing observable filesystem state through a known sandbox-root glob if possible.

- [ ] **Step 2: Add path rejection tests**

Required cases:

```python
@pytest.mark.parametrize("path", ["/etc/passwd", "../escape.py", "src/../../escape.py"])
def test_apply_changes_rejects_escaping_paths(...): ...
```

Create a symlink inside the workspace that points outside and prove `WRITE` through it raises `ValueError` containing `escape` or `symlink`.

- [ ] **Step 3: Add successful write/delete tests**

Verify nested text writes create parents only inside workspace, and deletes affect only files inside that workspace while leaving the trusted source repository unchanged.

- [ ] **Step 4: Run focused sandbox tests**

Run: `pytest tests/test_delivery_repository_sandbox.py -v`

Expected: FAIL because implementation does not exist.

- [ ] **Step 5: Implement preparation and typed changes**

Implementation requirements:

```python
candidate = workspace_root / relative_path
resolved_parent = candidate.parent.resolve()
if workspace_root != resolved_parent and workspace_root not in resolved_parent.parents:
    raise ValueError("repository path escapes workspace")
```

Also reject any existing symlink encountered in the candidate path chain. Use `shutil.copytree(..., symlinks=True)` so existing repository symlinks remain visible to validation rather than silently followed during copy. Generate `workspace_id` from UUID. Never copy into or operate on the source path itself.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/test_delivery_repository_sandbox.py -v`

Expected: path/isolation/write/delete tests PASS.

Commit: `feat: add isolated repository sandbox`

---

### Task 5: Deterministic machine snapshot and stale-workspace detection

**Files:**
- Modify: `src/ai_hq/delivery/repository_sandbox.py`
- Modify: `tests/test_delivery_repository_sandbox.py`

**Interfaces:**
- `snapshot(workspace) -> CandidateSnapshot` derives actual changed files by comparing the workspace file tree against the copied base-state manifest captured during `prepare()`.
- Snapshot uses sorted repository-relative POSIX paths.
- `diff_digest` hashes canonical changed-file metadata and changed content/deletion markers.
- `content_digest` hashes canonical complete candidate content for all regular files under workspace, excluding `.git` metadata if present.
- Service records latest snapshot fingerprint per workspace.
- `run_tests(workspace)` refuses to run if workspace state no longer matches the last snapshot fingerprint.

- [ ] **Step 1: Add failing deterministic snapshot tests**

Required behaviors:

```python
first = sandbox.snapshot(workspace=workspace)
second = sandbox.snapshot(workspace=workspace)
assert first == second
assert first.changed_files == ("src/new.py",)
```

Changing file content must change both candidate snapshot identity inputs; deleting a file must appear in `changed_files` and alter digests.

- [ ] **Step 2: Add stale mutation test**

After `snapshot()`, mutate a workspace file directly through the test fixture, then assert `run_tests()` raises `RuntimeError` containing `stale` before invoking the process runner.

- [ ] **Step 3: Implement canonical manifests/digests**

Use SHA-256 over JSON encoded with `sort_keys=True`, `separators=(",", ":")`, UTF-8. File manifests include relative path plus SHA-256 of bytes; deleted paths include a fixed deletion marker in diff material. Ignore `.git/**` if the trusted source contains Git metadata.

- [ ] **Step 4: Run sandbox tests and commit**

Run: `pytest tests/test_delivery_repository_sandbox.py -v`

Expected: PASS.

Commit: `feat: derive deterministic sandbox candidate snapshots`

---

### Task 6: Fixed trusted test profile execution

**Files:**
- Modify: `src/ai_hq/delivery/repository_sandbox.py`
- Modify: `tests/test_delivery_repository_sandbox.py`

**Interfaces:**
- Private `_run_profile_command(argv: tuple[str, ...], *, cwd: Path, timeout_seconds: float) -> subprocess.CompletedProcess[str]` may use `subprocess.run` with `shell=False`, `capture_output=True`, `text=True`, fixed `cwd`, and no model-provided environment.
- Public `run_tests(workspace) -> TestEvidence` iterates only `RepositoryProfile.test_commands`.
- Test evidence summary is bounded to the existing 4000-character `TestEvidence` maximum.
- Evidence digest hashes command-index, return codes, and bounded normalized outputs.

- [ ] **Step 1: Add failing fixed-command tests with a fake private runner**

Inject the private command execution dependency through constructor-only trusted code, e.g. `command_runner: Callable[..., CompletedProcess[str]] | None = None`, but do not expose it through Developer/QA. Assert exact commands passed to the fake equal the profile commands and no caller-supplied command argument exists on `run_tests`.

- [ ] **Step 2: Add pass/fail/timeout evidence tests**

A non-zero return from any fixed command produces `TestEvidence(passed=False, exit_code=<code>, ...)`; later commands need not run after first failure. Timeout converts to failed evidence or a fail-closed `RuntimeError` consistently; choose `RuntimeError("repository test profile timed out")` so no candidate verification occurs.

- [ ] **Step 3: Implement private process execution**

Use `subprocess.run(list(argv), cwd=workspace_path, shell=False, capture_output=True, text=True, timeout=timeout_seconds, check=False)` only inside `repository_sandbox.py`.

- [ ] **Step 4: Run sandbox tests and security grep/AST tests**

Run: `pytest tests/test_delivery_repository_sandbox.py tests/test_delivery_repository_security_boundary.py -v`

- [ ] **Step 5: Commit**

Commit: `feat: run trusted sandbox test profiles`

---

### Task 7: Developer structured file-change output

**Files:**
- Modify: `src/ai_hq/delivery/model_agents.py`
- Modify: `tests/test_delivery_model_agents.py`

**Interfaces:**
- Developer output retains `summary` and may retain legacy untrusted metadata for compatibility, but adds required `changes` list.
- Each change object must be exactly shaped as `{ "path": str, "operation": "write" | "delete", "content": str | null }`.
- Parser converts these into JSON-safe dictionaries only; `DeliveryAgentRunner` constructs trusted `FileChange` objects.
- Developer prompt explicitly forbids commands, shell, deployment, host-helper, systemd, Docker-production, push, and merge authority.

- [ ] **Step 1: Add failing parsing tests**

Test accepted write/delete change objects and rejection of missing path, invalid operation, write without string content, delete with content, non-list `changes`, and command-like top-level fields such as `command`, `argv`, or `shell` if present.

- [ ] **Step 2: Run model-agent tests**

Expected: FAIL against current Developer schema.

- [ ] **Step 3: Update Developer prompt and parser**

Prompt output shape:

```json
{
  "summary": "...",
  "changes": [
    {"path": "src/example.py", "operation": "write", "content": "..."},
    {"path": "src/obsolete.py", "operation": "delete", "content": null}
  ]
}
```

Reject prohibited command/control fields rather than ignoring them.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_delivery_model_agents.py -v`

Commit: `feat: structure developer repository file changes`

---

### Task 8: Runner applies typed changes before verification

**Files:**
- Modify: `src/ai_hq/delivery/agent_runner.py`
- Modify: `tests/test_delivery_agent_runner.py`

**Interfaces:**
- `run_developer(mission_id)` flow becomes `prepare -> Developer.execute -> parse FileChange tuple -> apply_changes -> run_tests -> CandidateVerifier.verify -> runtime.handoff_to_developer`.
- `apply_changes` returned snapshot is the snapshot passed to verifier; do not resnapshot silently after tests.
- Test failure remains fail closed before runtime handoff.

- [ ] **Step 1: Update fake workspace service and write failing order test**

Expected call order:

```python
[
    ("prepare", "mission-1"),
    ("apply_changes", "workspace-1", expected_changes),
    ("run_tests", "workspace-1"),
]
```

Assert model-provided changed files remain ignored and runtime persists snapshot-derived files.

- [ ] **Step 2: Add invalid Developer change test**

Malformed `changes` must raise before `apply_changes` and runtime handoff.

- [ ] **Step 3: Implement minimal runner conversion**

Construct `FileChange` using `FileOperation(value)` and tuple conversion. Do not import subprocess, host helper, operations, Docker, or deployment modules.

- [ ] **Step 4: Run focused delivery tests and commit**

Run: `pytest tests/test_delivery_agent_runner.py tests/test_delivery_candidate_verifier.py -v`

Commit: `feat: apply developer changes in repository sandbox`

---

### Task 9: Autonomous worker wiring for AI HQ sandbox

**Files:**
- Modify: `src/ai_hq/worker.py`
- Modify: worker/autonomous delivery tests, likely `tests/test_autonomous_worker_operations.py` and/or existing delivery worker tests

**Interfaces:**
- Worker builds `RepositoryProfileRegistry` with exactly the `ai-hq` profile from trusted Settings.
- Worker builds `IsolatedRepositorySandbox` only when `ai_hq_repository_source` and `repository_sandbox_root` are configured.
- If a mission produces a delivery candidate but sandbox configuration is absent, existing fail-closed behavior remains.
- No deployment or host-helper object is passed to Developer/QA delivery runner.

- [ ] **Step 1: Add failing configured-worker test**

Provide temp source/sandbox settings and assert the constructed delivery runner has a repository workspace service capable of preparing `ai-hq`.

- [ ] **Step 2: Preserve absent-config fail-closed regression**

Existing test must continue proving no direct unverified `DeliveryRuntime` handoff occurs when sandbox is unavailable.

- [ ] **Step 3: Implement wiring**

Keep source/sandbox values in Settings/application composition only. Do not add model-facing configuration parameters.

- [ ] **Step 4: Run worker/delivery tests and commit**

Run the exact affected worker test modules plus `tests/test_delivery_agent_runner.py`.

Commit: `feat: wire ai hq repository sandbox into worker`

---

### Task 10: Security boundary regression and full verification

**Files:**
- Modify: `tests/test_delivery_repository_security_boundary.py`
- No production feature files unless verification exposes a defect.

**Interfaces:**
- `repository_sandbox.py` is the only delivery module permitted to import `subprocess`.
- `agent_runner.py`, `model_agents.py`, `candidate_verifier.py`, `runtime.py`, and QA-facing modules remain prohibited from importing subprocess, host-helper, operations/deployment adapters, service restart, or production Docker.
- Sandbox source itself is prohibited from importing `ai_hq.host_helper`, `ai_hq.operations`, deployment adapters, Docker SDK, or service-management modules.

- [ ] **Step 1: Add AST security tests**

Parse delivery modules and assert:

```python
allowed_subprocess_modules = {"ai_hq.delivery.repository_sandbox"}
```

Only that module may import `subprocess`; no public function/method named `run`, `execute`, `execute_shell`, `deploy`, `push`, `merge`, or `restart` may be exposed by the sandbox service.

- [ ] **Step 2: Run focused security/delivery suite**

Run:

```bash
pytest \
  tests/test_delivery_repository_workspace.py \
  tests/test_delivery_repository_profiles.py \
  tests/test_delivery_repository_sandbox.py \
  tests/test_delivery_candidate_verifier.py \
  tests/test_delivery_agent_runner.py \
  tests/test_delivery_model_agents.py \
  tests/test_delivery_repository_security_boundary.py \
  tests/test_delivery_orchestration.py \
  tests/test_delivery_runtime.py -v
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run: `python -m ruff check src tests`

Expected: PASS using the project-pinned Ruff 0.15.x line.

- [ ] **Step 4: Run full pytest**

Run: `python -m pytest -q`

Expected: PASS with no failures.

- [ ] **Step 5: Review final diff**

Confirm there is no merge/push/deploy behavior, no production host-helper dependency in sandbox code, no model-provided command execution, no service restart/Docker-production authority, and no changes outside approved scope except test/tooling fixes required for green CI.

- [ ] **Step 6: Verify PR CI**

Use PR #1 or its successor draft PR for branch CI. Require `Install`, `Lint`, `Test`, and `Validate Compose` all green before reporting the milestone ready.

- [ ] **Step 7: Commit final guard changes**

Commit: `test: enforce isolated repository sandbox boundary`

- [ ] **Step 8: Do not deploy or merge**

Report the final head SHA, CI result, remaining limitations, and any genuine human approval required for merge/deployment separately.