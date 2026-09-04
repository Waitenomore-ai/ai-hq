from __future__ import annotations

from dataclasses import dataclass

from ai_hq.missions.models import (
    MissionStatus,
    MissionStep,
    MissionStepStatus,
)
from ai_hq.missions.service import MissionService
from ai_hq.tool_gateway.contracts import (
    ToolOutcome,
    ToolOutcomeState,
    ToolRequest,
)
from ai_hq.tool_gateway.service import ToolGateway


@dataclass(frozen=True, slots=True)
class MissionExecutionResult:
    mission_id: str
    mission_status: MissionStatus
    step_id: str | None = None
    step_status: MissionStepStatus | None = None
    outcome: ToolOutcome | None = None


class MissionExecutor:
    """
    Advances an autonomous mission exactly one step at a time.

    The executor never invokes host helpers, adapters, subprocesses, or
    infrastructure directly. All executable actions cross ToolGateway.
    """

    def __init__(
        self,
        missions: MissionService,
        gateway: ToolGateway,
    ) -> None:
        self.missions = missions
        self.gateway = gateway

    def run_next(self, mission_id: str) -> MissionExecutionResult:
        mission = self.missions.get_mission(mission_id)

        if mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            return MissionExecutionResult(
                mission_id=mission.id,
                mission_status=mission.status,
            )

        if mission.status is MissionStatus.WAITING_APPROVAL:
            waiting = self.missions.waiting_approval_step(mission.id)
            if waiting is not None:
                return MissionExecutionResult(
                    mission_id=mission.id,
                    mission_status=mission.status,
                    step_id=waiting.id,
                    step_status=waiting.status,
                )

        step = self.missions.claim_next_pending_step(mission.id)

        if step is None:
            if self.missions.plan_is_complete(mission.id):
                if mission.status is MissionStatus.QUEUED:
                    mission = self.missions.transition(
                        mission.id,
                        MissionStatus.RUNNING,
                    )
                if mission.status is MissionStatus.RUNNING:
                    mission = self.missions.transition(
                        mission.id,
                        MissionStatus.COMPLETED,
                    )

            return MissionExecutionResult(
                mission_id=mission.id,
                mission_status=mission.status,
            )

        if mission.status is MissionStatus.QUEUED:
            mission = self.missions.transition(
                mission.id,
                MissionStatus.RUNNING,
            )

        request = self._request_for(mission, step)
        outcome = self.gateway.execute(request)

        if outcome.state is ToolOutcomeState.WAITING_APPROVAL:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.WAITING_APPROVAL,
                approval_reference=outcome.approval_request_id,
            )

            mission = self.missions.transition(
                mission.id,
                MissionStatus.WAITING_APPROVAL,
            )

        elif outcome.state in {
            ToolOutcomeState.EXECUTED,
            ToolOutcomeState.SIMULATED,
        }:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.SUCCEEDED,
                result=outcome.result or {},
            )

            if self.missions.plan_is_complete(mission.id):
                mission = self.missions.transition(
                    mission.id,
                    MissionStatus.COMPLETED,
                    result={"plan_status": "completed"},
                )

        else:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.FAILED,
                error_state={
                    "gateway_state": outcome.state.value,
                    "reason": outcome.reason,
                },
            )

            mission = self.missions.transition(
                mission.id,
                MissionStatus.FAILED,
                error_state={
                    "step_id": step.id,
                    "gateway_state": outcome.state.value,
                    "reason": outcome.reason,
                },
            )

        return MissionExecutionResult(
            mission_id=mission.id,
            mission_status=mission.status,
            step_id=step.id,
            step_status=step.status,
            outcome=outcome,
        )

    def resume_approved(self, mission_id: str) -> MissionExecutionResult:
        mission = self.missions.get_mission(mission_id)

        if mission.status is not MissionStatus.WAITING_APPROVAL:
            raise ValueError("mission is not waiting for approval")

        step = self.missions.waiting_approval_step(mission.id)
        if step is None:
            raise ValueError("mission has no step waiting for approval")

        # The gateway remains the authority for whether the approval is
        # actually valid. We only return the step to RUNNING and ask the
        # gateway to evaluate the exact same request again.
        step = self.missions.transition_step(
            step.id,
            MissionStepStatus.RUNNING,
        )

        mission = self.missions.transition(
            mission.id,
            MissionStatus.RUNNING,
        )

        outcome = self.gateway.execute(self._request_for(mission, step))

        if outcome.state is ToolOutcomeState.WAITING_APPROVAL:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.WAITING_APPROVAL,
                approval_reference=outcome.approval_request_id,
            )
            mission = self.missions.transition(
                mission.id,
                MissionStatus.WAITING_APPROVAL,
            )

        elif outcome.state in {
            ToolOutcomeState.EXECUTED,
            ToolOutcomeState.SIMULATED,
        }:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.SUCCEEDED,
                result=outcome.result or {},
            )

            if self.missions.plan_is_complete(mission.id):
                mission = self.missions.transition(
                    mission.id,
                    MissionStatus.COMPLETED,
                    result={"plan_status": "completed"},
                )

        else:
            step = self.missions.transition_step(
                step.id,
                MissionStepStatus.FAILED,
                error_state={
                    "gateway_state": outcome.state.value,
                    "reason": outcome.reason,
                },
            )
            mission = self.missions.transition(
                mission.id,
                MissionStatus.FAILED,
                error_state={
                    "step_id": step.id,
                    "gateway_state": outcome.state.value,
                    "reason": outcome.reason,
                },
            )

        return MissionExecutionResult(
            mission_id=mission.id,
            mission_status=mission.status,
            step_id=step.id,
            step_status=step.status,
            outcome=outcome,
        )

    @staticmethod
    def _request_for(mission, step: MissionStep) -> ToolRequest:
        arguments = dict(step.tool_arguments or {})

        target = str(arguments.pop("target", mission.id))
        conditions = arguments.pop("conditions", {})
        mutates_external_state = bool(
            arguments.pop("mutates_external_state", False)
        )

        if not isinstance(conditions, dict):
            raise ValueError("mission step conditions must be an object")

        return ToolRequest(
            mission_id=mission.id,
            agent_key=mission.owner_agent,
            capability=step.tool_name,
            target=target,
            risk=mission.risk,
            params=arguments,
            conditions=conditions,
            mutates_external_state=mutates_external_state,
        )
