import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from ai_hq.approvals.models import ApprovalRequest, ApprovalState, ScopedApprovalRule
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import SessionFactory


def canonical_action_fingerprint(action: str, target: str, action_plan: dict) -> str:
    payload = json.dumps(
        {"action": action, "target": target, "action_plan": action_plan},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ApprovalService:
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def create_request(
        self,
        *,
        mission_id: str,
        requester_agent: str,
        action: str,
        target: str,
        risk: MissionRisk | str,
        action_plan: dict,
        expires_at: datetime,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            mission_id=mission_id,
            requester_agent=requester_agent,
            action=action,
            target=target,
            risk=MissionRisk(risk),
            action_plan=action_plan,
            action_fingerprint=canonical_action_fingerprint(action, target, action_plan),
            expires_at=expires_at,
        )
        with self.session_factory() as db:
            db.add(request)
            db.commit()
            db.refresh(request)
            return request

    def get_request(self, request_id: str) -> ApprovalRequest:
        with self.session_factory() as db:
            request = db.get(ApprovalRequest, request_id)
            if request is None:
                raise KeyError(f"approval request not found: {request_id}")
            return request

    def list_requests(self, *, mission_id: str | None = None) -> list[ApprovalRequest]:
        statement = select(ApprovalRequest)
        if mission_id is not None:
            statement = statement.where(ApprovalRequest.mission_id == mission_id)
        statement = statement.order_by(ApprovalRequest.created_at, ApprovalRequest.id)
        with self.session_factory() as db:
            return list(db.scalars(statement))

    def pending_for_fingerprint(
        self,
        mission_id: str,
        action_fingerprint: str,
    ) -> ApprovalRequest | None:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            requests = db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.mission_id == mission_id,
                    ApprovalRequest.action_fingerprint == action_fingerprint,
                    ApprovalRequest.state == ApprovalState.PENDING,
                )
            ).all()
            for request in requests:
                if _utc(request.expires_at) > now:
                    return request
            return None

    def decide(self, request_id: str, state: ApprovalState | str) -> ApprovalRequest:
        decision = ApprovalState(state)
        if decision is ApprovalState.PENDING:
            raise ValueError("approval decision cannot return to pending")
        with self.session_factory() as db:
            request = db.get(ApprovalRequest, request_id)
            if request is None:
                raise KeyError(f"approval request not found: {request_id}")
            if request.state is not ApprovalState.PENDING:
                raise ValueError("approval request already decided")
            request.state = decision
            request.decided_at = datetime.now(UTC)
            db.commit()
            db.refresh(request)
            return request

    def is_approved(self, mission_id: str, action_fingerprint: str) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            requests = db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.mission_id == mission_id,
                    ApprovalRequest.action_fingerprint == action_fingerprint,
                    ApprovalRequest.state == ApprovalState.APPROVED,
                )
            ).all()
            return any(_utc(request.expires_at) > now for request in requests)

    def create_scoped_rule(
        self,
        *,
        action: str,
        target: str,
        risk: MissionRisk | str,
        conditions: dict,
        expires_at: datetime,
        max_execution_count: int | None = None,
    ) -> ScopedApprovalRule:
        rule = ScopedApprovalRule(
            action=action,
            target=target,
            risk=MissionRisk(risk),
            conditions=conditions,
            expires_at=expires_at,
            max_execution_count=max_execution_count,
        )
        with self.session_factory() as db:
            db.add(rule)
            db.commit()
            db.refresh(rule)
            return rule

    def matching_scoped_rule(
        self,
        *,
        action: str,
        target: str,
        risk: MissionRisk | str,
        conditions: dict,
    ) -> ScopedApprovalRule | None:
        requested_risk = MissionRisk(risk)
        if requested_risk is MissionRisk.RED:
            return None
        now = datetime.now(UTC)
        with self.session_factory() as db:
            rules = db.scalars(
                select(ScopedApprovalRule).where(
                    ScopedApprovalRule.action == action,
                    ScopedApprovalRule.target == target,
                    ScopedApprovalRule.risk == requested_risk,
                )
            ).all()
            for rule in rules:
                if rule.conditions != conditions or _utc(rule.expires_at) <= now:
                    continue
                if (
                    rule.max_execution_count is not None
                    and rule.execution_count >= rule.max_execution_count
                ):
                    continue
                return rule
            return None

    def consume_rule(self, rule_id: str) -> ScopedApprovalRule:
        with self.session_factory() as db:
            rule = db.get(ScopedApprovalRule, rule_id)
            if rule is None:
                raise KeyError(f"scoped approval rule not found: {rule_id}")
            if rule.risk is MissionRisk.RED:
                raise ValueError("red actions cannot be authorized by scoped rules")
            if _utc(rule.expires_at) <= datetime.now(UTC):
                raise ValueError("scoped approval rule expired")
            if rule.max_execution_count is not None and rule.execution_count >= rule.max_execution_count:
                raise ValueError("scoped approval rule execution limit reached")
            rule.execution_count += 1
            db.commit()
            db.refresh(rule)
            return rule
