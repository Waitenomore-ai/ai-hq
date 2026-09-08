# Soup Core Worker-Only Design

## Goal

Add the canonical Soup CLI (`soup-cli==0.74.0`) to AI HQ as a worker-only capability while preserving the existing isolation boundaries between the web container, worker container, Host Helper, and DripVid MCP integration.

## Scope

This change installs only the light Soup core package. It does not install the `[train]`, `[all]`, MCP, UI, serving, or other optional Soup extras. It does not download any model weights, expose GPU devices, create a Soup MCP server, or add any new AI HQ tool permission, shell authority, restart authority, deployment authority, or model-selected command execution.

The target Soup release is exactly `soup-cli==0.74.0` from the canonical `MakazhanAlpamys/Soup` project. Soup supports Python 3.10 through 3.12; AI HQ currently runs Python 3.12.

## Architecture

AI HQ currently builds both `web` and `worker` from the same Dockerfile image. Installing Soup as a normal AI HQ dependency would therefore place it in both containers. To maintain the approved worker-only boundary, the Dockerfile will use named build stages:

1. `base`: installs the normal AI HQ package and contains all shared runtime files.
2. `web`: extends `base` without Soup and runs the existing web entrypoint.
3. `worker`: extends `base`, installs exactly `soup-cli==0.74.0`, and runs the existing worker entrypoint.

`compose.yaml` will explicitly select the `web` build target for the web service and the `worker` build target for the worker service.

No new volume, socket, secret, port, Linux capability, privileged mode, Docker socket, or device mapping is introduced by this change.

## Security Boundaries

The installation itself grants no AI HQ authority to execute Soup commands. Soup is simply present in the worker filesystem and Python environment for future controlled integration work.

The following remain unchanged:

- Web does not receive DripVid MCP socket/token access.
- Worker-only DripVid MCP and Host Helper access remains as currently configured.
- AI HQ containers do not receive the Docker socket.
- No arbitrary shell or subprocess authority is introduced.
- No Soup MCP server is started.
- No Soup `--allow-execute` capability is enabled.
- No training stack or model download is enabled.
- No GPU device is passed through to the worker.

## Dependency Policy

The Soup package must be pinned exactly to `soup-cli==0.74.0` in the worker Docker stage rather than added to AI HQ's shared Python dependencies. This keeps the web runtime free of Soup and prevents an upstream Soup release from changing production behavior unexpectedly.

Future upgrades require an explicit version change and normal review/testing.

## Verification

Tests will prove the configuration contract before implementation:

- The Dockerfile defines `base`, `web`, and `worker` stages.
- Only the worker stage contains `soup-cli==0.74.0`.
- The web stage does not install Soup.
- Compose selects the `web` target for `web` and `worker` target for `worker`.
- Existing worker-only MCP/Host Helper isolation remains intact.
- No Soup MCP, execute permission, Docker socket, privileged mode, GPU device mapping, or new port is added.

CI will then run the existing Ruff, pytest, and Compose validation suite. A build-level verification should additionally confirm that the worker image can resolve/import Soup and invoke the Soup CLI while the web image cannot resolve the Soup package.

## Production Rollout

This design does not itself authorize production deployment. After implementation, exact-head CI and image checks must pass. Production deployment remains a separate explicit approval boundary and must use the existing immutable AI HQ deployment process and `deploy/check-production.sh` verification.

## Future Work

A later, separately approved change may add Soup training support (`soup-cli[train]`) and GPU access. That work must be treated as a new design because it substantially increases image size, dependency surface, resource access, and execution authority.