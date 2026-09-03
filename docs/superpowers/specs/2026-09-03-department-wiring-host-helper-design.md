# AI HQ Department Wiring: Commander + SysAdmin Host Helper

Date: 2026-09-03
Status: Approved design for implementation planning
Branch: `feature/department-wiring-host-helper`

## Goal

Wire the first two AI HQ departments—Commander and SysAdmin—into real operational capabilities without giving AI HQ unrestricted host access. Commander becomes the orchestrator for mission routing. SysAdmin gains a narrow, authenticated, read-only view of host and service health through a dedicated host-side helper.

This phase must preserve the existing Approval & Safety Engine, Operations Ledger, mission lifecycle, Safe Mode, Simulation Mode, and fail-closed behavior.

## Scope

This phase includes:

- Commander mission routing to SysAdmin.
- A host-side helper service with a small authenticated API over a Unix domain socket.
- Read-only SysAdmin capabilities for host health, resources, selected services, selected containers, and bounded recent logs.
- Safety Engine evaluation before helper invocation.
- Operations Ledger records for proposed actions, permission/risk decisions, execution results, and failures.
- Agent and mission state transitions reflected in the live HQ UI.
- Production deployment and smoke checks that do not modify DripVid.

This phase explicitly excludes:

- Arbitrary shell execution.
- Docker socket access from AI HQ.
- Host file-write endpoints.
- Restart, update, stop, delete, deploy, package-management, user-management, firewall, network, storage, or security mutations.
- Broad host filesystem access.
- Browser endpoints that allow arbitrary helper calls.
- Communications or Calendar tool wiring.

## Architecture

AI HQ remains the control plane and system of record. The host helper is a separate, narrowly privileged process on the server.

Data flow:

`Mission -> Commander routing -> proposed SysAdmin action -> permission/risk check -> Host Helper capability -> result -> Operations Ledger -> mission/agent state -> HQ room UI`

Responsibilities are separated as follows:

### Commander

Commander is an orchestrator, not a privileged executor. Commander may:

- Inspect mission and approved system state.
- Decide that SysAdmin is the correct department for supported operational work.
- Assign or create a SysAdmin-owned mission according to existing mission rules.
- Propose one of the named SysAdmin capabilities.
- Track the resulting mission state.

Commander must not:

- Bypass the Safety Engine.
- Invoke host capabilities directly without a permission/risk decision.
- Construct arbitrary shell commands.
- Gain broader host permissions than the SysAdmin capability being requested.

### SysAdmin

SysAdmin owns host-observability missions and invokes only declared helper capabilities after the Safety Engine allows them.

The initial capability set is:

- `host.health`
- `host.resources`
- `service.status`
- `container.status`
- `logs.recent`

All capabilities are read-only in this phase.

### Host Helper

The Host Helper runs outside the AI HQ containers and exposes a small authenticated API over a Unix domain socket. It is not a general-purpose remote shell.

The helper must:

- Accept only known capability names.
- Validate all parameters against strict schemas and allow-lists.
- Return structured JSON wherever possible.
- Apply hard timeouts.
- Apply response-size and log-line limits.
- Reject unknown services, containers, units, files, paths, flags, and command fragments.
- Listen only on a dedicated Unix domain socket under a controlled runtime path such as `/run/ai-hq-host-helper/helper.sock`.
- Authenticate every request using a separate service credential even though transport is local.
- Never return environment files, secrets files, credential material, or unrestricted process environments.

The helper must not expose:

- A TCP listener.
- An arbitrary command endpoint.
- A raw Docker API proxy.
- A generic file-read endpoint.
- A generic systemd action endpoint.
- A generic log-file path argument.

## Worker-Only Transport Boundary

Only the AI HQ worker receives the helper socket mount. The web container does not receive it.

The intended Compose boundary is conceptually:

- host helper creates `/run/ai-hq-host-helper/helper.sock`
- worker mounts only that socket/runtime directory at a fixed in-container path
- web has no helper socket mount
- neither web nor worker mounts `/var/run/docker.sock`
- neither web nor worker runs privileged

Socket filesystem ownership/mode must allow the dedicated AI HQ worker process to connect while denying unrelated local users where practical.

The helper credential remains required in addition to socket permissions so possession of the path alone is insufficient authorization.

## Capability Contracts

### `host.health`

Returns coarse host health information, such as:

- helper status/version
- host uptime
- load summary
- timestamp

No caller-controlled command or path arguments are accepted.

### `host.resources`

Returns bounded resource metrics, such as:

- CPU/load summary
- memory totals/usage
- root filesystem usage

The first version uses a fixed resource set. No arbitrary filesystem path may be supplied.

### `service.status`

Returns status for one service selected from an explicit allow-list.

Initial intended allow-list categories include:

- AI HQ
- Nginx
- DripVid

The implementation may map friendly service keys to host-specific unit names internally. Callers never provide raw systemd flags or shell fragments.

### `container.status`

Returns structured status for one container or compose service selected from an explicit allow-list.

The helper may use host Docker tooling internally, but AI HQ receives neither the Docker socket nor arbitrary Docker CLI argument control.

### `logs.recent`

Returns a bounded recent log window for one approved target from an explicit allow-list.

Requirements:

- Fixed maximum number of lines and bytes.
- No arbitrary file path.
- No arbitrary journal unit.
- No follow/stream mode in the first version.
- Secret-like values are filtered before durable storage.

## Permission and Risk Model

All helper calls must pass through the existing Approval & Safety Engine.

For this phase:

- Declared read-only capability + allowed target + valid parameters may be classified Green and run automatically in Safe Mode.
- Any unknown capability, unknown target, invalid parameter, missing permission state, helper error, or policy ambiguity fails closed.
- No mutation capability is introduced, even with approval.
- Simulation Mode remains first-class. A simulated action must not invoke the host helper and must produce a clearly simulated result in the ledger.
- Freeze Mode prevents new helper execution.

The existing audit chain remains authoritative:

`Mission -> Proposed Action -> Permission Check -> Risk Check -> Approval -> Tool Execution -> Result`

For Green read-only actions, the Approval step records that no human approval was required under current policy. For any action that is not Green in this phase, execution is denied rather than escalated into a new mutation path.

## Authentication and Secrets

The helper uses a dedicated credential separate from:

- the AI HQ administrator password
- the AI HQ web session secret
- DripVid credentials

The helper credential is stored in the AI HQ production secret/env layer and in the helper's root-readable configuration. It must never be written into mission payloads, ledger details, UI state, logs, or browser responses.

Requests use an authenticated service-to-service scheme over the Unix socket, with constant-time credential comparison and rejection of missing/invalid credentials.

The helper has no public Nginx route and no TCP listener.

## Allow-list Configuration

Service, container, and log targets are configured explicitly rather than discovered dynamically for callers.

The configuration model should separate friendly capability keys from host-specific implementation details. Example conceptual mapping:

- `ai-hq` -> approved AI HQ service/container targets
- `nginx` -> approved Nginx service/log target
- `dripvid` -> approved DripVid service/container/log target

Unknown keys are rejected.

Adding a new target is an administrative code/configuration change, not a browser action.

## Commander Routing Rules

Commander routing in this phase is deterministic and capability-based rather than LLM-dependent.

A mission is eligible for SysAdmin routing when it requests one of the supported host-observability intents. The first implementation uses explicit intent/capability mapping rather than free-form model interpretation.

Examples:

- "Check AI HQ health" -> SysAdmin -> `host.health` and/or approved AI HQ service status.
- "Check disk and memory" -> SysAdmin -> `host.resources`.
- "Is Nginx running?" -> SysAdmin -> `service.status` target `nginx`.
- "Show recent DripVid logs" -> SysAdmin -> `logs.recent` target `dripvid`.

Unsupported or ambiguous requests remain queued/failed with a clear reason instead of guessing a host command.

## Mission and Agent State

The live HQ must reflect durable state, not decorative animation.

Expected flow:

1. Mission queued.
2. Commander evaluates routing.
3. Commander briefly enters `WORKING` while routing.
4. Mission ownership is assigned to SysAdmin for supported work.
5. SysAdmin enters `WORKING` during safety evaluation/helper execution.
6. Result is recorded.
7. Mission moves to `COMPLETED` or `FAILED`.
8. Agent returns to `IDLE` after completion/failure handling.

If execution is blocked by policy, the mission must record the policy outcome and not imply that host work occurred.

The HQ room projection continues to derive from durable mission/agent records.

## Error Handling

The following all fail closed:

- helper unavailable
- socket missing or inaccessible
- authentication failure
- timeout
- malformed helper response
- unknown capability
- unknown target
- invalid parameters
- missing permission/risk decision
- Simulation/Freeze policy conflict
- response larger than configured bounds

Failures must produce:

- a deterministic mission outcome/state
- a ledger event with non-secret diagnostic context
- a user-visible room/mission status that does not claim work succeeded

The system must not automatically retry dangerous or ambiguous requests. Read-only transient failures may later gain bounded retry policy, but retries are not required for the first slice.

## Operations Ledger

Every attempted host capability must produce ledger evidence for:

- mission id
- requesting/owning agent
- capability name
- target key where applicable
- permission/risk outcome
- whether execution was simulated or real
- helper request outcome
- bounded result metadata
- failure category if any

Raw secrets and unbounded logs must never be persisted.

## API and UI Exposure

The browser remains a read-oriented operations console for this phase.

The existing HQ state endpoint may surface mission/agent status derived from the new execution flow.

No browser endpoint should permit:

- arbitrary helper invocation
- arbitrary capability names
- arbitrary target selection outside known mission workflows
- shell input
- mutation requests

A later phase may add explicit operator controls after a separate design and approval cycle.

## Deployment

The Host Helper is deployed separately from the AI HQ Docker Compose stack so AI HQ containers never require privileged Docker/host access.

Intended production characteristics:

- dedicated host-side service definition
- least-privilege runtime identity where practical
- Unix domain socket under `/run/ai-hq-host-helper/`
- worker-only socket/runtime-directory mount
- root-readable credential/configuration where required
- explicit allow-list configuration
- no TCP listener
- no public Nginx route
- local helper health check through the socket

AI HQ keeps its current isolated Compose stack and localhost web binding.

The deployment must preserve DripVid and ordinary Nginx operation.

## Testing Strategy

Implementation follows TDD.

Required automated coverage includes:

### Host Helper

- rejects missing authentication
- rejects invalid authentication
- accepts valid authentication
- rejects unknown capability
- rejects unknown target
- rejects malformed parameters
- enforces output/log bounds
- returns structured responses for each supported capability
- exposes no TCP listener contract
- exposes no generic command or path endpoint

### AI HQ Tool Boundary

- valid Green read-only action is allowed
- unknown capability fails closed
- Simulation Mode does not call the helper
- Freeze Mode blocks helper execution
- helper timeout/failure yields deterministic failure
- helper secrets are never included in persisted results
- web container has no helper socket
- worker helper client uses only the configured Unix socket

### Commander/SysAdmin

- supported mission routes deterministically to SysAdmin
- unsupported/ambiguous mission does not invent a command
- mission ownership/state transitions are durable
- Commander cannot bypass Safety Engine
- SysAdmin cannot invoke undeclared capabilities

### Ledger/UI

- proposed action, safety decision, execution and result are logged
- shared room semantics remain intact
- SysAdmin room shows real `WORKING` state during an active mission
- completed/failed flows return to truthful idle/failure-derived projection

### Deployment Contract

- helper has no public Nginx route
- helper has no TCP listener
- helper socket is mounted only into worker
- AI HQ Compose does not mount Docker socket
- AI HQ Compose does not grant privileged mode
- production smoke checks confirm AI HQ, helper local health, and DripVid root

## Production Acceptance Criteria

The phase is complete only when all of the following are true:

- Exact-head CI passes lint, full tests, and Compose validation.
- Host Helper is deployed with a Unix domain socket and separate credential.
- Only the AI HQ worker receives the helper socket mount.
- AI HQ can execute at least one real read-only SysAdmin capability through the full safety path.
- Operations Ledger records the action chain without secrets.
- HQ SysAdmin room reflects the mission activity truthfully.
- Unknown capability/target tests prove fail-closed behavior.
- No Docker socket is mounted into AI HQ.
- No arbitrary shell endpoint exists.
- No helper TCP listener exists.
- DripVid production smoke check passes unchanged.

## Future Work

Not part of this implementation:

- approval-gated service restart
- package updates
- deployment actions
- host file changes
- firewall/network changes
- backup/restore operations
- Security department wiring
- Communications/Gmail wiring
- Calendar wiring
- LLM-based free-form host command generation

Any mutation capability requires a separate design approval and must remain narrower than a general shell.
