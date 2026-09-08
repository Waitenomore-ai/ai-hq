# Controlled Code-Change Publishing Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish only the exact machine-verified AI HQ or DripVid candidate to a generated GitHub release branch, without giving the model arbitrary Git, remote, ref, credential, or shell authority.

**Architecture:** Extend candidate identity with the exact trusted base commit, then reopen a persisted sandbox workspace by opaque workspace id and re-verify its manifest before publication. A narrow GitHub publisher uses fixed repository targets and generated branch names, constructs blobs/tree/commit through the GitHub Git Data API, confirms the remote base commit still equals the candidate base commit, and records immutable publication metadata. Authentication remains a worker-only runtime concern and is not exposed to model prompts or persisted evidence.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, httpx, FastAPI worker runtime, GitHub Git Data API, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-07-chat-driven-code-changes-design.md`

## Global Constraints

- Registered repository keys remain exactly `ai-hq` and `dripvid`.
- The model never selects remote URLs, branch names, Git commands, credentials, base commits, or publication targets.
- Publication accepts only a QA-passed candidate with an explicit persisted human approval bound to the exact `change_ref`.
- A changed or missing sandbox workspace, mismatched content digest, mismatched base commit, unknown repository, stale remote base branch, or malformed candidate fails closed before remote mutation.
- Generated branches use a trusted fixed prefix and never force-update an existing ref.
- The publisher does not merge, deploy, restart services, or mutate production.
- No token, credential, environment dump, or secret content is persisted in candidate/publication evidence.

---

### Task 1: Bind candidate identity to the exact Git base commit

**Files:**
- Modify: `src/ai_hq/delivery/repository_workspace.py`
- Modify: `src/ai_hq/delivery/repository_sandbox.py`
- Modify: `src/ai_hq/delivery/candidate_verifier.py`
- Modify: `src/ai_hq/delivery/repository_profiles.py`
- Modify: `src/ai_hq/code_changes/runtime.py`
- Test: `tests/test_repository_sandbox.py`
- Test: `tests/test_candidate_verifier.py`
- Test: `tests/test_repository_profiles.py`

**Interfaces:**
- Produces: `RepositoryWorkspace.base_commit: str` and `CandidateSnapshot.base_commit: str` containing a 40-character lowercase Git commit SHA.
- Produces: candidate evidence key `base_commit` and includes it in the machine-derived `change_ref` identity payload.

- [ ] **Step 1: Write failing tests** asserting AI HQ and DripVid profiles use explicit `main`, sandbox resolves the configured base ref to an exact commit, malformed/non-commit refs fail closed, and candidate identity changes when `base_commit` changes.
- [ ] **Step 2: Run the focused tests** with `python -m pytest -q tests/test_repository_profiles.py tests/test_repository_sandbox.py tests/test_candidate_verifier.py` and confirm the new assertions fail for the missing base-commit identity.
- [ ] **Step 3: Implement the minimal identity extension**. Resolve the trusted profile base ref with fixed argv `git rev-parse --verify <base_ref>^{commit}` through the sandbox command boundary during `prepare`; validate the returned SHA; carry it through workspace/snapshot/verifier evidence. Set AI HQ runtime/profile default base ref to `main`.
- [ ] **Step 4: Run the focused tests** and require all to pass.
- [ ] **Step 5: Commit** with `feat: bind candidates to exact base commits`.

### Task 2: Reopen and verify a persisted candidate workspace after worker restart

**Files:**
- Create: `src/ai_hq/code_changes/candidate_store.py`
- Test: `tests/test_candidate_store.py`

**Interfaces:**
- Produces: `PersistedCandidate` frozen dataclass with `mission_id`, `repository`, `workspace_id`, `base_ref`, `base_commit`, `change_ref`, `changed_files`, `content_digest`, and trusted `workspace_path`.
- Produces: `CandidateStore.load_verified(...) -> PersistedCandidate` accepting only persisted machine evidence and recomputing the workspace manifest/content digest before returning.
- Produces: `CandidateStore.read_changed_file(candidate, path) -> bytes | None`, where `None` represents a verified deletion.

- [ ] **Step 1: Write failing tests** for valid reopen, UUID/path containment, symlink workspace rejection, repository/base/base-commit mismatch, stale content digest, changed-file mismatch, `.git` exclusion, regular-file-only reads, and deleted files.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_candidate_store.py` and confirm RED failures.
- [ ] **Step 3: Implement the store** using the same canonical manifest algorithm as the sandbox, resolving only `<trusted sandbox root>/<repository>/<workspace_id>`, never accepting a model/HTTP-supplied path.
- [ ] **Step 4: Run focused tests** and require all pass.
- [ ] **Step 5: Commit** with `feat: reopen verified code-change candidates`.

### Task 3: Add a narrow GitHub publication contract and fixed repository targets

**Files:**
- Create: `src/ai_hq/code_changes/publisher.py`
- Test: `tests/test_code_change_publisher.py`

**Interfaces:**
- Produces: `RepositoryPublishTarget(key: str, repository_full_name: str, base_branch: str, branch_prefix: str)`.
- Produces: `PublishedCandidate(repository, change_ref, branch_name, commit_sha, tree_sha, base_commit)`.
- Produces: `CandidatePublisher.publish(...) -> PublishedCandidate` protocol.
- Produces: deterministic `generated_branch_name(target, mission_id, change_ref) -> str` using only trusted target prefix plus normalized mission/change digest material.

- [ ] **Step 1: Write failing contract tests** for exactly two targets, generated-only branch names, unknown repository rejection, no arbitrary remote/ref arguments, and no force-update method in the protocol.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_code_change_publisher.py` and confirm RED.
- [ ] **Step 3: Implement the contract and registry** with fixed targets `Waitenomore-ai/ai-hq` and `Waitenomore-ai/dripvid`, base branch `main`, and a fixed `ai-hq/candidate/` branch namespace.
- [ ] **Step 4: Run focused tests** and require all pass.
- [ ] **Step 5: Commit** with `feat: define trusted code-change publisher`.

### Task 4: Implement exact-tree GitHub publication through the Git Data API

**Files:**
- Modify: `src/ai_hq/code_changes/publisher.py`
- Test: `tests/test_code_change_publisher.py`

**Interfaces:**
- Produces: `GitHubCandidatePublisher(http_client, token, candidate_store, targets)` implementing `CandidatePublisher`.

- [ ] **Step 1: Add failing tests** using `httpx.MockTransport` for the complete sequence: read `refs/heads/main`; require remote head equals candidate `base_commit`; read base commit/tree; create blobs only for verified changed regular files; preserve existing `100644`/`100755` modes; use `sha: null` for deletions; create a tree using the exact base tree; create one commit with the base commit as sole parent; create a new generated ref; return server commit/tree identities. Add failure tests for stale base, symlink/submodule entries, existing generated ref/conflict, non-2xx response, malformed GitHub payload, and token omission.
- [ ] **Step 2: Run focused tests** and confirm RED.
- [ ] **Step 3: Implement the GitHub API client** with fixed `https://api.github.com` endpoint construction from trusted repository targets, `Authorization: Bearer` held only in request headers, bounded timeouts, no response-body secret persistence, and no ref update/force operation.
- [ ] **Step 4: Run focused tests** and require all pass.
- [ ] **Step 5: Commit** with `feat: publish exact candidates to generated branches`.

### Task 5: Persist immutable publication metadata and make publication idempotent

**Files:**
- Modify: `src/ai_hq/delivery/models.py`
- Modify: `src/ai_hq/delivery/service.py`
- Create: `migrations/versions/0016_delivery_publication.py`
- Test: `tests/test_delivery_service.py`
- Test: `tests/test_migration_graph.py`

**Interfaces:**
- Adds nullable delivery fields `published_branch`, `published_commit`, `published_tree`, `published_at`.
- Produces: `DeliveryService.record_publication(mission_id, change_ref, branch_name, commit_sha, tree_sha) -> Delivery`.

- [ ] **Step 1: Write failing persistence tests** requiring exact `change_ref`, QA PASSED, WAITING_APPROVAL, matching persisted approval, and idempotent replay only when branch/commit/tree are identical. Mismatched second publication must fail closed.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_delivery_service.py tests/test_migration_graph.py` and confirm RED.
- [ ] **Step 3: Add migration/model/service implementation** without storing tokens or remote response bodies.
- [ ] **Step 4: Run focused tests** and require all pass with one Alembic head.
- [ ] **Step 5: Commit** with `feat: persist code-change publication identity`.

### Task 6: Gate publication on the exact human approval

**Files:**
- Modify: `src/ai_hq/code_changes/service.py`
- Test: `tests/test_code_change_service.py`
- Test: `tests/test_delivery_service.py`

**Interfaces:**
- Adds injected optional `publisher: CandidatePublisher | None`.
- Produces: `CodeChangeService.publish_approved_candidate(mission_id, approval_reference, change_ref) -> CodeChangeResult`.

- [ ] **Step 1: Write failing tests** proving pending/denied/expired/mismatched approval blocks the publisher; QA failure blocks; changed `change_ref` blocks; unknown repository blocks; approved exact candidate publishes once and records metadata; replay returns the same persisted publication without a second remote mutation.
- [ ] **Step 2: Run focused service tests** and confirm RED.
- [ ] **Step 3: Implement the orchestration** by first calling the existing exact-boundary `DeliveryService.apply_human_decision`, then invoking the trusted publisher only for APPROVED exact candidate, then persisting publication metadata. Keep `deployed=False`.
- [ ] **Step 4: Run focused tests** and require all pass.
- [ ] **Step 5: Commit** with `feat: publish only approved code-change candidates`.

### Task 7: Add worker-only runtime configuration, without placing publisher credentials in model context

**Files:**
- Modify: `src/ai_hq/config.py`
- Modify: `src/ai_hq/code_changes/runtime.py`
- Modify: `src/ai_hq/worker.py`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Test: `tests/test_config.py`
- Test: `tests/test_compose_security.py`
- Test: `tests/test_code_change_worker.py`

**Interfaces:**
- Adds non-secret setting `github_publish_token_file` defaulting to `None`.
- Worker may construct `GitHubCandidatePublisher` only when the configured token file exists and passes restrictive file checks; missing configuration leaves publication disabled/fail-closed.
- Web receives no token file mount and no token value.

- [ ] **Step 1: Write failing tests** proving only worker can see `/run/secrets/ai-hq-github-publisher-token`, web cannot, missing token file disables publication without breaking Phase A, token contents never appear in settings repr/chat/model evidence, and unsafe token-file permissions are rejected.
- [ ] **Step 2: Run focused tests** and confirm RED.
- [ ] **Step 3: Implement worker-only token-file loading** and publisher injection. Do not add the secret value to `.env`; `.env.example` documents only the token-file path/feature flag semantics.
- [ ] **Step 4: Run focused tests and Compose validation**.
- [ ] **Step 5: Commit** with `feat: configure worker-only candidate publishing`.

### Task 8: Full Phase B verification and review

**Files:**
- Review all files changed by Tasks 1-7.

- [ ] **Step 1: Run lint**: `python -m ruff check src tests`.
- [ ] **Step 2: Run full tests**: `python -m pytest -q`.
- [ ] **Step 3: Validate Compose** with the CI environment and `docker compose config`.
- [ ] **Step 4: Verify authority boundaries**: no model-facing command/remote/ref/token fields; no Docker socket; Host Helper and writable sandbox remain worker-only; web has only read-only repository mirrors.
- [ ] **Step 5: Review the final diff** against the approved Phase B spec and merge only after CI is fully green.
