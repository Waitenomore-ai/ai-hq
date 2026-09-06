import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostAllowLists,
    HostCapability,
)

COMMAND_TIMEOUT_SECONDS = 8.0
MAX_LOG_LINES = 200
MAX_RESPONSE_BYTES = 64 * 1024
DRIPVID_READINESS_URL = "http://127.0.0.1:3000/health/ready"
DRIPVID_READINESS_TIMEOUT_SECONDS = 3.0

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
_ALLOWED_READINESS_ERRORS = frozenset(
    {
        "timeout",
        "connection_error",
        "transport_error",
        "response_too_large",
        "invalid_json",
    }
)

SERVICE_UNITS = {
    "ai-hq": "ai-hq-host-helper.service",
    "nginx": "nginx.service",
    "dripvid": "dripvid.service",
}
DIAGNOSTIC_SERVICE_UNITS = {
    "dripvid-mcp": "dripvid-mcp.service",
    "cloudflared": "cloudflared.service",
    "postgresql": "postgresql.service",
}
READ_SERVICE_UNITS = {
    **SERVICE_UNITS,
    **DIAGNOSTIC_SERVICE_UNITS,
}
RECOVERY_SERVICE_UNITS = {
    "app": "dripvid.service",
    "mcp": "dripvid-mcp.service",
    "proxy": "nginx.service",
    "tunnel": "cloudflared.service",
    "database": "postgresql.service",
}
CONTAINER_TARGETS = {
    "ai-hq-web": "ai-hq-web-1",
    "ai-hq-worker": "ai-hq-worker-1",
}
DEPLOY_ENTRYPOINTS = {
    "ai-hq": ("/opt/ai-hq/bin/controlled-deploy", "ai-hq"),
}

ROLLBACK_ENTRYPOINTS = {
    "ai-hq": ("/opt/ai-hq/bin/controlled-rollback", "ai-hq"),
}


LOG_TARGETS = {
    "ai-hq": ("journal", "ai-hq-host-helper.service"),
    "nginx": ("journal", "nginx.service"),
    "dripvid": ("journal", "dripvid.service"),
    "dripvid-mcp": ("journal", "dripvid-mcp.service"),
    "cloudflared": ("journal", "cloudflared.service"),
    "postgresql": ("journal", "postgresql.service"),
}

_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^(?P<prefix>\s*[^=\s]*(?:password|secret|token|api_key|authorization)[^=\s]*\s*=).*?$"
)


@dataclass(frozen=True, slots=True)
class CompletedCommand:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], float], CompletedCommand]
ReadinessRunner = Callable[[str, float, int], dict[str, object]]


def default_command_runner(argv: list[str], timeout: float) -> CompletedCommand:
    completed = subprocess.run(
        argv,
        shell=False,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CompletedCommand(completed.returncode, completed.stdout, completed.stderr)


def _bounded_readiness_error(
    *,
    reachable: bool,
    status_code: int | None,
    error: str,
) -> dict[str, object]:
    return {
        "reachable": reachable,
        "status_code": status_code,
        "ok": False,
        "error": error,
    }


def _normalize_readiness(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return _bounded_readiness_error(
            reachable=False,
            status_code=None,
            error="transport_error",
        )

    reachable = payload.get("reachable") is True
    status_code = payload.get("status_code")
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        status_code = None

    result: dict[str, object] = {
        "reachable": reachable,
        "status_code": status_code,
        "ok": payload.get("ok") is True,
    }

    for field in _READINESS_BOOLEAN_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool):
            result[field] = value

    storage_value = payload.get("storage")
    if isinstance(storage_value, dict):
        storage: dict[str, object] = {}
        for field in _STORAGE_BOOLEAN_FIELDS:
            value = storage_value.get(field)
            if isinstance(value, bool):
                storage[field] = value
        for field in _STORAGE_INTEGER_FIELDS:
            value = storage_value.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                storage[field] = value
        if storage:
            result["storage"] = storage

    error = payload.get("error")
    result["error"] = error if error in _ALLOWED_READINESS_ERRORS else None
    return result


def default_readiness_runner(url: str, timeout: float, limit: int) -> dict[str, object]:
    try:
        with httpx.stream("GET", url, timeout=timeout) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    return _bounded_readiness_error(
                        reachable=True,
                        status_code=response.status_code,
                        error="response_too_large",
                    )
    except httpx.TimeoutException:
        return _bounded_readiness_error(
            reachable=False,
            status_code=None,
            error="timeout",
        )
    except httpx.ConnectError:
        return _bounded_readiness_error(
            reachable=False,
            status_code=None,
            error="connection_error",
        )
    except httpx.HTTPError:
        return _bounded_readiness_error(
            reachable=False,
            status_code=None,
            error="transport_error",
        )

    try:
        payload = json.loads(bytes(body))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _bounded_readiness_error(
            reachable=True,
            status_code=response.status_code,
            error="invalid_json",
        )

    if not isinstance(payload, dict):
        return _bounded_readiness_error(
            reachable=True,
            status_code=response.status_code,
            error="invalid_json",
        )

    payload = {
        **payload,
        "reachable": True,
        "status_code": response.status_code,
    }
    return _normalize_readiness(payload)


def _redact(text: str) -> str:
    return _SECRET_ASSIGNMENT.sub(r"\g<prefix>[REDACTED]", text)


def _truncate_utf8(text: str, limit: int = MAX_RESPONSE_BYTES) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class HostExecutor:
    def __init__(
        self,
        allow_lists: HostAllowLists,
        *,
        command_runner: CommandRunner = default_command_runner,
        readiness_runner: ReadinessRunner = default_readiness_runner,
    ):
        self.allow_lists = allow_lists
        self.command_runner = command_runner
        self.readiness_runner = readiness_runner

    @staticmethod
    def _failure(request: HelperRequest, error: str) -> HelperResponse:
        return HelperResponse(False, request.capability, request.target, {}, error)

    def _command(
        self,
        request: HelperRequest,
        argv: list[str],
    ) -> CompletedCommand | HelperResponse:
        try:
            result = self.command_runner(argv, COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return self._failure(request, "timeout")
        except (OSError, subprocess.SubprocessError):
            return self._failure(request, "command_failed")
        if result.returncode != 0:
            return self._failure(request, "command_failed")
        return result

    def execute(self, request: HelperRequest) -> HelperResponse:
        capability = request.capability
        if capability is HostCapability.HOST_HEALTH:
            return self._host_health(request)
        if capability is HostCapability.HOST_RESOURCES:
            return self._host_resources(request)
        if capability is HostCapability.DRIPVID_READINESS:
            return self._dripvid_readiness(request)
        if capability is HostCapability.SERVICE_STATUS:
            return self._service_status(request)
        if capability is HostCapability.SERVICE_RESTART:
            return self._service_restart(request)
        if capability is HostCapability.SERVICE_RECOVER:
            return self._service_recover(request)
        if capability is HostCapability.DEPLOYMENT_DEPLOY:
            return self._deployment_deploy(request)
        if capability is HostCapability.DEPLOYMENT_ROLLBACK:
            return self._deployment_rollback(request)
        if capability is HostCapability.CONTAINER_STATUS:
            return self._container_status(request)
        if capability is HostCapability.LOGS_RECENT:
            return self._logs_recent(request)
        return self._failure(request, "unknown capability")

    def _host_health(self, request: HelperRequest) -> HelperResponse:
        uptime = self._command(request, ["uptime", "-p"])
        if isinstance(uptime, HelperResponse):
            return uptime
        load = self._command(request, ["cat", "/proc/loadavg"])
        if isinstance(load, HelperResponse):
            return load
        load_values = load.stdout.strip().split()
        return HelperResponse(
            True,
            request.capability,
            None,
            {
                "uptime": uptime.stdout.strip(),
                "load_1m": load_values[0] if len(load_values) > 0 else None,
                "load_5m": load_values[1] if len(load_values) > 1 else None,
                "load_15m": load_values[2] if len(load_values) > 2 else None,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _host_resources(self, request: HelperRequest) -> HelperResponse:
        load = self._command(request, ["cat", "/proc/loadavg"])
        if isinstance(load, HelperResponse):
            return load
        memory = self._command(request, ["free", "-b"])
        if isinstance(memory, HelperResponse):
            return memory
        filesystem = self._command(request, ["df", "-B1", "/"])
        if isinstance(filesystem, HelperResponse):
            return filesystem

        load_values = load.stdout.strip().split()
        memory_line = next(
            (
                line
                for line in memory.stdout.splitlines()
                if line.strip().startswith("Mem:")
            ),
            "",
        ).split()
        filesystem_lines = [
            line.split()
            for line in filesystem.stdout.splitlines()
            if line.strip()
        ]
        filesystem_values = (
            filesystem_lines[-1]
            if len(filesystem_lines) >= 2
            else []
        )

        if len(memory_line) < 4 or len(filesystem_values) < 6:
            return self._failure(request, "malformed_response")

        return HelperResponse(
            True,
            request.capability,
            None,
            {
                "load": {
                    "1m": load_values[0] if len(load_values) > 0 else None,
                    "5m": load_values[1] if len(load_values) > 1 else None,
                    "15m": load_values[2] if len(load_values) > 2 else None,
                },
                "memory": {
                    "total_bytes": int(memory_line[1]),
                    "used_bytes": int(memory_line[2]),
                    "free_bytes": int(memory_line[3]),
                },
                "filesystem": {
                    "path": "/",
                    "total_bytes": int(filesystem_values[1]),
                    "used_bytes": int(filesystem_values[2]),
                    "available_bytes": int(filesystem_values[3]),
                    "use_percent": filesystem_values[4],
                },
            },
        )

    def _dripvid_readiness(self, request: HelperRequest) -> HelperResponse:
        if request.target is not None or request.params:
            return self._failure(request, "invalid parameters")

        try:
            payload = self.readiness_runner(
                DRIPVID_READINESS_URL,
                DRIPVID_READINESS_TIMEOUT_SECONDS,
                MAX_RESPONSE_BYTES,
            )
        except TimeoutError:
            payload = _bounded_readiness_error(
                reachable=False,
                status_code=None,
                error="timeout",
            )
        except OSError:
            payload = _bounded_readiness_error(
                reachable=False,
                status_code=None,
                error="connection_error",
            )
        except Exception:
            payload = _bounded_readiness_error(
                reachable=False,
                status_code=None,
                error="transport_error",
            )

        return HelperResponse(
            True,
            request.capability,
            None,
            _normalize_readiness(payload),
        )

    def _service_status(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        allowed = self.allow_lists.services | self.allow_lists.diagnostic_services
        if target not in allowed or target not in READ_SERVICE_UNITS:
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            [
                "systemctl",
                "show",
                READ_SERVICE_UNITS[target],
                "--no-page",
                "--property=ActiveState,SubState,LoadState,UnitFileState",
            ],
        )
        if isinstance(result, HelperResponse):
            return result
        values = _key_values(result.stdout)
        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "active_state": values.get("ActiveState"),
                "sub_state": values.get("SubState"),
                "load_state": values.get("LoadState"),
                "unit_file_state": values.get("UnitFileState"),
            },
        )

    def _service_restart(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if target not in self.allow_lists.services or target not in SERVICE_UNITS:
            return self._failure(request, "unknown target")

        restarted = self._command(
            request,
            ["systemctl", "restart", SERVICE_UNITS[target]],
        )
        if isinstance(restarted, HelperResponse):
            return restarted

        status = self._command(
            request,
            [
                "systemctl",
                "show",
                SERVICE_UNITS[target],
                "--no-page",
                "--property=ActiveState,SubState,LoadState,UnitFileState",
            ],
        )
        if isinstance(status, HelperResponse):
            return status

        values = _key_values(status.stdout)
        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "restarted": True,
                "active_state": values.get("ActiveState"),
                "sub_state": values.get("SubState"),
                "load_state": values.get("LoadState"),
                "unit_file_state": values.get("UnitFileState"),
            },
        )

    def _service_recover(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if target != "dripvid" or target not in self.allow_lists.services:
            return self._failure(request, "unknown target")

        if set(request.params) != {"component"}:
            return self._failure(request, "invalid parameters")

        component = request.params.get("component")
        if (
            not isinstance(component, str)
            or component not in RECOVERY_SERVICE_UNITS
        ):
            return self._failure(request, "invalid parameters")

        unit = RECOVERY_SERVICE_UNITS[component]
        restarted = self._command(
            request,
            ["systemctl", "restart", unit],
        )
        if isinstance(restarted, HelperResponse):
            return restarted

        status = self._command(
            request,
            [
                "systemctl",
                "show",
                unit,
                "--no-page",
                "--property=ActiveState,SubState,LoadState,UnitFileState",
            ],
        )
        if isinstance(status, HelperResponse):
            return status

        values = _key_values(status.stdout)
        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "component": component,
                "restarted": True,
                "active_state": values.get("ActiveState"),
                "sub_state": values.get("SubState"),
                "load_state": values.get("LoadState"),
                "unit_file_state": values.get("UnitFileState"),
            },
        )

    def _deployment_deploy(
        self,
        request: HelperRequest,
    ) -> HelperResponse:
        target = request.target

        if request.params:
            return self._failure(request, "invalid parameters")

        if (
            target not in self.allow_lists.services
            or target not in DEPLOY_ENTRYPOINTS
        ):
            return self._failure(request, "unknown target")

        result = self._command(
            request,
            list(DEPLOY_ENTRYPOINTS[target]),
        )

        if isinstance(result, HelperResponse):
            return result

        return HelperResponse(
            True,
            request.capability,
            target,
            {"deployed": True},
        )

    def _deployment_rollback(
        self,
        request: HelperRequest,
    ) -> HelperResponse:
        target = request.target

        if (
            target not in self.allow_lists.services
            or target not in ROLLBACK_ENTRYPOINTS
        ):
            return self._failure(request, "unknown target")

        if set(request.params) != {"release_id"}:
            return self._failure(request, "invalid parameters")

        release_id = request.params.get("release_id")

        if (
            not isinstance(release_id, str)
            or not release_id
            or len(release_id) > 128
            or not release_id.isascii()
            or any(
                not (char.isalnum() or char in "._-")
                for char in release_id
            )
        ):
            return self._failure(request, "invalid parameters")

        result = self._command(
            request,
            [
                *ROLLBACK_ENTRYPOINTS[target],
                release_id,
            ],
        )

        if isinstance(result, HelperResponse):
            return result

        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "rolled_back": True,
                "release_id": release_id,
            },
        )

    def _container_status(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if (
            target not in self.allow_lists.containers
            or target not in CONTAINER_TARGETS
        ):
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            [
                "docker",
                "inspect",
                CONTAINER_TARGETS[target],
                "--format",
                "{{json .State}}",
            ],
        )
        if isinstance(result, HelperResponse):
            return result
        try:
            state = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return self._failure(request, "malformed_response")
        health = state.get("Health") or {}
        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "status": state.get("Status"),
                "health": health.get("Status"),
            },
        )

    def _logs_recent(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        allowed = self.allow_lists.logs | self.allow_lists.diagnostic_logs
        if target not in allowed or target not in LOG_TARGETS:
            return self._failure(request, "unknown target")
        lines = request.params.get("lines", 100)
        if (
            isinstance(lines, bool)
            or not isinstance(lines, int)
            or not 1 <= lines <= MAX_LOG_LINES
        ):
            return self._failure(request, "invalid parameters")
        source, unit = LOG_TARGETS[target]
        if source != "journal":
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            [
                "journalctl",
                "-u",
                unit,
                "-n",
                str(lines),
                "--no-pager",
                "-o",
                "short-iso",
            ],
        )
        if isinstance(result, HelperResponse):
            return result
        redacted = _redact(result.stdout)
        text, truncated = _truncate_utf8(redacted)
        return HelperResponse(
            True,
            request.capability,
            target,
            {
                "text": text,
                "truncated": truncated,
            },
        )
