# Tool Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the single fail-closed execution boundary that every future Gmail, Calendar, Home Assistant and SysAdmin tool adapter must pass through.

**Architecture:** `ToolGateway` accepts a typed request, checks the requesting agent's exact permission, asks `SafetyService` for the policy decision, and only then resolves an exact registered adapter. Blocked/approval/simulated actions never invoke an adapter. Allowed executions record `tool.executed` and `result.recorded` events without storing request payloads or credentials.

**Tech Stack:** Python 3.12, SQLAlchemy 2, existing `SafetyService`, `OperationsLedger`, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-ai-hq-phase-1-design.md`

## Global Constraints

- Exact capability permissions only; no wildcard permission matching.
- Missing agent, permission, safety state or adapter fails closed.
- No arbitrary shell, Docker socket or generic command-string adapter.
- Mutating actions never execute when `SafetyService` returns `BLOCK`, `REQUIRE_APPROVAL` or `SIMULATE_ONLY`.
- Simulation records a result but performs no external action.
- Adapter request parameters and secrets are not copied into the Operations Ledger.
- No browser execution API is introduced in this phase.

---

### Task 1: Gateway contracts and exact adapter registry

**Files:**
- Create: `src/ai_hq/tool_gateway/__init__.py`
- Create: `src/ai_hq/tool_gateway/contracts.py`
- Create: `src/ai_hq/tool_gateway/registry.py`
- Test: `tests/test_tool_gateway_registry.py`

**Interfaces:**
- Produces `ToolRequest`, `ToolOutcome`, `ToolOutcomeState`, `ToolAdapter`, `ToolRegistry`.
- `ToolRegistry.resolve(capability: str) -> ToolAdapter | None` uses exact string matching.

- [ ] **Step 1: Write the failing registry tests**

```python
def test_registry_resolves_only_exact_capability():
    registry = ToolRegistry([FakeAdapter("host.health")])
    assert registry.resolve("host.health") is not None
    assert registry.resolve("host.*") is None
    assert registry.resolve("host.health.extra") is None


def test_duplicate_capability_registration_is_rejected():
    with pytest.raises(ValueError, match="duplicate capability"):
        ToolRegistry([FakeAdapter("host.health"), FakeAdapter("host.health")])
```

- [ ] **Step 2: Run `pytest tests/test_tool_gateway_registry.py -q` and verify RED due to missing package.**
- [ ] **Step 3: Implement immutable request/outcome types and exact-match registry.**

```python
class ToolOutcomeState(StrEnum):
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    SIMULATED = "simulated"
    EXECUTED = "executed"
    FAILED = "failed"

class ToolAdapter(Protocol):
    capability: str
    def execute(self, request: ToolRequest) -> dict[str, object]: ...
```

- [ ] **Step 4: Run registry tests and full Ruff check; require GREEN.**
- [ ] **Step 5: Commit the registry slice.**

### Task 2: Permission and SafetyService execution gate

**Files:**
- Create: `src/ai_hq/tool_gateway/service.py`
- Test: `tests/test_tool_gateway.py`

**Interfaces:**
- Consumes `Agent.permissions`, `SafetyService.evaluate`, `ToolRegistry.resolve`.
- Produces `ToolGateway.execute(request: ToolRequest) -> ToolOutcome`.

- [ ] **Step 1: Write failing tests proving no permission means no adapter invocation, Green read-only allowed, Amber waits for approval, Red blocks, and missing adapter fails closed.**

```python
def test_missing_permission_fails_closed_without_invoking_adapter(gateway, adapter):
    outcome = gateway.execute(request(capability="host.health", risk=MissionRisk.GREEN))
    assert outcome.state is ToolOutcomeState.BLOCKED
    assert adapter.calls == 0


def test_green_read_only_action_executes_when_exact_permission_exists(gateway, adapter):
    grant_permission("sysadmin", "host.health")
    outcome = gateway.execute(request(capability="host.health", risk=MissionRisk.GREEN))
    assert outcome.state is ToolOutcomeState.EXECUTED
    assert adapter.calls == 1
```

- [ ] **Step 2: Run the focused tests and verify RED for missing `ToolGateway`.**
- [ ] **Step 3: Implement the minimum service:** load the agent, require exact permission, resolve safety with `authorization_available`, map safety decisions to outcomes, and invoke the adapter only for `ALLOW`.
- [ ] **Step 4: Run focused + full tests and require GREEN.**
- [ ] **Step 5: Commit the execution-gate slice.**

### Task 3: Simulation and audit-chain integration

**Files:**
- Modify: `src/ai_hq/tool_gateway/service.py`
- Test: `tests/test_tool_gateway.py`

**Interfaces:**
- Consumes existing `OperationsLedger` event types.
- Produces `TOOL_EXECUTED` and `RESULT_RECORDED` entries only after a permitted execution/simulation path.

- [ ] **Step 1: Add failing tests that a Normal+Simulation mutating action with valid approval returns `SIMULATED`, does not call the adapter, and records a result; an allowed read-only action records tool/result events; adapter exceptions return `FAILED` and record only non-secret failure metadata.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement decision mapping and audit writes. Never persist `request.params`.**

```python
if safety.decision is Decision.SIMULATE_ONLY:
    self.ledger.record(..., event_type=LedgerEventType.RESULT_RECORDED,
                       metadata={"capability": request.capability, "state": "simulated"})
    return ToolOutcome(state=ToolOutcomeState.SIMULATED, ...)
```

- [ ] **Step 4: Run focused + full tests and require GREEN.**
- [ ] **Step 5: Commit the simulation/audit slice.**

### Task 4: Host-helper read-only adapter boundary

**Files:**
- Create: `src/ai_hq/tool_gateway/host_adapter.py`
- Test: `tests/test_tool_gateway_host_adapter.py`

**Interfaces:**
- Consumes existing `HostCapability`, `HelperRequest` and a callable host-helper client.
- Produces adapters only for the five existing read-only host capabilities.

- [ ] **Step 1: Add failing tests proving only `host.health`, `host.resources`, `service.status`, `container.status`, and `logs.recent` can be constructed, and no arbitrary command capability exists.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement a narrow adapter translating typed gateway requests into existing `HelperRequest`; reject unknown fields/targets through existing host-helper validation.**
- [ ] **Step 4: Run focused + full tests and require GREEN.**
- [ ] **Step 5: Commit the host adapter slice.**

### Task 5: Exact-head verification and integration

**Files:** no new production behavior.

- [ ] **Step 1:** Run Ruff on `src tests`.
- [ ] **Step 2:** Run full pytest suite.
- [ ] **Step 3:** Validate Docker Compose.
- [ ] **Step 4:** Compare `feature/tool-gateway` to `main`; require ahead-only, zero behind, and no DripVid runtime/config changes.
- [ ] **Step 5:** Fast-forward `main` to the exact CI-green feature SHA under the user's standing merge-to-main choice.
- [ ] **Step 6:** Verify feature and `main` are identical.
