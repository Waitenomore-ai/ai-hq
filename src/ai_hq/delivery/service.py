from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from ai_hq.delivery.models import Delivery, DeliveryStage, QAResult
from ai_hq.missions.models import Mission, MissionStatus


SessionFactory = Callable[[], Session]


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

            # Developer work has begun.
            # Preserve the existing Mission transition rules:
            # QUEUED -> RUNNING -> WAITING_APPROVAL.
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

            # Critical immutable boundary:
            # QA may only assess the exact change Developer submitted.
            if delivery.change_ref != change_ref:
                raise ValueError(
                    "change_ref does not match developer proposal"
                )

            delivery.qa_result = qa_result
            delivery.qa_evidence = dict(evidence)

            if qa_result is QAResult.FAILED:
                # Return to Developer.
                # Human approval is never created for failed QA.
                delivery.stage = DeliveryStage.DEVELOPER
                delivery.approval_reference = None

            elif qa_result is QAResult.PASSED:
                if mission.status is not MissionStatus.RUNNING:
                    raise ValueError(
                        "mission must be RUNNING before approval"
                    )

                # Bind approval to this persisted proposal.
                delivery.stage = DeliveryStage.WAITING_APPROVAL
                delivery.approval_reference = str(uuid4())

                # Existing mission state machine destination.
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
