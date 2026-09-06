from __future__ import annotations

import json
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx

from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry


MAX_READINESS_BYTES = 64 * 1024
DEFAULT_PROBE_TIMEOUT_SECONDS = 3.0

_READINESS_BOOLEAN_FIELDS = (
    "database",
    "jellyfin",
    "radarr",
    "sonarr",
    "qbittorrent",
    "requestSync",
)

_STORAGE_BOOLEAN_FIELDS = (
    "available",
    "writable",
    "belowReserve",
)

_STORAGE_INTEGER_FIELDS = (
    "freeBytes",
    "reserveBytes",
)


def _validate_loopback_http(url: str) -> None:
    parsed = urlsplit(url)

    if parsed.scheme.casefold() != "http" or not parsed.hostname:
        raise ValueError("readiness URL must use loopback HTTP")

    host = parsed.hostname

    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"

    if not loopback:
        raise ValueError("readiness URL must use loopback HTTP")


def _bounded_error(*, reachable: bool, status_code: int | None, error: str) -> dict:
    return {
        "reachable": reachable,
        "status_code": status_code,
        "ok": False,
        "error": error,
    }


def _normalize_storage(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None

    storage: dict[str, object] = {}

    for field in _STORAGE_BOOLEAN_FIELDS:
        candidate = value.get(field)
        if isinstance(candidate, bool):
            storage[field] = candidate

    for field in _STORAGE_INTEGER_FIELDS:
        candidate = value.get(field)
        if (
            isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and candidate >= 0
        ):
            storage[field] = candidate

    return storage


def _normalize_payload(payload: dict, status_code: int) -> dict:
    result: dict[str, object] = {
        "reachable": True,
        "status_code": status_code,
        "ok": payload.get("ok") is True,
    }

    for field in _READINESS_BOOLEAN_FIELDS:
        candidate = payload.get(field)
        if isinstance(candidate, bool):
            result[field] = candidate

    storage = _normalize_storage(payload.get("storage"))
    if storage is not None:
        result["storage"] = storage

    result["error"] = None
    return result


class DripVidReadinessProbe:
    """Bounded, read-only probe for DripVid's loopback readiness endpoint."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        _validate_loopback_http(url)

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > 10
        ):
            raise ValueError(
                "readiness probe timeout must be greater than 0 and at most 10 seconds"
            )

        self.url = url
        self.timeout_seconds = float(timeout_seconds)
        self._client = client

    def probe(self) -> dict:
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        owns_client = self._client is None

        try:
            response = client.get(
                self.url,
                timeout=self.timeout_seconds,
            )
            body = response.content

            if len(body) > MAX_READINESS_BYTES:
                return _bounded_error(
                    reachable=True,
                    status_code=response.status_code,
                    error="response_too_large",
                )

            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _bounded_error(
                    reachable=True,
                    status_code=response.status_code,
                    error="invalid_json",
                )

            if not isinstance(payload, dict):
                return _bounded_error(
                    reachable=True,
                    status_code=response.status_code,
                    error="invalid_json",
                )

            return _normalize_payload(payload, response.status_code)
        except httpx.TimeoutException:
            return _bounded_error(
                reachable=False,
                status_code=None,
                error="timeout",
            )
        except httpx.ConnectError:
            return _bounded_error(
                reachable=False,
                status_code=None,
                error="connection_error",
            )
        except httpx.HTTPError:
            return _bounded_error(
                reachable=False,
                status_code=None,
                error="transport_error",
            )
        finally:
            if owns_client:
                client.close()


def recovery_diagnostic_targets() -> OperationalTargetRegistry:
    """Return the fixed read-only diagnostic target map used by recovery."""

    read_only = frozenset({
        "service.status.read",
        "service.logs.read",
    })

    return OperationalTargetRegistry(
        [
            OperationalTarget(
                key="dripvid-app",
                service_unit="dripvid.service",
                log_unit="dripvid.service",
                allowed_capabilities=read_only,
                host_helper_service_target="dripvid",
                host_helper_log_target="dripvid",
            ),
            OperationalTarget(
                key="dripvid-mcp",
                service_unit="dripvid-mcp.service",
                log_unit="dripvid-mcp.service",
                allowed_capabilities=read_only,
                host_helper_service_target="dripvid-mcp",
                host_helper_log_target="dripvid-mcp",
            ),
            OperationalTarget(
                key="dripvid-proxy",
                service_unit="nginx.service",
                log_unit="nginx.service",
                allowed_capabilities=read_only,
                host_helper_service_target="nginx",
                host_helper_log_target="nginx",
            ),
            OperationalTarget(
                key="dripvid-tunnel",
                service_unit="cloudflared.service",
                log_unit="cloudflared.service",
                allowed_capabilities=read_only,
                host_helper_service_target="cloudflared",
                host_helper_log_target="cloudflared",
            ),
            OperationalTarget(
                key="dripvid-database",
                service_unit="postgresql.service",
                log_unit="postgresql.service",
                allowed_capabilities=read_only,
                host_helper_service_target="postgresql",
                host_helper_log_target="postgresql",
            ),
        ]
    )
