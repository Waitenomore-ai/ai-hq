from __future__ import annotations

from typing import Any

from ai_hq.delivery.models import Delivery
from ai_hq.delivery.service import DeliveryService


class DeliveryRuntime:
    """
    Safe orchestration boundary between the mission runtime and the
    persisted Developer -> QA -> human approval workflow.

    This coordinator persists delivery state only. It has no deployment,
    host, shell, Docker, service-management, or production mutation
    authority.
    """

    def __init__(self, delivery_service: DeliveryService) -> None:
        self.delivery_service = delivery_service

    def handoff_to_developer(
        self,
        *,
        mission_id: str,
        change_ref: str,
        summary: str,
        changed_files: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> Delivery:
        """
        Persist an immutable Developer proposal and hand it to QA.

        The change reference and Developer evidence are explicit inputs.
        No code execution or deployment occurs here.
        """
        change_ref = change_ref.strip()
        summary = summary.strip()

        if not change_ref:
            raise ValueError("change_ref is required")

        if not summary:
            raise ValueError("summary is required")

        if not evidence:
            raise ValueError("developer evidence is required")

        return self.delivery_service.submit_developer_proposal(
            mission_id=mission_id,
            change_ref=change_ref,
            summary=summary,
            changed_files=list(changed_files or []),
            evidence=dict(evidence),
        )
