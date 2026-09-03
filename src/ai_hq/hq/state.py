from sqlalchemy import func, select

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.knowledge.models import KnowledgeMemory
from ai_hq.missions.models import Mission

_AGENT_ROOMS = (
    ("commander", "Commander", "Command Center"),
    ("communications", "Communications", "Comms"),
    ("calendar", "Calendar", "Planning"),
    ("sysadmin", "SysAdmin", "Infrastructure"),
)

_STATE_MAP = {
    AgentStatus.IDLE: "IDLE",
    AgentStatus.WORKING: "WORKING",
    AgentStatus.WAITING_APPROVAL: "WAITING_APPROVAL",
    AgentStatus.FAILED: "FAILED",
    AgentStatus.COMPLETED: "IDLE",
}


class HQStateService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def snapshot(self) -> dict:
        with self.session_factory() as db:
            agents = {
                agent.key: agent
                for agent in db.scalars(
                    select(Agent).where(Agent.key.in_([item[0] for item in _AGENT_ROOMS]))
                )
            }
            mission_ids = [
                agent.current_mission_id
                for agent in agents.values()
                if agent.current_mission_id is not None
            ]
            missions = (
                {
                    mission.id: mission
                    for mission in db.scalars(select(Mission).where(Mission.id.in_(mission_ids)))
                }
                if mission_ids
                else {}
            )
            pending_approvals = db.scalar(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.state == ApprovalState.PENDING)
            ) or 0
            knowledge_count = db.scalar(
                select(func.count())
                .select_from(KnowledgeMemory)
                .where(KnowledgeMemory.deleted_at.is_(None))
            ) or 0

            rooms = []
            for key, display_name, label in _AGENT_ROOMS:
                agent = agents.get(key)
                if agent is None:
                    rooms.append(
                        {
                            "key": key,
                            "label": label,
                            "agent": {"key": key, "display_name": display_name},
                            "state": "OFFLINE",
                            "mission_title": None,
                            "count": None,
                        }
                    )
                    continue

                mission = missions.get(agent.current_mission_id)
                rooms.append(
                    {
                        "key": key,
                        "label": label,
                        "agent": {
                            "key": agent.key,
                            "display_name": agent.display_name,
                        },
                        "state": _STATE_MAP.get(agent.status, "OFFLINE"),
                        "mission_title": mission.title if mission else None,
                        "count": None,
                    }
                )

            rooms.extend(
                [
                    {
                        "key": "approvals",
                        "label": "Approval Station",
                        "agent": None,
                        "state": "WAITING_APPROVAL" if pending_approvals else "IDLE",
                        "mission_title": None,
                        "count": pending_approvals,
                    },
                    {
                        "key": "knowledge",
                        "label": "Knowledge Core",
                        "agent": None,
                        "state": "IDLE",
                        "mission_title": None,
                        "count": knowledge_count,
                    },
                ]
            )
            return {
                "floor": {
                    "key": "operations",
                    "name": "Operations Floor",
                    "version": 1,
                },
                "rooms": rooms,
            }
