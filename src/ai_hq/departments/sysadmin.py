from dataclasses import dataclass

from ai_hq.departments.commander import RoutedAction
from ai_hq.host_helper.client import HostHelperClient, HostHelperError
from ai_hq.host_helper.contracts import HostAllowLists, validate_request
from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import MissionStatus
from ai_hq.safety.policy import Decision
from ai_hq.safety.service import SafetyService


@dataclass(frozen=True, slots=True)
class SysAdminExecutionResult:
    status: MissionStatus
    simulated: bool
    data: dict[str, object]
    error: str | None


class SysAdminService:
    def __init__(
        self,
        *,
        safety: SafetyService,
        helper: HostHelperClient,
        ledger: OperationsLedger,
        allow_lists: HostAllowLists,
    ):
        self.safety = safety
        self.helper = helper
        self.ledger = ledger
        self.allow_lists = allow_lists

    def _record_result(
        self,
        *,
        mission_id: str,
        action: RoutedAction,
        status: MissionStatus,
        simulated: bool,
        error: str | None,
    ) -> None:
        self.ledger.record(
            mission_id=mission_id,
            agent_key="sysadmin",
            event_type=LedgerEventType.RESULT_RECORDED,
            summary=f"SysAdmin result: {status.value}",
            metadata={
                "capability": action.capability.value,
                "target": action.target,
                "status": status.value,
                "simulated": simulated,
                "error": error,
            },
        )

    def _failure(
        self,
        *,
        mission_id: str,
        action: RoutedAction,
        error: str,
    ) -> SysAdminExecutionResult:
        self._record_result(
            mission_id=mission_id,
            action=action,
            status=MissionStatus.FAILED,
            simulated=False,
            error=error,
        )
        return SysAdminExecutionResult(MissionStatus.FAILED, False, {}, error)

    def execute(self, *, mission_id: str, action: RoutedAction) -> SysAdminExecutionResult:
        try:
            request = validate_request(
                {
                    "capability": action.capability.value,
                    "target": action.target,
                    "params": action.params,
                },
                self.allow_lists,
            )
        except (AttributeError, TypeError, ValueError):
            return self._failure(mission_id=mission_id, action=action, error="invalid_action")

        target = request.target or "host"
        safety_result = self.safety.evaluate(
            mission_id=mission_id,
            agent_key="sysadmin",
            action=request.capability.value,
            target=target,
            risk=action.risk,
            action_plan={
                "capability": request.capability.value,
                "target": request.target,
                "params": request.params,
            },
            conditions={},
            mutates_external_state=False,
        )

        if safety_result.decision is Decision.REQUIRE_APPROVAL:
            return SysAdminExecutionResult(MissionStatus.WAITING_APPROVAL, False, {}, None)
        if safety_result.decision is Decision.BLOCK:
            return self._failure(mission_id=mission_id, action=action, error="blocked")
        if safety_result.decision is Decision.SIMULATE_ONLY:
            self._record_result(
                mission_id=mission_id,
                action=action,
                status=MissionStatus.COMPLETED,
                simulated=True,
                error=None,
            )
            return SysAdminExecutionResult(MissionStatus.COMPLETED, True, {}, None)
        if safety_result.decision is not Decision.ALLOW:
            return self._failure(mission_id=mission_id, action=action, error="blocked")

        try:
            response = self.helper.execute(request)
        except HostHelperError as exc:
            error = str(exc)[:128] or "helper_failed"
            return self._failure(mission_id=mission_id, action=action, error=error)

        self.ledger.record(
            mission_id=mission_id,
            agent_key="sysadmin",
            event_type=LedgerEventType.TOOL_EXECUTED,
            summary=f"Host helper executed: {request.capability.value}",
            metadata={
                "capability": request.capability.value,
                "target": request.target,
                "ok": response.ok,
            },
        )

        if not response.ok:
            error = (response.error or "helper_failed")[:128]
            return self._failure(mission_id=mission_id, action=action, error=error)

        self._record_result(
            mission_id=mission_id,
            action=action,
            status=MissionStatus.COMPLETED,
            simulated=False,
            error=None,
        )
        return SysAdminExecutionResult(MissionStatus.COMPLETED, False, response.data, None)
