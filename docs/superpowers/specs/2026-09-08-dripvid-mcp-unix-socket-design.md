# DripVid MCP Unix-Socket Integration Design

## Goal

Connect AI HQ to the DripVid MCP service without exposing the MCP service on a non-loopback network interface and without granting AI HQ arbitrary host, restart, deployment, or write authority.

## Current state

DripVid MCP is deployed as a read-only systemd service and listens on `127.0.0.1:8788`. It exposes read-only operational tools including `dripvid_health`, `dripvid_git_status`, `dripvid_config`, `service_status`, and other host-observation tools. The old passwordless restart sudoers authority has been removed.

AI HQ runs inside Docker containers, so `127.0.0.1:8788` inside AI HQ does not refer to the host's DripVid MCP service. Binding MCP to `0.0.0.0` or a Docker-reachable host interface would weaken the current boundary and is rejected.

## Architecture

DripVid MCP will keep its existing localhost HTTP listener for local diagnostics and will add a Unix-domain socket endpoint at a fixed host path under `/run/dripvid-mcp/`. The socket is created by the systemd service with restrictive ownership and permissions and is not network-routable.

AI HQ will receive that socket through an explicit Docker bind mount. The AI HQ MCP client will use HTTP over the Unix socket and will never accept an arbitrary MCP URL, host, port, or socket path from a model or user request. The socket path is fixed by trusted configuration.

The MCP bearer credential remains separate from ordinary application configuration. The credential is mounted only into the AI HQ component that calls DripVid MCP, and the client reads it from a file rather than accepting a token value through chat or model output.

## AI HQ allowlist

AI HQ will enforce its own fixed allowlist even though DripVid MCP is already read-only. Initial allowed calls are:

- `dripvid_health` with no caller-supplied arguments.
- `dripvid_git_status` with no caller-supplied arguments.
- `dripvid_config` with no caller-supplied arguments.
- `service_status` only for the fixed service names `dripvid`, `jellyfin`, `cloudflared`, and `dripvid-requests`.

AI HQ must reject every other MCP tool name, including `server_info`, `disk_status`, `network_status`, `service_logs`, and `http_health`, until each is separately approved and added to the trusted allowlist. A future DripVid MCP release adding new tools must not automatically expand AI HQ authority.

## Transport and protocol

The DripVid MCP server continues to expose MCP over HTTP semantics. AI HQ uses `httpx` with Unix-domain-socket transport and a fixed logical base URL. Requests include the bearer token from the trusted credential file.

The client must have short fixed timeouts, bounded response sizes, JSON validation, and fail-closed handling for malformed or unexpected MCP responses. It must not follow redirects to another endpoint.

The integration must support the MCP initialization/session flow required by the currently deployed DripVid MCP server. Session identifiers returned by the server may be stored only in process memory and are not authority tokens.

## DripVid service changes

DripVid MCP gains a second listener backed by a Unix-domain socket while retaining `127.0.0.1:8788` for host-local health and diagnostics. The socket directory and socket itself are managed by systemd/runtime startup and cleaned up on restart.

The service remains read-only. No `sudo`, service restart, deploy, shell, arbitrary command, arbitrary path, arbitrary URL, or filesystem-write capability is added.

## AI HQ integration surface

A focused `dripvid_mcp` package will own the transport, allowlist, and response parsing. The existing Tool Gateway or SysAdmin chat may call this package, but model-generated text never directly selects a raw MCP method name or endpoint.

The first UI/chat integration will expose read-only DripVid inspection such as health, deployed release, redacted configuration, and allowlisted service state. These calls require normal authenticated AI HQ access but do not require human approval because they are read-only. Any future mutating DripVid MCP capability remains subject to the existing AI HQ approval and safety architecture and is out of scope for this change.

## Configuration and secrets

Trusted AI HQ settings will define only:

- a fixed Unix socket path, expected in production to be `/run/dripvid-mcp/mcp.sock`;
- a fixed credential-file path mounted into the calling AI HQ container;
- fixed request timeout values within safe bounds.

Production validation must reject non-absolute socket or credential paths and must not permit a network URL in place of the Unix socket.

The DripVid MCP bearer token must not be committed to either repository, emitted by deployment scripts, logged, persisted in mission records, or returned to the model.

## Docker and systemd boundary

Only the AI HQ container that requires read-only MCP access receives the socket and credential mounts. The mount is read-only from the AI HQ side where supported. No Docker socket, host root filesystem, or privileged mode is added.

The DripVid MCP service user retains only the permissions required for its existing read-only observation commands. The Unix socket permissions are set so the intended AI HQ runtime can connect without making the socket world-writable.

## Testing

DripVid tests must prove that the Unix socket listener is created at the fixed path, localhost HTTP remains available, startup removes a stale socket safely, shutdown closes the socket, and no restart/sudo authority is reintroduced.

AI HQ tests must prove that:

- the client connects through a Unix socket rather than TCP;
- the bearer credential is loaded from a trusted file and never accepted as a tool argument;
- only the four approved tool families are callable;
- `service_status` rejects services outside the fixed service allowlist;
- arbitrary MCP tool names, URLs, socket paths, redirects, and malformed responses fail closed;
- no new Docker privileged/Docker-socket authority is introduced;
- chat/Tool Gateway wiring returns read-only MCP results without exposing transport controls to the model.

CI for both repositories must pass before merge. Production deployment remains a separate explicit action after the exact merged commits are known.

## Rollout

1. Add and verify the Unix-socket listener in DripVid MCP while preserving the existing localhost endpoint.
2. Deploy the exact DripVid commit and verify both listeners locally.
3. Add the constrained AI HQ MCP client, trusted configuration, container mounts, and read-only Tool Gateway/chat integration.
4. Deploy the exact AI HQ commit.
5. Run an end-to-end read-only query from AI HQ to DripVid MCP and verify that non-allowlisted calls are rejected.

## Non-goals

This change does not add service restart, deployment, repository mutation, shell access, arbitrary MCP discovery/execution, arbitrary host networking, database writes, or autonomous approval bypass. It does not make DripVid MCP publicly reachable and does not replace the existing AI HQ code-change candidate/approval architecture.
