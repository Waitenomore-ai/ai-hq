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
    repository: str | None = None


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


CODE_CHANGE_ACTIONS = (
    "make",
    "change",
    "edit",
    "fix",
    "update",
    "adjust",
    "resize",
    "redesign",
    "add",
    "remove",
)

CODE_CHANGE_OBJECTS = (
    "ui",
    "toolbar",
    "menu",
    "sidebar",
    "dashboard",
    "layout",
    "spacing",
    "button",
    "page",
    "css",
    "style",
    "template",
    "component",
    "code",
    "bug",
)

AI_HQ_TARGET_WORDS = (
    "ai hq",
    "ai-hq",
    " hq ",
    "hq dashboard",
    "hq sidebar",
    "hq ui",
)

DRIPVID_TARGET_WORDS = (
    "dripvid",
    "drip vid",
)


def _looks_like_code_change(text: str) -> bool:
    has_action = _contains_any(text, CODE_CHANGE_ACTIONS)
    has_object = _contains_any(text, CODE_CHANGE_OBJECTS)
    return has_action and has_object


def _resolve_code_change_repository(text: str) -> str | None:
    padded = f" {text} "

    wants_ai_hq = _contains_any(
        padded,
        AI_HQ_TARGET_WORDS,
    )
    wants_dripvid = _contains_any(
        padded,
        DRIPVID_TARGET_WORDS,
    )

    if wants_ai_hq and wants_dripvid:
        return "ambiguous"

    if wants_ai_hq:
        return "ai-hq"

    if wants_dripvid:
        return "dripvid"

    return None


def plan_sysadmin_intent(text: str) -> ChatIntent:
    normalized = " ".join(text.lower().split())

    if _looks_like_code_change(normalized):
        repository = _resolve_code_change_repository(normalized)

        if repository == "ambiguous":
            return ChatIntent(
                kind="refused",
                refusal_reason=(
                    "Code-change requests must target exactly one trusted "
                    "repository: ai-hq or dripvid."
                ),
            )

        if repository is None:
            return ChatIntent(
                kind="refused",
                refusal_reason=(
                    "Code-change request requires a trusted repository "
                    "target: ai-hq or dripvid."
                ),
            )

        return ChatIntent(
            kind="code_change",
            repository=repository,
        )

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
            "ai hq logs",
            "ai-hq logs",
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
            "status of ai hq services",
            "status of ai-hq services",
            "ai hq services status",
            "ai-hq services status",
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
            "health of ai hq",
            "ai hq health",
            "ai-hq health",
            "health of ai-hq",
        ),
    )

    general_server_check = (
        _contains_any(
            normalized,
            (
                "is anything wrong with ai hq",
                "is anything wrong with ai-hq",
                "check everything in ai hq",
                "check everything in ai-hq",
                "is ai hq okay",
                "is ai-hq okay",
                "is ai hq ok",
                "is ai-hq ok",
                "investigate ai hq",
                "investigate ai-hq",
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
