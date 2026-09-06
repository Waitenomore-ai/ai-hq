# Recovery Host Readiness Probe Design

## Problem

AI HQ recovery currently constructs `DripVidReadinessProbe` inside the worker container and probes `http://127.0.0.1:3000/health/ready`. In production, DripVid is intentionally bound to host loopback only. Inside the worker container, `127.0.0.1` refers to the worker container, so the probe fails with connection refused even though DripVid is healthy on the host.

The current production validator also intentionally requires a loopback HTTP readiness URL. Relaxing that validator or exposing DripVid on a bridge/public interface would weaken the existing isolation model.

## Goal

Move DripVid readiness observation to the existing Host Helper boundary so the host performs the fixed loopback request and the worker receives only bounded, sanitized readiness data over the existing authenticated Unix socket.

## Architecture

Add a new read-only Host Helper capability: `dripvid.readiness`.

The capability accepts no arbitrary URL, host, path, headers, command, or model-provided parameters. The Host Helper executor owns one fixed endpoint:

`http://127.0.0.1:3000/health/ready`

The request path is:

`Recovery worker -> HostHelperClient -> Unix socket -> Host Helper -> fixed host-loopback readiness endpoint -> bounded response -> Recovery worker`

The worker no longer performs the production DripVid readiness HTTP request directly.

## Host Helper Contract

Add `HostCapability.DRIPVID_READINESS = "dripvid.readiness"`.

Validation rules:

- `target` must be absent / `None`.
- `params` must be empty.
- Unknown top-level request fields remain rejected.
- No URL or address is accepted from callers.
- The capability is read-only and does not participate in service mutation allow-lists.

## Host-Side Probe

The Host Helper executor performs a GET against the fixed endpoint `http://127.0.0.1:3000/health/ready`.

Requirements:

- Maximum timeout: 3 seconds.
- Maximum response body: 64 KiB.
- HTTP only, fixed host loopback endpoint only.
- Parse JSON object responses only.
- Return a bounded schema containing only:
  - `reachable`
  - `status_code`
  - `ok`
  - `database`
  - `jellyfin`
  - `radarr`
  - `sonarr`
  - `qbittorrent`
  - `requestSync`
  - `storage.available`
  - `storage.writable`
  - `storage.belowReserve`
  - `storage.freeBytes`
  - `storage.reserveBytes`
  - `error`
- Never return filesystem paths, raw bodies, headers, secrets, API keys, timestamps, arbitrary nested fields, or transport internals.
- Connection failure, timeout, invalid JSON, malformed payload, oversized response, or generic transport failure must fail closed into a bounded unhealthy response rather than raising through the worker loop.

## Recovery Probe Integration

Refactor the recovery readiness abstraction so production worker wiring can consume a host-helper-backed probe with the same `probe() -> dict` shape already expected by recovery coordination.

The existing direct HTTP probe may remain available for unit tests or non-production use if useful, but production worker wiring must use Host Helper when recovery is enabled.

The production URL setting remains loopback-only and may be retained for compatibility/documentation, but it must not be interpreted by the worker as a container-local URL for the production recovery path.

## Security Boundary

This change must not grant Developer, QA, or recovery orchestration any new production execution authority.

The new capability is strictly read-only. It must not expose:

- arbitrary HTTP requests;
- arbitrary URLs;
- shell commands;
- service names or systemd unit input;
- filesystem paths;
- Docker operations;
- deployment operations;
- restart/recover authority.

Existing `service.recover`, approval, scoped-rule, simulation, and SysAdmin authorization gates remain unchanged.

DripVid must remain bound to host loopback. No `0.0.0.0` or Docker-bridge exposure is introduced.

## Failure Behavior

If Host Helper is unavailable or the readiness request fails, recovery observation receives a bounded unhealthy readiness result. In observe-only mode this may contribute to incident observation but cannot create or execute recovery missions.

Healthy observations remain quiet unless existing recovery persistence/notification logic requires otherwise.

## Testing

Add or extend tests for:

1. Host Helper contract accepts `dripvid.readiness` only with `target=None` and empty params.
2. Arbitrary URL/target/params are rejected.
3. Executor returns a bounded healthy DripVid readiness payload.
4. Timeout, connection error, invalid JSON, oversized response, and malformed payload fail closed.
5. Extra fields including paths and secrets are stripped.
6. Worker production wiring uses the Host Helper-backed readiness probe rather than direct container HTTP.
7. Recovery security-boundary regression confirms no new direct mutation, subprocess, deployment, service-management, or arbitrary network authority is added to recovery domain code.
8. Existing recovery, Host Helper, worker, lint, full pytest, and Compose validation remain green.

## Production Rollout

Deploy AI HQ normally after CI is green. The Host Helper service must be updated before or together with the worker code because the worker depends on the new capability.

Post-deploy verification:

- Host Helper authenticated health passes.
- Worker can invoke `dripvid.readiness` over the Unix socket.
- Returned payload matches live DripVid readiness and contains no disallowed fields.
- AI HQ liveness/readiness remain healthy.
- `AI_HQ_RECOVERY_ENABLED=true` and `AI_HQ_RECOVERY_OBSERVE_ONLY=true` remain active.
- No automatic recovery mutation is enabled as part of this rollout.
