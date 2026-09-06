from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


RecoveryAction = Literal[
    "observe",
    "diagnose",
    "recover",
    "escalate",
    "resolved",
]


@dataclass(frozen=True, slots=True)
class RecoveryComponent:
    key: str
    diagnostic_target: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    component: str | None
    reason: str


RECOVERY_COMPONENTS = MappingProxyType(
    {
        "app": RecoveryComponent(
            "app",
            diagnostic_target="dripvid-app",
        ),
        "mcp": RecoveryComponent(
            "mcp",
            diagnostic_target="dripvid-mcp",
        ),
        "proxy": RecoveryComponent(
            "proxy",
            diagnostic_target="dripvid-proxy",
        ),
        "tunnel": RecoveryComponent(
            "tunnel",
            diagnostic_target="dripvid-tunnel",
        ),
        "database": RecoveryComponent(
            "database",
            diagnostic_target="dripvid-database",
        ),
    }
)


def _storage_decision(readiness: Mapping[str, object]) -> RecoveryDecision | None:
    storage = readiness.get("storage")
    if not isinstance(storage, Mapping):
        return None

    if storage.get("available") is False:
        return RecoveryDecision(
            action="escalate",
            component=None,
            reason="storage_unavailable",
        )

    if storage.get("writable") is False:
        return RecoveryDecision(
            action="escalate",
            component=None,
            reason="storage_unwritable",
        )

    if readiness.get("ok") is True and storage.get("belowReserve") is True:
        return RecoveryDecision(
            action="observe",
            component=None,
            reason="storage_below_reserve",
        )

    return None


def decide_recovery(
    *,
    component: str | None,
    service_state: str | None,
    consecutive_failures: int,
    failure_threshold: int,
    readiness: Mapping[str, object],
) -> RecoveryDecision:
    """Return the deterministic recovery decision for one observation.

    This function never executes a mutation. It only classifies a bounded,
    trusted observation into the next allowed recovery state.
    """
    storage_decision = _storage_decision(readiness)
    if storage_decision is not None:
        return storage_decision

    if readiness.get("ok") is True:
        return RecoveryDecision(
            action="resolved",
            component=None,
            reason="readiness_healthy",
        )

    if consecutive_failures < failure_threshold:
        return RecoveryDecision(
            action="observe",
            component=component,
            reason="failure_threshold_not_met",
        )

    if component is None:
        return RecoveryDecision(
            action="diagnose",
            component=None,
            reason="component_not_identified",
        )

    recovery_component = RECOVERY_COMPONENTS.get(component)
    if recovery_component is None or not recovery_component.recoverable:
        return RecoveryDecision(
            action="escalate",
            component=None,
            reason="unknown_component",
        )

    state = (service_state or "").casefold()
    service_down = state in {"inactive", "failed"}
    service_running = state in {"active", "running"}

    if component == "database":
        if service_down:
            return RecoveryDecision(
                action="recover",
                component="database",
                reason="database_service_inactive_or_failed",
            )

        if service_running and readiness.get("database") is False:
            return RecoveryDecision(
                action="escalate",
                component="database",
                reason="database_running_but_unhealthy",
            )

        return RecoveryDecision(
            action="diagnose",
            component="database",
            reason="database_state_requires_diagnosis",
        )

    if service_down:
        return RecoveryDecision(
            action="recover",
            component=component,
            reason="service_inactive_or_failed",
        )

    if service_running:
        return RecoveryDecision(
            action="diagnose",
            component=component,
            reason="service_running_readiness_failed",
        )

    return RecoveryDecision(
        action="diagnose",
        component=component,
        reason="service_state_uncertain",
    )
