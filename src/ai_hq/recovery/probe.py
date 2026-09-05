from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class DiagnosticReader(Protocol):
    def service_status(self, target: str) -> dict[str, Any]: ...

    def recent_logs(self, target: str, *, lines: int = 100) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    ok: bool
    payload: dict[str, Any]
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    services: dict[str, dict[str, Any]]
    logs: dict[str, dict[str, Any]]


class DripVidReadinessProbe:
    """Bounded, read-only DripVid readiness probe.

    The probe accepts only the configured loopback readiness URL and returns a
    normalized snapshot. It never performs recovery itself.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 10:
            raise ValueError("readiness probe timeout must be between 0 and 10 seconds")
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._client = client

    def probe(self) -> ReadinessSnapshot:
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        owns_client = self._client is None
        try:
            response = client.get(self.url, timeout=self.timeout_seconds)
            try:
                payload = response.json()
            except ValueError:
                payload = {}

            if not isinstance(payload, dict):
                payload = {}

            return ReadinessSnapshot(
                ok=response.status_code == 200 and payload.get("ok") is True,
                payload=payload,
                status_code=response.status_code,
                error=None,
            )
        except httpx.HTTPError as exc:
            return ReadinessSnapshot(
                ok=False,
                payload={},
                status_code=None,
                error=exc.__class__.__name__,
            )
        finally:
            if owns_client:
                client.close()


RECOVERY_DIAGNOSTIC_TARGETS = (
    "dripvid",
    "dripvid-mcp",
    "nginx",
    "cloudflared",
    "postgresql",
)


def collect_recovery_diagnostics(
    reader: DiagnosticReader,
    *,
    log_lines: int = 100,
) -> DiagnosticSnapshot:
    if isinstance(log_lines, bool) or not isinstance(log_lines, int) or not 1 <= log_lines <= 200:
        raise ValueError("recovery diagnostic log lines must be between 1 and 200")

    services: dict[str, dict[str, Any]] = {}
    logs: dict[str, dict[str, Any]] = {}

    for target in RECOVERY_DIAGNOSTIC_TARGETS:
        services[target] = dict(reader.service_status(target))
        logs[target] = dict(reader.recent_logs(target, lines=log_lines))

    return DiagnosticSnapshot(services=services, logs=logs)
