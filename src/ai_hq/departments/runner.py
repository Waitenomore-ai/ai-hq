from collections.abc import Callable

from ai_hq.agents.models import AgentStatus
from ai_hq.agents.registry import AgentRegistry
from ai_hq.departments.commander import RoutedAction, UnsupportedMission, route_sysadmin_mission
from ai_hq.departments.sysadmin import SysAdminService
from ai_hq.missions.models import MissionStatus
from ai_hq.missions.service import MissionService

Router = Callable[[str], RoutedAction]


class DepartmentRunner:
    def __init__(
        self,
        *,
        mission_service: MissionService,
        agent_registry: AgentRegistry,
        sysadmin: SysAdminService,
        router: Router = route_sysadmin_mission,
    ):
        self.mission_service = mission_service
        self.agent_registry = agent_registry
        self.sysadmin = sysadmin
        self.router = router

    def run_once(self) -> bool:
        mission = self.mission_service.oldest_queued()
        if mission is None:
            return False

        self.agent_registry.set_state(
            "commander",
            AgentStatus.WORKING,
            current_mission_id=mission.id,
        )
        try:
            try:
                action = self.router(mission.title)
            except UnsupportedMission:
                self.mission_service.transition(
                    mission.id,
                    MissionStatus.FAILED,
                    error_state={"code": "unsupported_mission"},
                )
                return True
        finally:
            self.agent_registry.set_state(
                "commander",
                AgentStatus.IDLE,
                current_mission_id=None,
            )

        self.mission_service.assign_owner(mission.id, action.owner_agent)
        self.mission_service.transition(mission.id, MissionStatus.RUNNING)
        self.agent_registry.set_state(
            "sysadmin",
            AgentStatus.WORKING,
            current_mission_id=mission.id,
        )
        try:
            result = self.sysadmin.execute(mission_id=mission.id, action=action)
            if result.status is MissionStatus.COMPLETED:
                self.mission_service.transition(
                    mission.id,
                    MissionStatus.COMPLETED,
                    result=result.data,
                )
            elif result.status is MissionStatus.WAITING_APPROVAL:
                self.mission_service.transition(mission.id, MissionStatus.WAITING_APPROVAL)
            else:
                self.mission_service.transition(
                    mission.id,
                    MissionStatus.FAILED,
                    error_state={"code": result.error or "sysadmin_failed"},
                )
        finally:
            self.agent_registry.set_state(
                "sysadmin",
                AgentStatus.IDLE,
                current_mission_id=None,
            )
        return True
