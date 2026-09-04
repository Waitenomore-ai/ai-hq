from dataclasses import dataclass
import re


READ_TOOLS = frozenset(
    {
        "system.health.read",
        "service.status.read",
        "service.logs.read",
    }
)

TARGET = "ai-hq"

MUTATION_PATTERNS = (
    r"\brestart\b",
    r"\breboot\b",
    r"\bdeploy\b",
    r"\brollback\b",
    r"\broll back\b",
    r"\bstop\b",
    r"\bstart\b",
    r"\bkill\b",
    r"\bshutdown\b",
    r"\bpoweroff\b",
    r"\bshell\b",
    r"\bterminal\b",
    r"\bcommand\b",
    r"\bexecute\b",
    r"\brun\s+(?:a\s+)?(?:shell|command)\b",
    r"\brm\s+-",
    r"\bsudo\b",
)


@dataclass(frozen=True)
class ChatIntent:
    kind: str
    steps: tuple[dict, ...] = ()
    refusal_reason: str | None = None


def _step(
    tool_name: str,
    description: str,
) -> dict:
    if tool_name not in READ_TOOLS:
        raise ValueError("Tool is not allowed for SysAdmin Chat v1")

    return {
        "description": description,
        "tool_name": tool_name,
        "tool_arguments": {"target": TARGET},
    }


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _is_mutation_request(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in MUTATION_PATTERNS)


def plan_sysadmin_intent(text: str) -> ChatIntent:
    normalized = " ".join(text.lower().split())

    if _is_mutation_request(normalized):
        return ChatIntent(
            kind="refused",
            refusal_reason=(
                "SysAdmin currently has read-only authority. "
                "Restart, deploy, rollback, shell and other "
                "mutation operations are not enabled."
            ),
        )

    wants_logs = _contains_any(
        normalized,
        (
            " log",
            "logs",
            "logging",
            "recent log",
        ),
    )

    wants_status = _contains_any(
        normalized,
        (
            "service status",
            "service running",
            "service up",
            "services running",
            "services up",
            "is the service",
            "status of the service",
        ),
    )

    wants_health = _contains_any(
        normalized,
        (
            "system health",
            "server health",
            "health check",
            "check health",
            "machine health",
            "host health",
        ),
    )

    general_server_check = (
        _contains_any(
            normalized,
            (
                "how is my server",
                "how's my server",
                "how is the server",
                "how's the server",
                "server doing",
                "server okay",
                "server ok",
                "server healthy",
                "services healthy",
                "everything running",
                "everything okay",
                "everything ok",
            ),
        )
        and not wants_logs
        and not wants_status
        and not wants_health
    )

    if general_server_check:
        return ChatIntent(
            kind="operational",
            steps=(
                _step(
                    "system.health.read",
                    "Inspect AI HQ system health",
                ),
                _step(
                    "service.status.read",
                    "Inspect AI HQ service status",
                ),
                _step(
                    "service.logs.read",
                    "Inspect recent AI HQ service logs",
                ),
            ),
        )

    steps: list[dict] = []

    if wants_health:
        steps.append(
            _step(
                "system.health.read",
                "Inspect AI HQ system health",
            )
        )

    if wants_status:
        steps.append(
            _step(
                "service.status.read",
                "Inspect AI HQ service status",
            )
        )

    if wants_logs:
        steps.append(
            _step(
                "service.logs.read",
                "Inspect recent AI HQ service logs",
            )
        )

    if steps:
        return ChatIntent(
            kind="operational",
            steps=tuple(steps),
        )

    return ChatIntent(kind="conversation")
