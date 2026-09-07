from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from ai_hq.missions.models import MissionStatus


class QueuedCodeChangeService(Protocol):
    mission_service: Any

    def process_queued_candidate(
        self,
        *,
        mission_id: str,
        lease_owner: str | None = None,
        lease_seconds: int = 900,
    ) -> Any:
        ...


class CodeChangeQueueRunner:
    def __init__(
        self,
        *,
        code_change_service: QueuedCodeChangeService,
        worker_id: str | None = None,
        lease_seconds: int = 900,
    ) -> None:
        self.code_change_service = (
            code_change_service
        )

        self.worker_id = (
            worker_id
            or f"code-change-{uuid4()}"
        )

        self.lease_seconds = lease_seconds

    def run_once(self):
        missions = (
            self.code_change_service
            .mission_service
        )

        claim = getattr(
            missions,
            "claim_oldest_code_change",
            None,
        )

        if callable(claim):
            mission = claim(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )

            if mission is None:
                return None

            return (
                self.code_change_service
                .process_queued_candidate(
                    mission_id=mission.id,
                    lease_owner=self.worker_id,
                    lease_seconds=(
                        self.lease_seconds
                    ),
                )
            )

        # Compatibility for lightweight test doubles.
        # Real MissionService always uses atomic claims.
        for mission in missions.list_missions():
            if (
                mission.status
                is not MissionStatus.QUEUED
            ):
                continue

            if (
                mission.source
                != "hq_chat_code_change"
            ):
                continue

            if mission.owner_agent != "developer":
                continue

            return (
                self.code_change_service
                .process_queued_candidate(
                    mission_id=mission.id
                )
            )

        return None
