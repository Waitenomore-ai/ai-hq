# DripVid MCP Unix-Socket Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect AI HQ to the DripVid MCP service over a fixed Unix-domain socket while preserving the existing read-only authority boundary.

**Architecture:** DripVid MCP keeps its localhost TCP listener and adds a second HTTP-over-Unix-socket listener at `/run/dripvid-mcp/mcp.sock`. AI HQ mounts that socket and a bearer-token file into the single calling container, uses `httpx` UDS transport, and enforces a second fixed tool/service allowlist before any MCP request is sent.

**Tech Stack:** Node.js, systemd, MCP HTTP transport, Python 3.12, `httpx`, FastAPI, Docker Compose, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-08-dripvid-mcp-unix-socket-design.md`

## Global Constraints

- DripVid MCP must remain bound to `127.0.0.1:8788` for TCP and must not bind to `0.0.0.0`.
- The Unix socket path is fixed at `/run/dripvid-mcp/mcp.sock` in production.
- No restart, deploy, shell, arbitrary command, arbitrary URL, filesystem-write, Docker-socket, or privileged-container authority may be added.
- AI HQ may initially call only `dripvid_health`, `dripvid_git_status`, `dripvid_config`, and `service_status` for `dripvid`, `jellyfin`, `cloudflared`, or `dripvid-requests`.
- The MCP bearer token must be loaded from a file, never committed, logged, placed in chat/model output, or persisted in mission records.
- All implementation follows TDD: RED test first, then minimal GREEN implementation, then full relevant CI.
- Production deployment remains a separate explicit action after exact merged SHAs are known.

---

### Task 1: Add the DripVid Unix-socket listener

**Files:**
- Modify: `mcp-server/src/server.js`
- Modify: `mcp-server/deploy/deploy-mcp-server.sh`
- Test: `mcp-server/test/safety.test.js`
- Test: `mcp-server/test/install-contract.test.js`

**Interfaces:**
- Consumes: existing MCP handler produced by `createMcpHandler(buildServer)` and existing localhost HTTP listener.
- Produces: a second HTTP server listening on `/run/dripvid-mcp/mcp.sock`, with the same `/mcp` bearer middleware and the same `/health` semantics.

- [ ] **Step 1: Write failing transport-contract tests**

Add tests that require the server/deployer contract to contain the fixed socket path `/run/dripvid-mcp/mcp.sock`, require stale-socket cleanup before listen, require both TCP and Unix listeners, and forbid `0.0.0.0`, `sudo`, or `service_restart` from being reintroduced.

- [ ] **Step 2: Run the DripVid MCP tests and verify RED**

Run: `cd mcp-server && npm test`

Expected: FAIL because no Unix-socket listener exists yet.

- [ ] **Step 3: Implement the minimal second listener**

Refactor `server.js` so a shared Express/MCP handler can back both the existing TCP HTTP server and a Unix-socket HTTP server. Before binding the socket, unlink only the exact fixed socket path if it already exists and is a socket; reject unexpected filesystem object types. Ensure shutdown closes both servers and removes the socket.

- [ ] **Step 4: Update systemd/runtime-directory provisioning**

Update `deploy-mcp-server.sh` so the service gets a runtime directory under `/run/dripvid-mcp`, owned for the MCP service, and the service starts with restrictive permissions. Preserve existing localhost diagnostics and existing read-only hardening.

- [ ] **Step 5: Run targeted and full DripVid checks**

Run: `cd mcp-server && npm test`
Run repository checks: `npm run check && npm test`

Expected: all pass.

- [ ] **Step 6: Commit DripVid changes**

Commit message: `feat: add read-only MCP unix socket transport`

---

### Task 2: Add AI HQ trusted MCP configuration and credential loading

**Files:**
- Modify: `src/ai_hq/config.py`
- Create: `src/ai_hq/dripvid_mcp/__init__.py`
- Create: `src/ai_hq/dripvid_mcp/runtime.py`
- Test: `tests/test_dripvid_mcp_config.py`
- Test: `tests/test_dripvid_mcp_runtime.py`

**Interfaces:**
- Produces: `Settings.dripvid_mcp_socket_path`, `Settings.dripvid_mcp_token_file_path`, bounded timeout settings, and `load_dripvid_mcp_token(path: Path) -> str`.

- [ ] **Step 1: Write failing configuration tests**

Require production to reject relative socket paths, relative token paths, network URLs in place of a socket path, and out-of-range timeouts. Require the default production socket path to be `/run/dripvid-mcp/mcp.sock`.

- [ ] **Step 2: Write failing credential-loader tests**

Require a regular non-symlink file, owner-only permissions where applicable, bounded size, non-empty content, and no whitespace. Tests must verify the token value is never included in raised exceptions.

- [ ] **Step 3: Run targeted tests and verify RED**

Run: `pytest tests/test_dripvid_mcp_config.py tests/test_dripvid_mcp_runtime.py -q`

Expected: FAIL because the settings and loader do not exist.

- [ ] **Step 4: Implement trusted settings and loader**

Add fixed-path settings and validators in `config.py`; implement the token loader in `dripvid_mcp/runtime.py` using the same fail-closed file discipline as the GitHub publisher token loader.

- [ ] **Step 5: Run targeted tests to GREEN**

Run: `pytest tests/test_dripvid_mcp_config.py tests/test_dripvid_mcp_runtime.py -q`

Expected: PASS.

- [ ] **Step 6: Commit AI HQ configuration changes**

Commit message: `feat: add trusted dripvid mcp runtime config`

---

### Task 3: Implement the constrained AI HQ MCP client

**Files:**
- Create: `src/ai_hq/dripvid_mcp/client.py`
- Test: `tests/test_dripvid_mcp_client.py`

**Interfaces:**
- Produces: `DripVidMcpClient` with explicit methods `dripvid_health()`, `dripvid_git_status()`, `dripvid_config()`, and `service_status(service: str)`.
- Internal transport: `httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=<fixed socket>), follow_redirects=False, timeout=<bounded>)`.

- [ ] **Step 1: Write failing allowlist and UDS tests**

Use `httpx.MockTransport`/transport injection to prove public client methods cannot accept arbitrary tool names, URLs, socket paths, or bearer values. Verify `service_status` rejects any service outside the four-name allowlist before transport is called.

- [ ] **Step 2: Write failing MCP protocol tests**

Cover initialize/session establishment, tool call request shape, bearer header presence, bounded response parsing, malformed JSON, unexpected result shape, redirect rejection, HTTP failures, and oversized response rejection.

- [ ] **Step 3: Run targeted tests and verify RED**

Run: `pytest tests/test_dripvid_mcp_client.py -q`

Expected: FAIL because the client does not exist.

- [ ] **Step 4: Implement minimal MCP client**

Implement only the four approved operation families. Keep raw MCP method names private constants, store any MCP session identifier only in memory, never expose transport controls to callers, and fail closed on malformed responses.

- [ ] **Step 5: Run targeted tests to GREEN**

Run: `pytest tests/test_dripvid_mcp_client.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the client**

Commit message: `feat: add constrained dripvid mcp client`

---

### Task 4: Mount the socket and credential into only the AI HQ caller

**Files:**
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `deploy/ai-hq-deploy`
- Modify: `deploy/check-production.sh`
- Test: `tests/test_compose_security.py`
- Test: `tests/test_deploy_contract.py`

**Interfaces:**
- Consumes: host `/run/dripvid-mcp/mcp.sock` and a root-managed MCP token file.
- Produces: read-only mounts and env path variables in only the selected AI HQ service that performs MCP reads.

- [ ] **Step 1: Write failing compose/security tests**

Require that only the intended AI HQ service receives the DripVid MCP socket/token mounts, require read-only mount flags, and continue to reject Docker socket or privileged mode.

- [ ] **Step 2: Write failing deploy-preflight tests**

Require production deploy to fail closed if the socket is missing, token source is missing/insecure, or configured paths differ from the fixed trusted paths.

- [ ] **Step 3: Run targeted tests and verify RED**

Run: `pytest tests/test_compose_security.py tests/test_deploy_contract.py -q`

Expected: FAIL on missing MCP mount/preflight contract.

- [ ] **Step 4: Implement mounts and preflight checks**

Add only the required UDS/token mounts and path env variables; do not add host networking, `network_mode: host`, privileged mode, or Docker socket access.

- [ ] **Step 5: Run targeted tests to GREEN**

Run: `pytest tests/test_compose_security.py tests/test_deploy_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit runtime wiring**

Commit message: `feat: mount read-only dripvid mcp transport`

---

### Task 5: Expose read-only DripVid MCP inspection through AI HQ

**Files:**
- Modify: `src/ai_hq/tool_gateway/registry.py`
- Modify: `src/ai_hq/tool_gateway/service.py`
- Modify: `src/ai_hq/chat/controller.py` or the existing narrow read-only routing surface selected after inspection
- Test: `tests/test_tool_gateway_registry.py`
- Test: `tests/test_tool_gateway.py`
- Test: `tests/test_chat_controller.py`

**Interfaces:**
- Consumes: explicit `DripVidMcpClient` methods only.
- Produces: authenticated read-only HQ operations for health, deployed release, redacted config, and allowlisted service state.

- [ ] **Step 1: Inspect the existing read-only Tool Gateway/chat pattern**

Read the complete registry/service/controller flow and choose the narrowest existing route that does not let model text name arbitrary MCP tools.

- [ ] **Step 2: Write failing gateway/chat tests**

Require fixed intent-to-method mapping, authenticated access, correct read-only result rendering, and rejection of model/user attempts to inject arbitrary MCP method names or transport parameters.

- [ ] **Step 3: Run targeted tests and verify RED**

Run: `pytest tests/test_tool_gateway_registry.py tests/test_tool_gateway.py tests/test_chat_controller.py -q`

Expected: FAIL because no DripVid MCP operations are registered.

- [ ] **Step 4: Implement minimal read-only wiring**

Wire only explicit high-level operations to the `DripVidMcpClient`; keep MCP method strings and transport configuration out of chat/model inputs.

- [ ] **Step 5: Run targeted tests to GREEN**

Run the same targeted pytest command and expect PASS.

- [ ] **Step 6: Commit the integration surface**

Commit message: `feat: expose read-only dripvid mcp inspection`

---

### Task 6: Verify both repositories and prepare exact releases

**Files:**
- No new functional files unless test failures reveal a spec-compliance bug.

**Interfaces:**
- Produces: exact immutable DripVid and AI HQ candidate SHAs with green CI.

- [ ] **Step 1: Run complete DripVid CI-equivalent checks**

Run all repository checks used by GitHub Actions, including MCP CI. Do not run `npm audit fix`.

- [ ] **Step 2: Run complete AI HQ CI-equivalent checks**

Run: `ruff check .`
Run: `pytest -q`
Run compose validation used by CI.

Expected: all pass.

- [ ] **Step 3: Review security diff**

Verify no `0.0.0.0` MCP bind, no Docker socket, no privileged mode, no service restart authority, no arbitrary tool execution, no secret value in tracked files, and no new production write capability.

- [ ] **Step 4: Open PRs and wait for exact-head CI**

Open one DripVid PR and one AI HQ PR. Merge only when their exact head SHAs are green.

- [ ] **Step 5: Record exact merged SHAs**

Use those immutable SHAs for production packaging/deployment. Do not deploy from mutable `main` without resolving the exact commit first.

---

### Task 7: Production rollout and end-to-end read-only verification

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: exact merged DripVid and AI HQ SHAs.
- Produces: live verified UDS MCP integration.

- [ ] **Step 1: Deploy the exact DripVid MCP commit**

Run the host installer from the exact merged checkout, verify localhost `/health`, verify `/run/dripvid-mcp/mcp.sock` exists as a socket, and verify no legacy sudoers file exists.

- [ ] **Step 2: Provision the AI HQ MCP bearer credential locally without displaying it**

Use a root-only local command/script to generate or copy the same bearer credential into the AI HQ trusted token file. Never paste the token into chat or command output.

- [ ] **Step 3: Deploy the exact AI HQ commit**

Use the existing immutable AI HQ deployment helper and run `deploy/check-production.sh`.

- [ ] **Step 4: Run end-to-end allowed calls**

From authenticated AI HQ, query DripVid health, deployed release, redacted configuration, and one allowlisted service status. Verify results come from MCP over the Unix socket.

- [ ] **Step 5: Run end-to-end negative checks**

Verify a non-allowlisted MCP tool and a non-allowlisted service are rejected before execution and that no network-facing MCP port was added.

- [ ] **Step 6: Record rollout result**

Record exact deployed SHAs and verification outcomes in the deployment/audit notes already used by the project.
