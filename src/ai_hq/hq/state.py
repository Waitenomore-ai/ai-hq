from sqlalchemy import func, select

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.delivery.models import Delivery, DeliveryStage
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

_DEFAULT_RECOVERY = {
    "last_probe_at": None,
    "last_result": "unknown",
    "reachable": None,
    "status_code": None,
    "ready": None,
    "consecutive_failures": 0,
    "active_incident_id": None,
    "active_incident_state": None,
}


class HQStateService:
    def __init__(
        self,
        session_factory,
        *,
        recovery_status_service=None,
        recovery_settings_provider=None,
    ):
        self.session_factory = session_factory
        self.recovery_status_service = recovery_status_service
        self.recovery_settings_provider = recovery_settings_provider

    def _recovery_snapshot(self) -> dict:
        settings = (
            self.recovery_settings_provider()
            if self.recovery_settings_provider is not None
            else {}
        )
        persisted = (
            self.recovery_status_service.snapshot("dripvid")
            if self.recovery_status_service is not None
            else _DEFAULT_RECOVERY
        )
        return {
            "enabled": bool(settings.get("enabled", False)),
            "observe_only": bool(settings.get("observe_only", True)),
            **dict(persisted),
        }

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

            active_delivery = db.scalar(
                select(Delivery)
                .where(
                    Delivery.stage.in_(
                        (
                            DeliveryStage.DEVELOPER,
                            DeliveryStage.QA,
                            DeliveryStage.WAITING_APPROVAL,
                        )
                    )
                )
                .order_by(
                    Delivery.updated_at.desc(),
                    Delivery.id.desc(),
                )
                .limit(1)
            )

            delivery_mission = (
                db.get(Mission, active_delivery.mission_id)
                if active_delivery is not None
                else None
            )

            developer_working = (
                active_delivery is not None
                and active_delivery.stage is DeliveryStage.DEVELOPER
            )

            qa_working = (
                active_delivery is not None
                and active_delivery.stage is DeliveryStage.QA
            )

            rooms.extend(
                [
                    {
                        "key": "developer",
                        "label": "Developer",
                        "agent": {
                            "key": "developer",
                            "display_name": "Developer",
                        },
                        "state": (
                            "WORKING"
                            if developer_working
                            else "IDLE"
                        ),
                        "mission_title": (
                            delivery_mission.title
                            if developer_working
                            and delivery_mission is not None
                            else None
                        ),
                        "count": None,
                    },
                    {
                        "key": "qa",
                        "label": "QA",
                        "agent": {
                            "key": "qa",
                            "display_name": "QA",
                        },
                        "state": (
                            "WORKING"
                            if qa_working
                            else "IDLE"
                        ),
                        "mission_title": (
                            delivery_mission.title
                            if qa_working
                            and delivery_mission is not None
                            else None
                        ),
                        "count": None,
                    },
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
                "recovery": self._recovery_snapshot(),
            }
