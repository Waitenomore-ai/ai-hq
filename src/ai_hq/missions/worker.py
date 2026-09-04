from __future__ import annotations

from ai_hq.missions.executor import MissionExecutionResult, MissionExecutor
from ai_hq.missions.models import MissionStatus
from ai_hq.missions.service import MissionService


class AutonomousMissionRunner:
    """
    Advances persisted autonomous mission plans through MissionExecutor.

    This runner never executes tools, host helpers, subprocesses, or
    infrastructure directly. MissionExecutor -> ToolGateway remains the
    only execution path.
    """

    def __init__(
        self,
        *,
        missions: MissionService,
        executor: MissionExecutor,
    ) -> None:
        self.missions = missions
        self.executor = executor

    def run_once(self) -> MissionExecutionResult | None:
        for mission in self.missions.list_missions():
            if mission.status not in {
                MissionStatus.QUEUED,
                MissionStatus.RUNNING,
            }:
                continue

            if not self.missions.list_plan_steps(mission.id):
                continue

            return self.executor.run_next(mission.id)

        return None

    def resume_approved(
        self,
        mission_id: str,
    ) -> MissionExecutionResult:
        return self.executor.resume_approved(mission_id)
