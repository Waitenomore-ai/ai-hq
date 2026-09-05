from __future__ import annotations

from typing import TYPE_CHECKING

from ai_hq.missions.executor import MissionExecutionResult, MissionExecutor
from ai_hq.missions.models import MissionStatus
from ai_hq.missions.service import MissionService

if TYPE_CHECKING:
    from ai_hq.delivery.runtime import DeliveryRuntime


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
        delivery_runtime: DeliveryRuntime | None = None,
    ) -> None:
        self.missions = missions
        self.executor = executor
        self.delivery_runtime = delivery_runtime

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

            self._handoff_delivery_candidate(
                mission.id,
                result,
            )

            return result

        return None

    def _handoff_delivery_candidate(
        self,
        mission_id: str,
        result: MissionExecutionResult,
    ) -> None:
        if self.delivery_runtime is None:
            return

        candidate = getattr(
            result,
            "delivery_candidate",
            None,
        )

        if candidate is None:
            return

        if not isinstance(candidate, dict):
            raise ValueError(
                "delivery candidate must be a mapping"
            )

        change_ref = candidate.get("change_ref")

        if not isinstance(change_ref, str) or not change_ref.strip():
            raise ValueError(
                "delivery candidate requires immutable change_ref"
            )

        summary = candidate.get("summary")

        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(
                "delivery candidate requires summary"
            )

        evidence = candidate.get("evidence")

        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(
                "delivery candidate requires developer evidence"
            )

        changed_files = candidate.get(
            "changed_files",
            [],
        )

        if not isinstance(changed_files, list):
            raise ValueError(
                "delivery candidate changed_files must be a list"
            )

        self.delivery_runtime.handoff_to_developer(
            mission_id=mission_id,
            change_ref=change_ref,
            summary=summary,
            changed_files=changed_files,
            evidence=evidence,
        )

    def resume_approved(
        self,
        mission_id: str,
    ) -> MissionExecutionResult:
        return self.executor.resume_approved(mission_id)
