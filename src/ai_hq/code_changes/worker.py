from __future__ import annotations

from typing import Any, Protocol

from ai_hq.missions.models import MissionStatus


class QueuedCodeChangeService(Protocol):
    mission_service: Any

    def process_queued_candidate(
        self,
        *,
        mission_id: str,
    ) -> Any:
        ...


class CodeChangeQueueRunner:
    def __init__(
        self,
        *,
        code_change_service: QueuedCodeChangeService,
    ) -> None:
        self.code_change_service = code_change_service

    def run_once(self):
        missions = (
            self.code_change_service
            .mission_service
            .list_missions()
        )

        for mission in missions:
            if mission.status is not MissionStatus.QUEUED:
                continue

            if mission.source != "hq_chat_code_change":
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
