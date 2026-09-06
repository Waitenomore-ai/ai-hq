# Recovery Host Readiness Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route DripVid production readiness observation through AI HQ Host Helper so the host probes the fixed loopback endpoint and the worker receives only bounded read-only readiness data.

**Architecture:** Add a read-only `dripvid.readiness` Host Helper capability with no caller-supplied URL or parameters. The Host Helper probes `http://127.0.0.1:3000/health/ready`, sanitizes the payload, and returns it over the existing authenticated Unix socket; production recovery worker wiring consumes that result through a probe adapter with the existing `probe() -> dict` interface.

**Tech Stack:** Python 3.12, pytest, httpx, AI HQ Host Helper Unix-socket client/server, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-06-recovery-host-readiness-probe-design.md`

## Global Constraints

- DripVid remains bound to host loopback; do not expose port 3000 to `0.0.0.0` or Docker bridge interfaces.
- The new Host Helper capability is read-only and accepts no arbitrary URL, host, path, header, shell command, service name, or model-provided parameter.
- Fixed host endpoint: `http://127.0.0.1:3000/health/ready`.
- Probe timeout: 3 seconds maximum.
- Response body limit: 64 KiB.
- Return only the bounded readiness fields defined in the spec.
- Existing service recovery, approval, scoped-rule, simulation, and exact-agent authorization gates remain unchanged.
- Developer and QA gain no production execution authority.
- Production recovery remains observe-only during rollout.

---

### Task 1: Define the read-only Host Helper readiness contract

**Files:**
- Modify: `src/ai_hq/host_helper/contracts.py`
- Test: `tests/test_host_helper_contracts.py`
- Test: `tests/test_host_helper_recovery.py`

**Interfaces:**
- Produces: `HostCapability.DRIPVID_READINESS = "dripvid.readiness"`.
- Produces: validated request shape `HelperRequest(capability=HostCapability.DRIPVID_READINESS, target=None, params={})`.

- [ ] **Step 1: Write failing contract tests**

Add tests equivalent to:

```python
def test_dripvid_readiness_accepts_no_target_or_params(allow_lists):
    request = validate_request(
        {"capability": "dripvid.readiness", "target": None, "params": {}},
        allow_lists,
    )
    assert request.capability is HostCapability.DRIPVID_READINESS
    assert request.target is None
    assert request.params == {}


def test_dripvid_readiness_rejects_arbitrary_input(allow_lists):
    for payload in (
        {"capability": "dripvid.readiness", "target": "dripvid", "params": {}},
        {"capability": "dripvid.readiness", "target": None, "params": {"url": "http://example.com"}},
    ):
        with pytest.raises(ValueError):
            validate_request(payload, allow_lists)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_host_helper_contracts.py tests/test_host_helper_recovery.py -q
```

Expected: failures because `dripvid.readiness` is not a known capability.

- [ ] **Step 3: Implement minimal contract support**

In `HostCapability`, add:

```python
DRIPVID_READINESS = "dripvid.readiness"
```

In `validate_request`, handle `DRIPVID_READINESS` alongside host read-only capabilities, requiring `target is None` and empty params:

```python
if capability in {
    HostCapability.HOST_HEALTH,
    HostCapability.HOST_RESOURCES,
    HostCapability.DRIPVID_READINESS,
}:
    if target is not None:
        raise ValueError("target not allowed")
    if params:
        raise ValueError("unknown parameter")
    return HelperRequest(capability=capability, target=None, params={})
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest tests/test_host_helper_contracts.py tests/test_host_helper_recovery.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/host_helper/contracts.py tests/test_host_helper_contracts.py tests/test_host_helper_recovery.py
git commit -m "feat: define read-only DripVid readiness capability"
```

---

### Task 2: Execute the fixed host-loopback readiness probe

**Files:**
- Modify: `src/ai_hq/host_helper/executor.py`
- Test: `tests/test_host_helper_executor.py`
- Test: `tests/test_host_helper_recovery.py`

**Interfaces:**
- Consumes: `HostCapability.DRIPVID_READINESS` from Task 1.
- Produces: executor response data with bounded keys `reachable`, `status_code`, `ok`, dependency booleans, bounded `storage`, and `error`.

- [ ] **Step 1: Write failing executor tests**

Use an injectable read-only HTTP probe function rather than shelling out to `curl`. Add tests for:

```python
def test_executor_returns_bounded_dripvid_readiness(...):
    # Probe fixture returns extra secret/path fields.
    # Assert only approved readiness fields survive.


def test_executor_readiness_timeout_fails_closed(...):
    # Simulate timeout.
    # Assert ok response envelope with bounded unhealthy readiness data.


def test_executor_readiness_rejects_oversized_or_invalid_json(...):
    # Assert error values are bounded and raw body is absent.
```

Expected healthy data shape:

```python
{
    "reachable": True,
    "status_code": 200,
    "ok": True,
    "database": True,
    "jellyfin": True,
    "radarr": True,
    "sonarr": True,
    "qbittorrent": True,
    "requestSync": True,
    "storage": {
        "available": True,
        "writable": True,
        "belowReserve": False,
        "freeBytes": 959790956544,
        "reserveBytes": 53687091200,
    },
    "error": None,
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest tests/test_host_helper_executor.py tests/test_host_helper_recovery.py -q
```

Expected: failures because executor has no readiness implementation.

- [ ] **Step 3: Add a focused host readiness helper**

Keep the fixed endpoint in Host Helper code:

```python
DRIPVID_READINESS_URL = "http://127.0.0.1:3000/health/ready"
DRIPVID_READINESS_TIMEOUT_SECONDS = 3.0
MAX_RESPONSE_BYTES = 64 * 1024
```

Create an injectable callable with a signature equivalent to:

```python
ReadinessRunner = Callable[[str, float, int], dict[str, object]]
```

The default implementation should use `httpx` from the host-helper process, enforce timeout/body bounds, parse only JSON objects, and normalize to the approved schema. It must never accept the URL from `HelperRequest`.

- [ ] **Step 4: Wire the executor capability**

In `HostExecutor.execute`:

```python
if capability is HostCapability.DRIPVID_READINESS:
    return self._dripvid_readiness(request)
```

Implement `_dripvid_readiness` to call only the fixed endpoint and return:

```python
HelperResponse(
    True,
    request.capability,
    None,
    bounded_readiness,
)
```

For transport/parsing failures, return a bounded unhealthy readiness dictionary rather than raw exceptions or response bodies.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
pytest tests/test_host_helper_executor.py tests/test_host_helper_recovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_hq/host_helper/executor.py tests/test_host_helper_executor.py tests/test_host_helper_recovery.py
git commit -m "feat: probe DripVid readiness on the host"
```

---

### Task 3: Expose the readiness call through HostHelperClient

**Files:**
- Modify: `src/ai_hq/host_helper/client.py`
- Test: `tests/test_host_helper_client.py`

**Interfaces:**
- Produces: `HostHelperClient.dripvid_readiness() -> HelperResponse` or the repository's existing equivalent typed request method.
- No URL argument is permitted.

- [ ] **Step 1: Write a failing client test**

Assert that the client sends exactly:

```python
{
    "capability": "dripvid.readiness",
    "target": None,
    "params": {},
}
```

and accepts the bounded response.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest tests/test_host_helper_client.py -q
```

Expected: failure because the client helper method does not exist.

- [ ] **Step 3: Implement the client method**

Follow the existing request transport pattern and add no new transport mechanism. The method must take no URL or target argument.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
pytest tests/test_host_helper_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/host_helper/client.py tests/test_host_helper_client.py
git commit -m "feat: add Host Helper readiness client call"
```

---

### Task 4: Add a Host Helper-backed recovery probe adapter

**Files:**
- Modify: `src/ai_hq/recovery/probe.py`
- Test: `tests/test_recovery_probe.py`

**Interfaces:**
- Consumes: Host Helper client readiness call from Task 3.
- Produces: `HostHelperDripVidReadinessProbe.probe() -> dict` with the same recovery-facing schema as `DripVidReadinessProbe.probe()`.

- [ ] **Step 1: Write failing adapter tests**

Add tests equivalent to:

```python
def test_host_helper_probe_returns_bounded_data():
    client = FakeHostHelperClient(...)
    probe = HostHelperDripVidReadinessProbe(client)
    assert probe.probe()["ok"] is True


def test_host_helper_probe_fails_closed_when_helper_unavailable():
    client = FakeHostHelperClient(error=OSError("socket unavailable"))
    probe = HostHelperDripVidReadinessProbe(client)
    assert probe.probe() == {
        "reachable": False,
        "status_code": None,
        "ok": False,
        "error": "host_helper_unavailable",
    }
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest tests/test_recovery_probe.py -q
```

Expected: failure because the adapter is absent.

- [ ] **Step 3: Implement the adapter**

Add a small class that delegates to the Host Helper client, copies only the approved bounded fields, and maps Host Helper transport failure to a bounded unhealthy result. Do not import `subprocess`, `os`, `shlex`, Docker, systemd, or deployment code into the recovery module.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest tests/test_recovery_probe.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/recovery/probe.py tests/test_recovery_probe.py
git commit -m "feat: use Host Helper for recovery readiness"
```

---

### Task 5: Switch production recovery worker wiring to Host Helper

**Files:**
- Modify: `src/ai_hq/recovery/bootstrap.py`
- Modify: `src/ai_hq/worker.py`
- Test: `tests/test_recovery_worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `HostHelperDripVidReadinessProbe` from Task 4 and the existing configured Host Helper Unix socket/credential.
- Produces: production recovery coordinator whose readiness probe is Host Helper-backed when recovery is enabled.

- [ ] **Step 1: Write failing worker-wiring tests**

Assert that enabling recovery constructs the Host Helper-backed probe and does not construct/directly invoke the container-local HTTP probe for production observation.

Also assert recovery-disabled startup remains backward compatible.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest tests/test_recovery_worker.py tests/test_worker.py -q
```

Expected: failure because worker wiring still uses `DripVidReadinessProbe` directly.

- [ ] **Step 3: Update bootstrap/wiring**

Reuse the existing `HostHelperClient` configured with:

- `settings.host_helper_socket`
- `settings.host_helper_credential`

When recovery is enabled, inject `HostHelperDripVidReadinessProbe` into the recovery coordinator. Do not broaden web-container access to the Host Helper socket; preserve worker-only mounting.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest tests/test_recovery_worker.py tests/test_worker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_hq/recovery/bootstrap.py src/ai_hq/worker.py tests/test_recovery_worker.py tests/test_worker.py
git commit -m "fix: route production recovery probe through Host Helper"
```

---

### Task 6: Lock the security boundary and deployment contract

**Files:**
- Modify: `tests/test_recovery_security_boundary.py`
- Modify: `tests/test_host_helper_recovery.py`
- Modify: `tests/test_compose_security.py` if necessary only to assert existing worker-only socket isolation
- Modify: `deploy/check-production.sh` only if a non-mutating readiness capability smoke check fits the existing authenticated Host Helper check pattern

**Interfaces:**
- Produces: regression coverage proving no new arbitrary network or mutation authority exists.

- [ ] **Step 1: Add security regressions**

Assert:

```python
assert "DRIPVID_READINESS_URL" is fixed to "http://127.0.0.1:3000/health/ready"
```

and that:

- recovery modules do not import `subprocess`, `os`, or `shlex`;
- recovery modules do not call restart/recover/deploy/rollback directly;
- Host Helper readiness validation rejects caller-provided URL/target/params;
- Compose still mounts `/run/ai-hq/host-helper.sock` only into the worker;
- no `0.0.0.0:3000` exposure is introduced by AI HQ.

- [ ] **Step 2: Run security-focused tests**

Run:

```bash
pytest tests/test_recovery_security_boundary.py tests/test_host_helper_recovery.py tests/test_compose_security.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recovery_security_boundary.py tests/test_host_helper_recovery.py tests/test_compose_security.py deploy/check-production.sh
git commit -m "test: lock host readiness probe security boundary"
```

---

### Task 7: Full verification

**Files:**
- No production code changes unless verification reveals a specific regression.

**Interfaces:**
- Produces: fresh evidence that the branch is safe to integrate.

- [ ] **Step 1: Run lint**

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 2: Run full pytest suite**

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Validate Compose**

Use the repository's existing CI-equivalent command, normally:

```bash
docker compose config >/dev/null
```

with the same environment fixture used by CI if required.

Expected: PASS.

- [ ] **Step 4: Review the diff for authority expansion**

Confirm the diff contains no arbitrary URL input, no host networking exposure, no new production socket mount to web, and no relaxation of recovery mutation gates.

- [ ] **Step 5: Push branch and wait for CI**

Push `feature/recovery-host-readiness-probe` and require the repository CI workflow to pass on the exact branch head before integration.

---

### Task 8: Production rollout verification after human-approved integration/deployment

**Files:**
- No source change expected.

**Interfaces:**
- Consumes: deployed AI HQ release containing the Host Helper readiness capability.
- Produces: production evidence that observe-only recovery can see DripVid health through Host Helper.

- [ ] **Step 1: Verify AI HQ smoke checks**

Run the existing `deploy/check-production.sh` and require all checks to pass.

- [ ] **Step 2: Verify recovery flags remain observe-only**

Inside the worker, require:

```text
AI_HQ_RECOVERY_ENABLED=true
AI_HQ_RECOVERY_OBSERVE_ONLY=true
```

- [ ] **Step 3: Invoke the new Host Helper readiness capability from the worker**

Use the repository's authenticated `HostHelperClient` path, not a direct `curl`/HTTP request from the worker. Confirm the response reports healthy DripVid dependencies and bounded storage fields.

- [ ] **Step 4: Confirm sanitization**

Verify the production response contains no storage root/path, raw response body, API keys, tokens, headers, or arbitrary fields.

- [ ] **Step 5: Confirm no mutation enablement**

Do not grant `service.recover`, scoped approval, or set `AI_HQ_RECOVERY_OBSERVE_ONLY=false` as part of this rollout.
