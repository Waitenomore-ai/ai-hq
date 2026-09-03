from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai_hq.approvals.service import ApprovalService, canonical_action_fingerprint
from ai_hq.config import OperatingMode
from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import MissionRisk, MissionStatus
from ai_hq.missions.service import SessionFactory
from ai_hq.models.system_state import SystemState
from ai_hq.safety.policy import ActionIntent, Decision, evaluate_action


@dataclass(frozen=True, slots=True)
class SafetyResult:
    decision: Decision
    mission_status: MissionStatus
    action_fingerprint: str
    approval_request_id: str | None = None
    scoped_rule_id: str | None = None


class SafetyService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        ledger: OperationsLedger | None = None,
        approval_lifetime: timedelta = timedelta(hours=1),
    ):
        self.session_factory = session_factory
        self.ledger = ledger or OperationsLedger(session_factory)
        self.approvals = ApprovalService(session_factory)
        self.approval_lifetime = approval_lifetime

    def _system_state(self) -> tuple[OperatingMode, bool, bool]:
        with self.session_factory() as db:
            state = db.get(SystemState, 1)
            if state is None:
                return OperatingMode.FREEZE, True, False
            try:
                mode = OperatingMode(state.operating_mode)
            except ValueError:
                return OperatingMode.FREEZE, True, False
            return mode, state.simulation_mode, True

    def evaluate(
        self,
        *,
        mission_id: str,
        agent_key: str,
        action: str,
        target: str,
        risk: MissionRisk | str,
        action_plan: dict,
        conditions: dict,
        mutates_external_state: bool,
        authorization_available: bool = True,
    ) -> SafetyResult:
        requested_risk = MissionRisk(risk)
        fingerprint = canonical_action_fingerprint(action, target, action_plan)

        self.ledger.record(
            mission_id=mission_id,
            agent_key=agent_key,
            event_type=LedgerEventType.ACTION_PROPOSED,
            summary=f"Action proposed: {action}",
            metadata={
                "action": action,
                "target": target,
                "risk": requested_risk.value,
                "fingerprint": fingerprint,
                "mutates_external_state": mutates_external_state,
            },
        )

        mode, simulation_mode, state_available = self._system_state()
        approved = self.approvals.is_approved(mission_id, fingerprint)
        scoped_rule = self.approvals.matching_scoped_rule(
            action=action,
            target=target,
            risk=requested_risk,
            conditions=conditions,
        )
        permission_available = authorization_available and state_available

        self.ledger.record(
            mission_id=mission_id,
            agent_key=agent_key,
            event_type=LedgerEventType.PERMISSION_CHECKED,
            summary="Permission context checked",
            metadata={
                "authorization_available": permission_available,
                "approved": approved,
                "scoped_rule_id": scoped_rule.id if scoped_rule else None,
            },
        )

        intent = ActionIntent(
            action=action,
            target=target,
            risk=requested_risk,
            mutates_external_state=mutates_external_state,
            scoped_rule_allows=(scoped_rule is not None or approved),
            approved=approved,
            authorization_available=permission_available,
        )
        decision = evaluate_action(intent, mode, simulation_mode=simulation_mode)

        self.ledger.record(
            mission_id=mission_id,
            agent_key=agent_key,
            event_type=LedgerEventType.RISK_CHECKED,
            summary=f"Safety decision: {decision.value}",
            metadata={
                "risk": requested_risk.value,
                "operating_mode": mode.value,
                "simulation_mode": simulation_mode,
                "decision": decision.value,
            },
        )

        if decision is not Decision.REQUIRE_APPROVAL:
            return SafetyResult(
                decision=decision,
                mission_status=MissionStatus.RUNNING,
                action_fingerprint=fingerprint,
                scoped_rule_id=scoped_rule.id if scoped_rule else None,
            )

        pending = self.approvals.pending_for_fingerprint(mission_id, fingerprint)
        if pending is None:
            pending = self.approvals.create_request(
                mission_id=mission_id,
                requester_agent=agent_key,
                action=action,
                target=target,
                risk=requested_risk,
                action_plan=action_plan,
                expires_at=datetime.now(UTC) + self.approval_lifetime,
            )
            self.ledger.record(
                mission_id=mission_id,
                agent_key=agent_key,
                event_type=LedgerEventType.APPROVAL_RECORDED,
                summary="Approval requested",
                metadata={
                    "approval_request_id": pending.id,
                    "state": pending.state.value,
                    "fingerprint": fingerprint,
                },
            )

        return SafetyResult(
            decision=decision,
            mission_status=MissionStatus.WAITING_APPROVAL,
            action_fingerprint=fingerprint,
            approval_request_id=pending.id,
            scoped_rule_id=scoped_rule.id if scoped_rule else None,
        )
