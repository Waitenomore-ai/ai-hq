import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostAllowLists,
    HostCapability,
)

COMMAND_TIMEOUT_SECONDS = 3.0
MAX_LOG_LINES = 200
MAX_RESPONSE_BYTES = 64 * 1024

SERVICE_UNITS = {
    "ai-hq": "ai-hq-host-helper.service",
    "nginx": "nginx.service",
    "dripvid": "dripvid.service",
}
CONTAINER_TARGETS = {
    "ai-hq-web": "ai-hq-web-1",
    "ai-hq-worker": "ai-hq-worker-1",
    "dripvid": "dripvid",
}
LOG_TARGETS = {
    "ai-hq": ("journal", "ai-hq-host-helper.service"),
    "nginx": ("journal", "nginx.service"),
    "dripvid": ("journal", "dripvid.service"),
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
    ):
        self.allow_lists = allow_lists
        self.command_runner = command_runner

    def _run(self, argv: list[str]) -> CompletedCommand | HelperResponse:
        try:
            result = self.command_runner(argv, COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return HelperResponse(False, HostCapability.HOST_HEALTH, None, {}, "timeout")
        except (OSError, subprocess.SubprocessError):
            return HelperResponse(False, HostCapability.HOST_HEALTH, None, {}, "command_failed")
        return result

    @staticmethod
    def _failure(request: HelperRequest, error: str) -> HelperResponse:
        return HelperResponse(False, request.capability, request.target, {}, error)

    def _command(self, request: HelperRequest, argv: list[str]) -> CompletedCommand | HelperResponse:
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
        if capability is HostCapability.SERVICE_STATUS:
            return self._service_status(request)
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
            (line for line in memory.stdout.splitlines() if line.strip().startswith("Mem:")),
            "",
        ).split()
        filesystem_lines = [line.split() for line in filesystem.stdout.splitlines() if line.strip()]
        filesystem_values = filesystem_lines[-1] if len(filesystem_lines) >= 2 else []

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

    def _service_status(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if target not in self.allow_lists.services or target not in SERVICE_UNITS:
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            [
                "systemctl",
                "show",
                SERVICE_UNITS[target],
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

    def _container_status(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if target not in self.allow_lists.containers or target not in CONTAINER_TARGETS:
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            ["docker", "inspect", CONTAINER_TARGETS[target], "--format", "{{json .State}}"],
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
            {"status": state.get("Status"), "health": health.get("Status")},
        )

    def _logs_recent(self, request: HelperRequest) -> HelperResponse:
        target = request.target
        if target not in self.allow_lists.logs or target not in LOG_TARGETS:
            return self._failure(request, "unknown target")
        lines = request.params.get("lines", 100)
        if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= MAX_LOG_LINES:
            return self._failure(request, "invalid parameters")
        source, unit = LOG_TARGETS[target]
        if source != "journal":
            return self._failure(request, "unknown target")
        result = self._command(
            request,
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
        )
        if isinstance(result, HelperResponse):
            return result
        redacted = _redact(result.stdout)
        text, truncated = _truncate_utf8(redacted)
        return HelperResponse(
            True,
            request.capability,
            target,
            {"text": text, "lines_requested": lines, "truncated": truncated},
        )
