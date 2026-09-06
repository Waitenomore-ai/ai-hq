from types import MappingProxyType

from ai_hq.recovery.policy import (
    RECOVERY_COMPONENTS,
    RecoveryDecision,
    decide_recovery,
)


HEALTHY_READINESS = {
    "ok": True,
    "database": True,
    "jellyfin": True,
    "radarr": True,
    "sonarr": True,
    "qbittorrent": True,
    "requestSync": True,
    "storage": {
        "available": True,
        "writable": True,
        "belowReserve": False,
    },
}


def readiness_failure(**changes):
    payload = {
        **HEALTHY_READINESS,
        "ok": False,
        "storage": dict(HEALTHY_READINESS["storage"]),
    }
    payload.update(changes)
    return payload


def test_recovery_component_registry_is_fixed_and_immutable():
    assert isinstance(RECOVERY_COMPONENTS, MappingProxyType)
    assert set(RECOVERY_COMPONENTS) == {
        "app",
        "mcp",
        "proxy",
        "tunnel",
        "database",
    }
    assert RECOVERY_COMPONENTS["app"].diagnostic_target == "dripvid-app"
    assert RECOVERY_COMPONENTS["mcp"].diagnostic_target == "dripvid-mcp"
    assert RECOVERY_COMPONENTS["proxy"].diagnostic_target == "dripvid-proxy"
    assert RECOVERY_COMPONENTS["tunnel"].diagnostic_target == "dripvid-tunnel"
    assert RECOVERY_COMPONENTS["database"].diagnostic_target == "dripvid-database"


def test_healthy_readiness_is_resolved_without_mutation():
    decision = decide_recovery(
        component="app",
        service_state="active",
        consecutive_failures=0,
        failure_threshold=3,
        readiness=HEALTHY_READINESS,
    )

    assert decision == RecoveryDecision(
        action="resolved",
        component=None,
        reason="readiness_healthy",
    )


def test_single_failed_observation_is_suspect_not_recoverable():
    decision = decide_recovery(
        component="app",
        service_state="failed",
        consecutive_failures=1,
        failure_threshold=3,
        readiness=readiness_failure(),
    )

    assert decision.action == "observe"
    assert decision.component == "app"
    assert decision.reason == "failure_threshold_not_met"


def test_unknown_component_fails_closed_after_threshold():
    decision = decide_recovery(
        component="made-up-service",
        service_state="failed",
        consecutive_failures=3,
        failure_threshold=3,
        readiness=readiness_failure(),
    )

    assert decision.action == "escalate"
    assert decision.component is None
    assert decision.reason == "unknown_component"


def test_inactive_or_failed_frontend_components_are_recoverable_after_threshold():
    for component in ("app", "mcp", "proxy", "tunnel"):
        for state in ("inactive", "failed"):
            decision = decide_recovery(
                component=component,
                service_state=state,
                consecutive_failures=3,
                failure_threshold=3,
                readiness=readiness_failure(),
            )

            assert decision.action == "recover"
            assert decision.component == component
            assert decision.reason == "service_inactive_or_failed"


def test_active_component_with_readiness_failure_is_diagnosed_not_restarted():
    decision = decide_recovery(
        component="app",
        service_state="active",
        consecutive_failures=3,
        failure_threshold=3,
        readiness=readiness_failure(jellyfin=False),
    )

    assert decision.action == "diagnose"
    assert decision.component == "app"
    assert decision.reason == "service_running_readiness_failed"


def test_database_inactive_or_failed_is_recoverable_after_threshold():
    for state in ("inactive", "failed"):
        decision = decide_recovery(
            component="database",
            service_state=state,
            consecutive_failures=3,
            failure_threshold=3,
            readiness=readiness_failure(database=False),
        )

        assert decision.action == "recover"
        assert decision.component == "database"
        assert decision.reason == "database_service_inactive_or_failed"


def test_running_but_unhealthy_database_is_never_restart_eligible():
    decision = decide_recovery(
        component="database",
        service_state="active",
        consecutive_failures=4,
        failure_threshold=3,
        readiness=readiness_failure(database=False),
    )

    assert decision.action == "escalate"
    assert decision.component == "database"
    assert decision.reason == "database_running_but_unhealthy"


def test_unavailable_storage_always_escalates_without_component_restart():
    readiness = readiness_failure()
    readiness["storage"]["available"] = False

    decision = decide_recovery(
        component="app",
        service_state="failed",
        consecutive_failures=5,
        failure_threshold=3,
        readiness=readiness,
    )

    assert decision.action == "escalate"
    assert decision.component is None
    assert decision.reason == "storage_unavailable"


def test_unwritable_storage_always_escalates_without_component_restart():
    readiness = readiness_failure()
    readiness["storage"]["writable"] = False

    decision = decide_recovery(
        component="proxy",
        service_state="failed",
        consecutive_failures=5,
        failure_threshold=3,
        readiness=readiness,
    )

    assert decision.action == "escalate"
    assert decision.component is None
    assert decision.reason == "storage_unwritable"


def test_low_storage_reserve_is_warning_only_when_otherwise_healthy():
    readiness = {
        **HEALTHY_READINESS,
        "storage": {
            "available": True,
            "writable": True,
            "belowReserve": True,
        },
    }

    decision = decide_recovery(
        component=None,
        service_state=None,
        consecutive_failures=0,
        failure_threshold=3,
        readiness=readiness,
    )

    assert decision.action == "observe"
    assert decision.component is None
    assert decision.reason == "storage_below_reserve"


def test_missing_component_after_threshold_requests_diagnosis_not_guessing():
    decision = decide_recovery(
        component=None,
        service_state=None,
        consecutive_failures=3,
        failure_threshold=3,
        readiness=readiness_failure(),
    )

    assert decision.action == "diagnose"
    assert decision.component is None
    assert decision.reason == "component_not_identified"
