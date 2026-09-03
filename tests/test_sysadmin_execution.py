from ai_hq.departments.sysadmin import SysAdminService

from ai_hq.departments.commander import RoutedAction
from ai_hq.host_helper.client import HostHelperError
from ai_hq.host_helper.contracts import HelperResponse, HostAllowLists, HostCapability
from ai_hq.ledger.models import LedgerEventType
from ai_hq.missions.models import MissionRisk, MissionStatus
from ai_hq.safety.policy import Decision
from ai_hq.safety.service import SafetyResult

ALLOW_LISTS = HostAllowLists(
    services=frozenset({"ai-hq", "nginx", "dripvid"}),
    containers=frozenset({"ai-hq-web", "ai-hq-worker", "dripvid"}),
    logs=frozenset({"ai-hq", "nginx", "dripvid"}),
)


class FakeSafety:
    def __init__(self, decision: Decision, events: list[str] | None = None):
        self.decision = decision
        self.events = events if events is not None else []
        self.calls: list[dict] = []

    def evaluate(self, **kwargs):
        self.events.append("safety")
        self.calls.append(kwargs)
        return SafetyResult(
            decision=self.decision,
            mission_status=MissionStatus.RUNNING,
            action_fingerprint="fingerprint",
        )


class FakeHelper:
    def __init__(self, response=None, error: HostHelperError | None = None, events=None):
        self.response = response
        self.error = error
        self.events = events if events is not None else []
        self.calls = []
        self.credential = "super-secret-helper-credential"

    def execute(self, request):
        self.events.append("helper")
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class FakeLedger:
    def __init__(self):
        self.records: list[dict] = []

    def record(self, **kwargs):
        self.records.append(kwargs)
        return kwargs


def action(
    capability: HostCapability = HostCapability.SERVICE_STATUS,
    target: str | None = "nginx",
    params: dict[str, object] | None = None,
) -> RoutedAction:
    return RoutedAction(
        owner_agent="sysadmin",
        capability=capability,
        target=target,
        params=params or {},
        risk=MissionRisk.GREEN,
    )


def make_service(safety, helper, ledger):
    return SysAdminService(
        safety=safety,
        helper=helper,
        ledger=ledger,
        allow_lists=ALLOW_LISTS,
    )


def test_allow_evaluates_safety_before_invoking_helper():
    events: list[str] = []
    safety = FakeSafety(Decision.ALLOW, events)
    helper = FakeHelper(
        HelperResponse(True, HostCapability.SERVICE_STATUS, "nginx", {"active_state": "active"}),
        events=events,
    )
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(mission_id="mission-1", action=action())

    assert events[:2] == ["safety", "helper"]
    assert safety.calls[0]["mutates_external_state"] is False
    assert safety.calls[0]["agent_key"] == "sysadmin"
    assert helper.calls[0].capability is HostCapability.SERVICE_STATUS
    assert result.status is MissionStatus.COMPLETED
    assert result.simulated is False
    assert result.data == {"active_state": "active"}


def test_simulation_decision_never_invokes_helper_and_records_simulation():
    safety = FakeSafety(Decision.SIMULATE_ONLY)
    helper = FakeHelper()
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(mission_id="mission-2", action=action())

    assert helper.calls == []
    assert result.status is MissionStatus.COMPLETED
    assert result.simulated is True
    assert any(
        record["event_type"] is LedgerEventType.RESULT_RECORDED
        and record["metadata"]["simulated"] is True
        for record in ledger.records
    )


def test_block_decision_fails_closed_without_helper_execution():
    safety = FakeSafety(Decision.BLOCK)
    helper = FakeHelper()
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(mission_id="mission-3", action=action())

    assert helper.calls == []
    assert result.status is MissionStatus.FAILED
    assert result.error == "blocked"


def test_forged_invalid_target_is_revalidated_before_safety_or_helper():
    safety = FakeSafety(Decision.ALLOW)
    helper = FakeHelper()
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(
        mission_id="mission-4",
        action=action(target="not-allowed"),
    )

    assert safety.calls == []
    assert helper.calls == []
    assert result.status is MissionStatus.FAILED
    assert result.error == "invalid_action"


def test_helper_failure_returns_bounded_failure_and_records_result():
    safety = FakeSafety(Decision.ALLOW)
    helper = FakeHelper(
        HelperResponse(False, HostCapability.SERVICE_STATUS, "nginx", {}, "timeout")
    )
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(mission_id="mission-5", action=action())

    assert result.status is MissionStatus.FAILED
    assert result.error == "timeout"
    failure = next(
        record for record in ledger.records if record["event_type"] is LedgerEventType.RESULT_RECORDED
    )
    assert failure["metadata"]["error"] == "timeout"
    assert len(str(failure["metadata"])) < 1024


def test_transport_failure_does_not_persist_helper_credential():
    safety = FakeSafety(Decision.ALLOW)
    helper = FakeHelper(error=HostHelperError("connection_failed"))
    ledger = FakeLedger()

    result = make_service(safety, helper, ledger).execute(mission_id="mission-6", action=action())

    assert result.status is MissionStatus.FAILED
    assert result.error == "connection_failed"
    assert helper.credential not in repr(ledger.records)
