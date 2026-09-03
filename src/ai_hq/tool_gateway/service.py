from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_hq.agents.models import Agent
from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.safety.policy import Decision
from ai_hq.safety.service import SafetyService
from ai_hq.tool_gateway.contracts import (
    ToolAdapterError,
    ToolOutcome,
    ToolOutcomeState,
    ToolRequest,
)
from ai_hq.tool_gateway.registry import ToolRegistry

SessionFactory = Callable[[], Session]


class ToolGateway:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        registry: ToolRegistry,
        safety: SafetyService | None = None,
        ledger: OperationsLedger | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.ledger = ledger or OperationsLedger(session_factory)
        self.safety = safety or SafetyService(session_factory, ledger=self.ledger)

    def execute(self, request: ToolRequest) -> ToolOutcome:
        adapter = self.registry.resolve(request.capability)
        if adapter is None:
            return ToolOutcome(
                state=ToolOutcomeState.BLOCKED,
                capability=request.capability,
                reason="adapter_unavailable",
            )

        authorized = self._has_exact_permission(request.agent_key, request.capability)
        safety = self.safety.evaluate(
            mission_id=request.mission_id,
            agent_key=request.agent_key,
            action=request.capability,
            target=request.target,
            risk=request.risk,
            action_plan={
                "capability": request.capability,
                "target": request.target,
                "params": request.params,
            },
            conditions=request.conditions,
            mutates_external_state=request.mutates_external_state,
            authorization_available=authorized,
        )

        if safety.decision is Decision.BLOCK:
            return ToolOutcome(
                state=ToolOutcomeState.BLOCKED,
                capability=request.capability,
                reason="permission_denied" if not authorized else "safety_blocked",
            )

        if safety.decision is Decision.REQUIRE_APPROVAL:
            return ToolOutcome(
                state=ToolOutcomeState.WAITING_APPROVAL,
                capability=request.capability,
                reason="approval_required",
                approval_request_id=safety.approval_request_id,
            )

        if safety.decision is Decision.SIMULATE_ONLY:
            self._record_result(request, state=ToolOutcomeState.SIMULATED)
            return ToolOutcome(
                state=ToolOutcomeState.SIMULATED,
                capability=request.capability,
                result={"simulated": True},
            )

        try:
            result = adapter.execute(request)
        except ToolAdapterError:
            self._record_result(request, state=ToolOutcomeState.FAILED)
            return ToolOutcome(
                state=ToolOutcomeState.FAILED,
                capability=request.capability,
                reason="adapter_failed",
            )

        self.ledger.record(
            mission_id=request.mission_id,
            agent_key=request.agent_key,
            event_type=LedgerEventType.TOOL_EXECUTED,
            summary=f"Executed tool capability {request.capability}",
            metadata={
                "capability": request.capability,
                "target": request.target,
            },
        )
        self._record_result(request, state=ToolOutcomeState.EXECUTED)
        return ToolOutcome(
            state=ToolOutcomeState.EXECUTED,
            capability=request.capability,
            result=result,
        )

    def _has_exact_permission(self, agent_key: str, capability: str) -> bool:
        with self.session_factory() as db:
            agent = db.scalar(select(Agent).where(Agent.key == agent_key))
            return bool(agent and capability in (agent.permissions or []))

    def _record_result(self, request: ToolRequest, *, state: ToolOutcomeState) -> None:
        self.ledger.record(
            mission_id=request.mission_id,
            agent_key=request.agent_key,
            event_type=LedgerEventType.RESULT_RECORDED,
            summary=f"Tool capability {request.capability} finished as {state.value}",
            metadata={
                "capability": request.capability,
                "target": request.target,
                "state": state.value,
            },
        )
