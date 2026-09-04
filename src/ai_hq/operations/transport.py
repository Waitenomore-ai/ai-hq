from collections.abc import Callable
import subprocess

from ai_hq.operations.targets import OperationalTarget
from ai_hq.tool_gateway.contracts import ToolAdapterError

Runner = Callable[..., object]

MAX_OUTPUT_CHARS = 64_000
COMMAND_TIMEOUT_SECONDS = 15


class SubprocessOperationalTransport:
    """
    Restricted local operational transport.

    This class never accepts an executable, service unit, file path,
    hostname, or command from a mission. Those values come from trusted
    OperationalTarget configuration.
    """

    def __init__(self, *, runner: Runner = subprocess.run) -> None:
        self.runner = runner

    def _run(self, argv: list[str]) -> object:
        try:
            result = self.runner(
                argv,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolAdapterError("operational_command_failed") from exc

        returncode = getattr(result, "returncode", 1)

        if returncode != 0:
            raise ToolAdapterError("operational_command_failed")

        return result

    @staticmethod
    def _stdout(result: object) -> str:
        value = getattr(result, "stdout", "")
        if not isinstance(value, str):
            return ""
        return value[:MAX_OUTPUT_CHARS]

    def system_health(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        result = self._run(
            ["systemctl", "is-active", target.service_unit]
        )
        active = self._stdout(result).strip() == "active"

        return {
            "target": target.key,
            "service_active": active,
        }

    def service_status(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        result = self._run(
            ["systemctl", "is-active", target.service_unit]
        )
        state = self._stdout(result).strip()

        return {
            "target": target.key,
            "service": target.service_unit,
            "state": state,
            "active": state == "active",
        }

    def service_logs(
        self,
        target: OperationalTarget,
        *,
        lines: int,
    ) -> dict[str, object]:
        unit = target.log_unit or target.service_unit

        result = self._run([
            "journalctl",
            "--unit",
            unit,
            "--lines",
            str(lines),
            "--no-pager",
        ])

        output = self._stdout(result)

        return {
            "target": target.key,
            "lines": output.splitlines(),
        }

    def service_restart(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        self._run(
            ["systemctl", "restart", target.service_unit]
        )

        return {
            "target": target.key,
            "service": target.service_unit,
            "restarted": True,
        }
