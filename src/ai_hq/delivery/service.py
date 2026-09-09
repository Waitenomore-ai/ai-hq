from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import re

from sqlalchemy.orm import Session

from ai_hq.approvals.models import ApprovalState
from ai_hq.approvals.service import ApprovalService
from ai_hq.delivery.models import Delivery, DeliveryStage, QAResult
from ai_hq.missions.models import Mission, MissionStatus


SessionFactory = Callable[[], Session]
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PUBLISH_BRANCH_PREFIX = "ai-hq/candidate/"
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _approval_expired(expires_at: datetime) -> bool:
    boundary = expires_at
    if boundary.tzinfo is None:
        boundary = boundary.replace(tzinfo=UTC)
    return boundary <= datetime.now(UTC)


def _release_id_valid(release_id: str) -> bool:
    if len(release_id) > 128:
        return False
    if not release_id.isascii():
        return False
    return _RELEASE_ID_RE.fullmatch(release_id) is not None


class DeliveryService:
    """
    Persisted handoff boundary:

        Developer -> QA -> Human Approval

    This service does not deploy, execute shell commands, restart services,
    mutate Docker, or grant agents production authority.
    """

    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def get_delivery(self, mission_id: str) -> Delivery:
        with self.session_factory() as db:
            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )

            if delivery is None:
                raise KeyError(
                    f"delivery not found for mission: {mission_id}"
                )

            return delivery

    def submit_developer_proposal(
        self,
        *,
        mission_id: str,
        change_ref: str,
        summary: str,
        changed_files: list,
        evidence: dict,
    ) -> Delivery:
        if not change_ref.strip():
            raise ValueError("change_ref is required")

        if not summary.strip():
            raise ValueError("summary is required")

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)

            if mission is None:
                raise KeyError(
                    f"mission not found: {mission_id}"
                )

            existing = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )

            if existing is not None:
                raise ValueError(
                    "mission already has a developer proposal"
                )

            if mission.status is MissionStatus.QUEUED:
                mission.status = MissionStatus.RUNNING

            if mission.status is not MissionStatus.RUNNING:
                raise ValueError(
                    "mission must be QUEUED or RUNNING "
                    "for developer submission"
                )

            delivery = Delivery(
                mission_id=mission_id,
                stage=DeliveryStage.QA,
                change_ref=change_ref,
                summary=summary,
                changed_files=list(changed_files),
                developer_evidence=dict(evidence),
            )

            db.add(delivery)
            db.commit()
            db.refresh(delivery)

            return delivery

    def record_qa_result(
        self,
        *,
        mission_id: str,
        change_ref: str,
        result: QAResult | str,
        evidence: dict,
    ) -> Delivery:
        qa_result = QAResult(result)

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)

            if mission is None:
                raise KeyError(
                    f"mission not found: {mission_id}"
                )

            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )

            if delivery is None:
                raise KeyError(
                    f"delivery not found for mission: {mission_id}"
                )

            if delivery.stage is not DeliveryStage.QA:
                raise ValueError(
                    "delivery is not awaiting QA"
                )

            if delivery.change_ref != change_ref:
                raise ValueError(
                    "change_ref does not match developer proposal"
                )

            delivery.qa_result = qa_result
            delivery.qa_evidence = dict(evidence)

            if qa_result is QAResult.FAILED:
                delivery.stage = DeliveryStage.DEVELOPER
                delivery.approval_reference = None

            elif qa_result is QAResult.PASSED:
                if mission.status is not MissionStatus.RUNNING:
                    raise ValueError(
                        "mission must be RUNNING before approval"
                    )

                approval = ApprovalService(self.session_factory).create_request(
                    mission_id=mission.id,
                    requester_agent="qa",
                    action="approve_delivery_change",
                    target=delivery.change_ref,
                    risk=mission.risk,
                    action_plan={
                        "change_ref": delivery.change_ref,
                        "summary": delivery.summary,
                        "changed_files": list(delivery.changed_files or []),
                        "developer_evidence": dict(
                            delivery.developer_evidence or {}
                        ),
                        "qa_evidence": dict(delivery.qa_evidence or {}),
                    },
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                )

                delivery.stage = DeliveryStage.WAITING_APPROVAL
                delivery.approval_reference = approval.id
                mission.status = MissionStatus.WAITING_APPROVAL

                refs = list(mission.approval_references or [])
                refs.append(
                    {
                        "approval_reference": delivery.approval_reference,
                        "change_ref": delivery.change_ref,
                    }
                )
                mission.approval_references = refs

            db.commit()
            db.refresh(delivery)

            return delivery

    def record_publication(
        self,
        *,
        mission_id: str,
        change_ref: str,
        branch_name: str,
        commit_sha: str,
        tree_sha: str,
    ) -> Delivery:
        if not isinstance(branch_name, str) or not branch_name.startswith(
            _PUBLISH_BRANCH_PREFIX
        ):
            raise ValueError("publication branch must use generated candidate namespace")
        if not isinstance(commit_sha, str) or not _GIT_SHA_RE.fullmatch(commit_sha):
            raise ValueError("publication commit must be a Git SHA")
        if not isinstance(tree_sha, str) or not _GIT_SHA_RE.fullmatch(tree_sha):
            raise ValueError("publication tree must be a Git SHA")

        approvals = ApprovalService(self.session_factory)

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )
            if delivery is None:
                raise KeyError(f"delivery not found for mission: {mission_id}")

            if delivery.change_ref != change_ref:
                raise ValueError("change_ref does not match publication candidate")
            if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
                raise ValueError("delivery is not waiting for publication approval")
            if delivery.qa_result is not QAResult.PASSED:
                raise ValueError("QA must pass before publication")
            if not delivery.approval_reference:
                raise ValueError("publication requires human approval")

            approval = approvals.get_request(delivery.approval_reference)
            if approval.mission_id != mission_id:
                raise ValueError("approval mission does not match publication")
            if approval.target != change_ref:
                raise ValueError("approval target does not match change_ref")
            if (approval.action_plan or {}).get("change_ref") != change_ref:
                raise ValueError("approval action plan does not match change_ref")
            if _approval_expired(approval.expires_at):
                raise ValueError("publication approval expired")
            if approval.state is not ApprovalState.APPROVED:
                raise ValueError("publication requires approved human approval")

            existing = (
                delivery.published_branch,
                delivery.published_commit,
                delivery.published_tree,
            )
            requested = (branch_name, commit_sha, tree_sha)
            if any(value is not None for value in existing):
                if existing != requested or delivery.published_at is None:
                    raise ValueError("publication identity does not match persisted publication")
                return delivery

            delivery.published_branch = branch_name
            delivery.published_commit = commit_sha
            delivery.published_tree = tree_sha
            delivery.published_at = datetime.now(UTC)

            db.commit()
            db.refresh(delivery)
            return delivery

    def record_deployment(
        self,
        *,
        mission_id: str,
        change_ref: str,
        release_id: str,
        prior_release_id: str | None = None,
    ) -> Delivery:
        if not isinstance(release_id, str) or not _release_id_valid(release_id):
            raise ValueError("release id must use the trusted release identity charset")
        if (
            prior_release_id is not None
            and not _release_id_valid(prior_release_id)
        ):
            raise ValueError(
                "prior release id must use the trusted release identity charset"
            )

        approvals = ApprovalService(self.session_factory)

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )
            if delivery is None:
                raise KeyError(f"delivery not found for mission: {mission_id}")

            if delivery.change_ref != change_ref:
                raise ValueError("change_ref does not match deployment candidate")
            if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
                raise ValueError("delivery is not waiting for deployment approval")
            if delivery.qa_result is not QAResult.PASSED:
                raise ValueError("QA must pass before deployment")
            if not delivery.approval_reference:
                raise ValueError("deployment requires human approval")
            if not (
                delivery.published_branch
                and delivery.published_commit
                and delivery.published_tree
            ):
                raise ValueError("candidate must be published before deployment")

            approval = approvals.get_request(delivery.approval_reference)
            if approval.mission_id != mission_id:
                raise ValueError("approval mission does not match deployment")
            if approval.target != change_ref:
                raise ValueError("approval target does not match change_ref")
            if (approval.action_plan or {}).get("change_ref") != change_ref:
                raise ValueError("approval action plan does not match change_ref")
            if _approval_expired(approval.expires_at):
                raise ValueError("deployment approval expired")
            if approval.state is not ApprovalState.APPROVED:
                raise ValueError("deployment requires approved human approval")

            existing = (
                delivery.deployment_release_id,
                delivery.deployment_prior_release_id,
            )
            requested = (release_id, prior_release_id)
            if existing[0] is not None or existing[1] is not None:
                if existing != requested or delivery.deployed_at is None:
                    raise ValueError("deployment identity does not match persisted deployment")
                return delivery

            delivery.deployment_release_id = release_id
            delivery.deployment_prior_release_id = prior_release_id
            delivery.deployed_at = datetime.now(UTC)

            db.commit()
            db.refresh(delivery)
            return delivery

    def record_rollback(
        self,
        *,
        mission_id: str,
        change_ref: str,
        release_id: str,
    ) -> Delivery:
        """Persist an approved rollback restoring the prior known-good release.

        The restored release must equal the persisted deployment history's
        ``deployment_prior_release_id``. The caller never selects it from
        model output or arbitrary input; it is derived from trusted history.
        """
        if not isinstance(release_id, str) or not _release_id_valid(release_id):
            raise ValueError("release id must use the trusted release identity charset")

        approvals = ApprovalService(self.session_factory)

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )
            if delivery is None:
                raise KeyError(f"delivery not found for mission: {mission_id}")

            if delivery.change_ref != change_ref:
                raise ValueError("change_ref does not match rollback candidate")
            if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
                raise ValueError("delivery is not waiting for rollback approval")
            if delivery.qa_result is not QAResult.PASSED:
                raise ValueError("QA must pass before rollback")
            if not delivery.approval_reference:
                raise ValueError("rollback requires human approval")
            if not (
                delivery.published_branch
                and delivery.published_commit
                and delivery.published_tree
            ):
                raise ValueError("candidate must be published before rollback")
            if not delivery.deployment_release_id:
                raise ValueError("candidate must be deployed before rollback")
            if not delivery.deployment_prior_release_id:
                raise ValueError("no prior known-good release is recorded for rollback")
            if delivery.deployment_prior_release_id != release_id:
                raise ValueError(
                    "rollback release must resolve from trusted deployment history",
                )

            approval = approvals.get_request(delivery.approval_reference)
            if approval.mission_id != mission_id:
                raise ValueError("approval mission does not match rollback")
            if approval.target != change_ref:
                raise ValueError("approval target does not match change_ref")
            if (approval.action_plan or {}).get("change_ref") != change_ref:
                raise ValueError("approval action plan does not match change_ref")
            if _approval_expired(approval.expires_at):
                raise ValueError("rollback approval expired")
            if approval.state is not ApprovalState.APPROVED:
                raise ValueError("rollback requires approved human approval")

            if delivery.rollback_release_id is not None or delivery.rolled_back_at is not None:
                if (
                    delivery.rollback_release_id != release_id
                    or delivery.rolled_back_at is None
                ):
                    raise ValueError(
                        "rollback identity does not match persisted rollback"
                    )
                return delivery

            delivery.rollback_release_id = release_id
            delivery.rolled_back_at = datetime.now(UTC)

            db.commit()
            db.refresh(delivery)
            return delivery

    def apply_human_decision(
        self,
        *,
        mission_id: str,
        approval_reference: str,
        change_ref: str,
    ) -> Delivery:
        """
        Apply an already-persisted human decision to the exact QA-passed
        delivery proposal.

        Approval is authorization only. This method does not deploy,
        execute shell commands, restart services, mutate Docker, or
        otherwise change production.
        """
        approvals = ApprovalService(self.session_factory)

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)

            if mission is None:
                raise KeyError(
                    f"mission not found: {mission_id}"
                )

            delivery = (
                db.query(Delivery)
                .filter(Delivery.mission_id == mission_id)
                .one_or_none()
            )

            if delivery is None:
                raise KeyError(
                    f"delivery not found for mission: {mission_id}"
                )

            if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
                raise ValueError(
                    "delivery is not waiting for human approval"
                )

            if delivery.approval_reference != approval_reference:
                raise ValueError(
                    "approval reference does not match delivery"
                )

            if delivery.change_ref != change_ref:
                raise ValueError(
                    "change_ref does not match approved proposal"
                )

            approval = approvals.get_request(approval_reference)

            if approval.mission_id != mission_id:
                raise ValueError(
                    "approval mission does not match delivery"
                )

            if approval.target != delivery.change_ref:
                raise ValueError(
                    "approval target does not match change_ref"
                )

            approval_change_ref = (
                approval.action_plan or {}
            ).get("change_ref")

            if approval_change_ref != delivery.change_ref:
                raise ValueError(
                    "approval action plan does not match change_ref"
                )

            if _approval_expired(approval.expires_at):
                raise ValueError("approval request expired")

            if approval.state is ApprovalState.PENDING:
                raise ValueError(
                    "approval request has not been decided"
                )

            if approval.state is ApprovalState.APPROVED:
                return delivery

            if approval.state in {
                ApprovalState.DENIED,
                ApprovalState.CANCELLED,
            }:
                delivery.stage = DeliveryStage.DEVELOPER
                delivery.approval_reference = None
                mission.status = MissionStatus.RUNNING

                db.commit()
                db.refresh(delivery)

                return delivery

            raise ValueError(
                f"unsupported approval state: {approval.state}"
            )
