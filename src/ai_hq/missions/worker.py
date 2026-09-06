from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ai_hq.missions.executor import MissionExecutionResult, MissionExecutor
from ai_hq.missions.models import MissionStatus
from ai_hq.missions.service import MissionService

if TYPE_CHECKING:
    from typing import Any


class VerifiedDeliveryRunner(Protocol):
    def persist_candidate(
        self,
        *,
        mission_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        ...


class AutonomousMissionRunner:
    """
    Advances persisted autonomous mission plans through MissionExecutor.

    This runner never persists Developer candidates directly. When an
    execution result carries candidate metadata, it is delegated to the
    verified delivery runner so machine workspace evidence establishes the
    trusted candidate identity before persistence.
    """

    def __init__(
        self,
        *,
        missions: MissionService,
        executor: MissionExecutor,
        delivery_runner: VerifiedDeliveryRunner | None = None,
    ) -> None:
        self.missions = missions
        self.executor = executor
        self.delivery_runner = delivery_runner

    def run_once(self) -> MissionExecutionResult | None:
        for mission in self.missions.list_missions():
            if mission.status not in {
                MissionStatus.QUEUED,
                MissionStatus.RUNNING,
            }:
                continue

            if not self.missions.list_plan_steps(mission.id):
                continue

            result = self.executor.run_next(mission.id)
            self._handoff_delivery_candidate(mission.id, result)
            return result

        return None

    def _handoff_delivery_candidate(
        self,
        mission_id: str,
        result: MissionExecutionResult,
    ) -> None:
        if self.delivery_runner is None:
            return

        candidate = getattr(result, "delivery_candidate", None)
        if candidate is None:
            return

        if not isinstance(candidate, dict):
            raise ValueError("delivery candidate must be a mapping")

        self.delivery_runner.persist_candidate(
            mission_id=mission_id,
            candidate=dict(candidate),
        )

    def resume_approved(
        self,
        mission_id: str,
    ) -> MissionExecutionResult:
        return self.executor.resume_approved(mission_id)
