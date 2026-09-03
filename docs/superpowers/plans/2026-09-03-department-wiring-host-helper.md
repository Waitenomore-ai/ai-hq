# Commander + SysAdmin Host Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Commander and SysAdmin into a real, read-only host-observability execution path through a worker-only Unix-domain-socket Host Helper while preserving AI HQ safety, audit, Simulation, Freeze, and fail-closed behavior.

**Architecture:** A new host-side helper exposes only five named read-only capabilities over `/run/ai-hq/host-helper.sock`. Only the AI HQ worker receives the socket mount and helper credential. Commander deterministically maps supported mission titles/intents to SysAdmin capabilities; SysAdmin sends every proposed action through the existing `SafetyService` before the worker invokes the helper client. Durable mission/agent state and Operations Ledger entries drive the HQ UI.

**Tech Stack:** Python 3.12, FastAPI/Starlette request models where useful, SQLAlchemy, existing AI HQ Safety/Approval/Ledger/Mission services, Unix domain sockets, JSON, systemd, Docker Compose, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-department-wiring-host-helper-design.md`

## Global Constraints

- No arbitrary shell execution.
- No Docker socket mounted into AI HQ.
- No host file-write endpoint.
- No restart/update/stop/delete/deploy/package/user/firewall/network/storage/security mutation capability in this phase.
- Host Helper transport is a Unix domain socket at `/run/ai-hq/host-helper.sock`, mounted read-only only into the worker container; the web container receives no helper socket.
- Host Helper credential is separate from the AI HQ administrator password, AI HQ session secret, and DripVid credentials.
- Simulation Mode must not invoke the helper.
- Freeze Mode must prevent new helper execution.
- Unknown capability/target/parameters, missing permission state, helper errors, malformed responses, or policy ambiguity fail closed.
- DripVid and existing Nginx routing must remain unchanged.

---

### Task 1: Host Helper capability contract and allow-lists

**Files:**
- Create: `src/ai_hq/host_helper/__init__.py`
- Create: `src/ai_hq/host_helper/contracts.py`
- Test: `tests/test_host_helper_contracts.py`

**Interfaces:**
- Produces: `HostCapability(StrEnum)`, `HelperRequest`, `HelperResponse`, `validate_request(payload: dict, allow_lists: HostAllowLists) -> HelperRequest`, and `HostAllowLists`.
- Later tasks consume these exact names for both server and client validation.

- [ ] **Step 1: Write the failing contract tests**

Create tests that assert the five capabilities are exactly:

```python
{
    "host.health",
    "host.resources",
    "service.status",
    "container.status",
    "logs.recent",
}
```

Also assert:

```python
validate_request({"capability": "shell.exec", "params": {}}, allow_lists)
```

raises `ValueError("unknown capability")`; `service.status`, `container.status`, and `logs.recent` reject targets outside the explicit allow-list; `host.health` and `host.resources` reject caller-supplied target/path/command fields; `logs.recent` accepts only integer `lines` from 1 through 200.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/test_host_helper_contracts.py -q`

Expected: import/module failure because `ai_hq.host_helper.contracts` does not exist.

- [ ] **Step 3: Implement the minimal immutable contract types**

Use dataclasses or Pydantic models with exact fields:

```python
class HostCapability(StrEnum):
    HOST_HEALTH = "host.health"
    HOST_RESOURCES = "host.resources"
    SERVICE_STATUS = "service.status"
    CONTAINER_STATUS = "container.status"
    LOGS_RECENT = "logs.recent"

@dataclass(frozen=True, slots=True)
class HostAllowLists:
    services: frozenset[str]
    containers: frozenset[str]
    logs: frozenset[str]

@dataclass(frozen=True, slots=True)
class HelperRequest:
    capability: HostCapability
    target: str | None
    params: dict[str, object]

@dataclass(frozen=True, slots=True)
class HelperResponse:
    ok: bool
    capability: HostCapability
    target: str | None
    data: dict[str, object]
    error: str | None = None
```

`validate_request()` must normalize nothing except the enum conversion; it must reject unknown keys in `params` rather than silently ignore them.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/test_host_helper_contracts.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: define host helper capability contracts`

---

### Task 2: Host Helper executor with bounded read-only system probes

**Files:**
- Create: `src/ai_hq/host_helper/executor.py`
- Test: `tests/test_host_helper_executor.py`

**Interfaces:**
- Consumes: `HelperRequest`, `HelperResponse`, `HostCapability`, `HostAllowLists`.
- Produces: `HostExecutor(allow_lists, command_runner=...)` and `HostExecutor.execute(request: HelperRequest) -> HelperResponse`.

- [ ] **Step 1: Write RED tests for every capability and every bound**

Use a fake `command_runner(argv: list[str], timeout: float) -> CompletedCommand` so tests never touch the real host. Assert exact command argument arrays are constructed internally from friendly keys, never from caller fragments.

Required mappings in test fixtures:

```python
service_units = {
    "ai-hq": "ai-hq-host-helper.service",
    "nginx": "nginx.service",
    "dripvid": "dripvid.service",
}
container_targets = {
    "ai-hq-web": "ai-hq-web-1",
    "ai-hq-worker": "ai-hq-worker-1",
    "dripvid": "dripvid",
}
log_targets = {
    "ai-hq": ("journal", "ai-hq-host-helper.service"),
    "nginx": ("journal", "nginx.service"),
    "dripvid": ("journal", "dripvid.service"),
}
```

Tests must prove:
- `host.health` has no caller-controlled command arguments.
- `host.resources` reports CPU/load, memory, and `/` filesystem only.
- `service.status` uses `systemctl show <fixed-unit> --no-page` with a fixed property set.
- `container.status` uses `docker inspect <fixed-name>` with no extra caller arguments.
- `logs.recent` uses `journalctl -u <fixed-unit> -n <bounded-lines> --no-pager -o short-iso`.
- `logs.recent` truncates the UTF-8 response to a fixed maximum byte count and returns truncation metadata.
- command timeout returns `ok=False` with category `timeout` rather than raising unbounded exceptions.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_host_helper_executor.py -q`

Expected: missing executor module/classes.

- [ ] **Step 3: Implement the minimal executor**

Define a small `CompletedCommand(returncode: int, stdout: str, stderr: str)` dataclass and a default runner using `subprocess.run(argv, shell=False, text=True, capture_output=True, timeout=3, check=False)`.

Hard limits:

```python
COMMAND_TIMEOUT_SECONDS = 3.0
MAX_LOG_LINES = 200
MAX_RESPONSE_BYTES = 64 * 1024
```

Never use `shell=True`. Parse systemctl/docker outputs into dictionaries before returning. Sanitize log text with a helper that replaces obvious secret assignments matching case-insensitive keys containing `password`, `secret`, `token`, `api_key`, or `authorization` with `[REDACTED]`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_host_helper_executor.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add bounded read only host executor`

---

### Task 3: Authenticated Unix-socket Host Helper server

**Files:**
- Create: `src/ai_hq/host_helper/server.py`
- Create: `deploy/ai-hq-host-helper.service`
- Test: `tests/test_host_helper_server.py`

**Interfaces:**
- Consumes: contract validation and `HostExecutor`.
- Produces: newline-delimited JSON request/response protocol over Unix socket and CLI entry `python -m ai_hq.host_helper.server`.

**Protocol:** one connection carries one request line and one response line.

Request JSON:

```json
{"credential":"<service-secret>","capability":"host.health","target":null,"params":{}}
```

Successful response JSON:

```json
{"ok":true,"capability":"host.health","target":null,"data":{...},"error":null}
```

- [ ] **Step 1: Write RED tests**

Using a temporary Unix socket, assert:
- missing credential -> response `ok=false`, `error="authentication failed"`.
- wrong credential -> same response without revealing which comparison failed.
- valid credential + valid capability -> executor invoked exactly once.
- invalid JSON -> bounded error response.
- request larger than 16 KiB -> connection rejected/error response.
- socket mode is `0660` after bind.
- server removes a stale socket path it owns before bind but refuses a non-socket path.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_host_helper_server.py -q`

Expected: missing server implementation.

- [ ] **Step 3: Implement server and constant-time auth**

Use `hmac.compare_digest`. Credential comes only from `AI_HQ_HOST_HELPER_CREDENTIAL`. Socket path comes from `AI_HQ_HOST_HELPER_SOCKET` default `/run/ai-hq/host-helper.sock`. Server reads at most `16 * 1024` bytes plus one byte to detect overflow, writes one JSON line, and closes.

The systemd unit must:
- run as a dedicated `ai-hq-helper` system user/group;
- create `/run/ai-hq` with group access suitable for the worker mount;
- load credential/config from `/etc/ai-hq/host-helper.env`;
- set `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectHome=true`, `ProtectSystem=strict`, and only the runtime directory writable;
- never open a TCP port.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_host_helper_server.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add authenticated unix socket host helper`

---

### Task 4: Worker-only Host Helper client and Compose isolation

**Files:**
- Create: `src/ai_hq/host_helper/client.py`
- Modify: `src/ai_hq/config.py`
- Modify: `compose.yaml`
- Test: `tests/test_host_helper_client.py`
- Test: `tests/test_compose_security.py`

**Interfaces:**
- Produces: `HostHelperClient(socket_path: str, credential: str, timeout_seconds: float = 4.0)` with `execute(request: HelperRequest) -> HelperResponse`.
- Adds Settings fields: `host_helper_socket: str = "/run/ai-hq/host-helper.sock"` and `host_helper_credential: str | None = None`.

- [ ] **Step 1: Write RED tests**

Client tests use a temporary Unix server and assert valid exchange, connect timeout/error normalization, malformed JSON rejection, response larger than 64 KiB rejection, capability/target echo mismatch rejection, and no credential value in exception strings.

Compose tests parse YAML and assert:

```python
assert "/run/ai-hq/host-helper.sock:/run/ai-hq/host-helper.sock" in worker_volumes
assert web_volumes does not contain "host-helper.sock"
assert no service mounts "/var/run/docker.sock"
assert no service has privileged == True
```

Also assert production settings require `host_helper_credential` before real helper execution is enabled; Simulation Mode may start without contacting helper.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_host_helper_client.py tests/test_compose_security.py -q`

Expected: missing client and missing Compose mount/settings.

- [ ] **Step 3: Implement client and worker-only mount**

Use `socket.socket(AF_UNIX, SOCK_STREAM)`; send one bounded JSON line and read at most `MAX_RESPONSE_BYTES + 1`. Convert all transport/protocol faults to a dedicated `HostHelperError` whose message contains only a non-secret failure category.

In Compose, add the Unix socket bind mount only under `worker`. Do not add it to `web`. Do not add Docker socket or privileged mode.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_host_helper_client.py tests/test_compose_security.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: connect worker to host helper socket`

---

### Task 5: Deterministic Commander routing

**Files:**
- Create: `src/ai_hq/departments/__init__.py`
- Create: `src/ai_hq/departments/commander.py`
- Test: `tests/test_commander_routing.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class RoutedAction:
    owner_agent: str
    capability: HostCapability
    target: str | None
    params: dict[str, object]
    risk: MissionRisk

class UnsupportedMission(ValueError): ...

def route_sysadmin_mission(title: str) -> RoutedAction
```

- [ ] **Step 1: Write RED routing tests**

Exact supported examples:

```python
"Check AI HQ health" -> host.health, target=None
"Check disk and memory" -> host.resources, target=None
"Is Nginx running?" -> service.status, target="nginx"
"Show recent DripVid logs" -> logs.recent, target="dripvid", params={"lines": 100}
"Check AI HQ web container" -> container.status, target="ai-hq-web"
```

All route to `owner_agent="sysadmin"` and `risk=MissionRisk.GREEN`.

Ambiguous/unsupported examples such as `"fix nginx"`, `"restart dripvid"`, `"run ls"`, `"delete logs"`, and unrelated free text must raise `UnsupportedMission` rather than select a capability.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_commander_routing.py -q`

Expected: missing commander module.

- [ ] **Step 3: Implement minimal deterministic matcher**

Use normalized casefolded strings/explicit regex patterns only. No LLM call and no generic command construction. Keep mutation verbs on a deny list before any read-only matching.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_commander_routing.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add deterministic Commander SysAdmin routing`

---

### Task 6: Safety-gated SysAdmin execution service and ledger result records

**Files:**
- Create: `src/ai_hq/departments/sysadmin.py`
- Modify: `src/ai_hq/ledger/models.py` only if a result/failure event type is missing; otherwise reuse existing result event type.
- Test: `tests/test_sysadmin_execution.py`

**Interfaces:**
- Consumes: `SafetyService.evaluate`, `HostHelperClient.execute`, `RoutedAction`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class SysAdminExecutionResult:
    status: MissionStatus
    simulated: bool
    data: dict[str, object]
    error: str | None

class SysAdminService:
    def execute(self, *, mission_id: str, action: RoutedAction) -> SysAdminExecutionResult: ...
```

- [ ] **Step 1: Write RED tests for the complete safety boundary**

Assert:
- Green read-only real-mode action calls `SafetyService.evaluate(..., mutates_external_state=False)` before helper.
- `Decision.ALLOW` invokes helper exactly once.
- Simulation decision/result does not invoke helper and records `simulated=True`.
- Freeze/deny decision does not invoke helper.
- unknown capability cannot reach this service because `RoutedAction` uses enum; forged invalid target is revalidated and denied.
- helper timeout/failure returns deterministic mission failure and a bounded ledger failure entry.
- persisted metadata never contains the helper credential.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_sysadmin_execution.py -q`

Expected: missing service.

- [ ] **Step 3: Implement safety-first execution**

Construct the safety action as the capability value, target as `target or "host"`, `risk=GREEN`, `conditions={"read_only": True}`, `mutates_external_state=False`. Read current `SystemState.simulation_mode` only through the existing safety result path; do not independently bypass it. Record execution/result ledger metadata containing capability, friendly target, simulated flag, `ok`, and bounded non-secret result summary only.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_sysadmin_execution.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: safety gate SysAdmin host observations`

---

### Task 7: Mission consumption and truthful Commander/SysAdmin agent state

**Files:**
- Create: `src/ai_hq/departments/runner.py`
- Modify: `src/ai_hq/worker.py`
- Modify: `src/ai_hq/missions/service.py` only through existing public methods where possible; add narrow transition helpers if absent.
- Modify: `src/ai_hq/agents/service.py` only through existing public methods where possible; add narrow status/current-mission helpers if absent.
- Test: `tests/test_department_runner.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `DepartmentRunner.run_once() -> bool`, returning `True` when one eligible mission was processed and `False` when none was available.

- [ ] **Step 1: Write RED end-to-end service tests**

Using SQLite and a fake helper client, create a queued mission titled `"Is Nginx running?"` and assert the durable sequence:

```text
mission QUEUED
commander WORKING/current_mission
route -> owner sysadmin
commander IDLE
mission RUNNING
sysadmin WORKING/current_mission
safety -> helper
mission COMPLETED
sysadmin IDLE/current_mission=None
```

For unsupported `"restart nginx"`, assert no helper call and deterministic failure reason. For helper failure, assert mission `FAILED`, SysAdmin does not remain `WORKING`, and HQ projection cannot claim active work after cleanup.

Worker test must prove the resident loop repeatedly calls `runner.run_once()` while not frozen and sleeps only when no mission is processed.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_department_runner.py tests/test_worker.py -q`

Expected: missing runner / worker does not consume missions.

- [ ] **Step 3: Implement one-mission-at-a-time runner**

Use the oldest eligible `QUEUED` mission with row/state recheck before transition. Do not create parallel execution in this phase. Always restore agent state in `finally` blocks. Unsupported missions fail without helper execution. The worker constructs the runner once and remains resident; Freeze must prevent `run_once()` from executing new work.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_department_runner.py tests/test_worker.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: run Commander SysAdmin missions in worker`

---

### Task 8: HQ live-state regression coverage

**Files:**
- Modify: `tests/test_hq_state.py`
- Modify: `tests/test_hq_api.py` only if additional payload fields are required; prefer no API shape change.

**Interfaces:**
- Consumes existing HQ projection; no new browser execution endpoints.

- [ ] **Step 1: Add RED/behavior tests around real department state**

Assert a durable SysAdmin `WORKING` mission projects `WORKING` with mission title, and after `COMPLETED`/agent reset it projects `IDLE`. Assert Commander routing work projects only from durable Commander agent state. Assert no helper credential/capability raw request body is exposed by `/api/hq/state`.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/test_hq_state.py tests/test_hq_api.py -q`

If existing projection already satisfies the contract, record that this task needs tests only; do not change production code merely to force a RED state.

- [ ] **Step 3: Make only necessary projection changes**

If needed, adapt `src/ai_hq/hq/state.py` to use existing mission/agent fields without adding decorative activity states.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_hq_state.py tests/test_hq_api.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `test: lock live Commander SysAdmin HQ state`

---

### Task 9: Production deployment tooling for Host Helper

**Files:**
- Create: `deploy/install-host-helper.sh`
- Modify: `deploy/check-production.sh`
- Modify: `deploy/ai-hq-deploy` only if the worker socket mount requires an explicit preflight; do not weaken rollback behavior.
- Test: `tests/test_host_helper_deploy_contract.py`

**Interfaces:**
- Installer creates/updates the dedicated system user, `/etc/ai-hq/host-helper.env`, `/run/ai-hq` runtime ownership via systemd, installs unit file, daemon-reloads and starts the helper.
- Production check verifies socket type/permissions, helper local health request, worker socket mount, no web socket mount, no Docker socket, and DripVid root.

- [ ] **Step 1: Write RED deployment-contract tests**

Read scripts/unit as text and assert:
- installer never prints credential contents;
- systemd unit contains no TCP listener;
- Compose worker mounts host-helper socket but web does not;
- smoke script checks `test -S /run/ai-hq/host-helper.sock`;
- smoke script checks DripVid root exactly as before;
- no Docker socket or `privileged: true` appears.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_host_helper_deploy_contract.py -q`

Expected: missing installer/smoke checks.

- [ ] **Step 3: Implement safe installer and smoke checks**

Installer must accept credential via interactive hidden input or pre-existing root-readable env file; it must not accept plaintext credential as a command-line argument. It writes `/etc/ai-hq/host-helper.env` mode `0600`, installs code from the active release, enables/restarts `ai-hq-host-helper.service`, and verifies the Unix socket exists.

Add a helper health request to production smoke using a small Python snippet that reads the credential from root-readable env without echoing it and communicates over the Unix socket.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_host_helper_deploy_contract.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add host helper production deployment`

---

### Task 10: Full verification, branch review, merge, and controlled production acceptance

**Files:**
- No new feature files unless verification exposes a defect.

- [ ] **Step 1: Run full local/CI-equivalent verification**

Run:

```bash
python -m ruff check src tests
pytest -q
docker compose --env-file .env.example config >/dev/null
```

Expected: zero failures/errors.

- [ ] **Step 2: Push exact head and require GitHub Actions GREEN**

Verify Install, Lint, Test, and Validate Compose all succeed on the exact branch SHA.

- [ ] **Step 3: Compare against `main`**

Require `behind_by == 0`. Review the file list and confirm all changes are limited to the approved Host Helper / Commander / SysAdmin / deployment scope.

- [ ] **Step 4: Fast-forward `main` only after exact-head GREEN**

Move `main` to the verified branch SHA and require a fresh `main` CI success at the same SHA.

- [ ] **Step 5: Controlled server deployment**

On the live server:
1. keep existing AI HQ env/secrets intact;
2. install Host Helper with a newly generated separate credential entered by the operator;
3. verify helper socket locally;
4. deploy exact green AI HQ SHA through `ai-hq-deploy` rollback gate;
5. run `deploy/check-production.sh`;
6. create one real read-only mission such as `"Is Nginx running?"` through the existing authenticated mission API/workflow;
7. verify Operations Ledger chain and HQ SysAdmin room transition;
8. verify DripVid root remains healthy.

Production acceptance fails if any helper credential appears in output/logs, if the web container receives the socket, if any Docker socket is mounted, or if a mutation capability becomes reachable.
