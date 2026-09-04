from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import (
    Mission,
    MissionPriority,
    MissionRisk,
    MissionStatus,
    MissionStep,
)

if TYPE_CHECKING:
    from ai_hq.tool_gateway.registry import ToolRegistry


SessionFactory = Callable[[], Session]

_ALLOWED_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.QUEUED: {
        MissionStatus.RUNNING,
        MissionStatus.PAUSED,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
    },
    MissionStatus.RUNNING: {
        MissionStatus.WAITING_APPROVAL,
        MissionStatus.PAUSED,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.WAITING_APPROVAL: {
        MissionStatus.RUNNING,
        MissionStatus.PAUSED,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
    },
    MissionStatus.PAUSED: {
        MissionStatus.QUEUED,
        MissionStatus.RUNNING,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
    },
    MissionStatus.COMPLETED: set(),
    MissionStatus.FAILED: set(),
    MissionStatus.CANCELLED: set(),
}


class MissionService:
    def __init__(self, session_factory: SessionFactory, ledger: OperationsLedger | None = None):
        self.session_factory = session_factory
        self.ledger = ledger

    def create_mission(
        self,
        *,
        title: str,
        description: str,
        owner_agent: str,
        source: str,
        priority: MissionPriority | str = MissionPriority.NORMAL,
        risk: MissionRisk | str = MissionRisk.GREEN,
        objectives: list | None = None,
        dependencies: list | None = None,
        xp_reward: int = 0,
    ) -> Mission:
        mission = Mission(
            title=title,
            description=description,
            owner_agent=owner_agent,
            source=source,
            priority=MissionPriority(priority),
            risk=MissionRisk(risk),
            objectives=objectives or [],
            dependencies=dependencies or [],
            xp_reward=xp_reward,
        )
        with self.session_factory() as db:
            db.add(mission)
            db.flush()
            if self.ledger is not None:
                self.ledger.add_to_session(
                    db,
                    mission_id=mission.id,
                    agent_key=mission.owner_agent,
                    event_type=LedgerEventType.MISSION_CREATED,
                    summary="Mission created",
                    metadata={
                        "source": mission.source,
                        "priority": mission.priority.value,
                        "risk": mission.risk.value,
                        "status": mission.status.value,
                    },
                )
            db.commit()
            db.refresh(mission)
            return mission

    def create_plan(
        self,
        mission_id: str,
        steps: list[dict],
        *,
        tool_registry: "ToolRegistry | None" = None,
    ) -> list[MissionStep]:
        if not steps:
            raise ValueError("mission plan requires at least one step")

        if tool_registry is not None:
            for step in steps:
                tool_name = step["tool_name"]
                try:
                    adapter = tool_registry.resolve(tool_name)
                except (KeyError, ValueError) as exc:
                    raise ValueError(
                        f"unregistered mission tool: {tool_name}"
                    ) from exc
                if adapter is None:
                    raise ValueError(
                        f"unregistered mission tool: {tool_name}"
                    )

        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            existing = db.scalar(
                select(MissionStep)
                .where(MissionStep.mission_id == mission_id)
                .limit(1)
            )
            if existing is not None:
                raise ValueError("mission already has a plan")

            planned_steps = [
                MissionStep(
                    mission_id=mission.id,
                    position=position,
                    description=step["description"],
                    tool_name=step["tool_name"],
                    tool_arguments=step.get("tool_arguments", {}),
                )
                for position, step in enumerate(steps, start=1)
            ]

            db.add_all(planned_steps)
            db.commit()

            for step in planned_steps:
                db.refresh(step)

            return planned_steps

    def get_mission(self, mission_id: str) -> Mission:
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")
            return mission

    def list_missions(self) -> list[Mission]:
        with self.session_factory() as db:
            return list(db.scalars(select(Mission).order_by(Mission.created_at, Mission.id)))

    def oldest_queued(self) -> Mission | None:
        with self.session_factory() as db:
            return db.scalar(
                select(Mission)
                .where(Mission.status == MissionStatus.QUEUED)
                .order_by(Mission.created_at, Mission.id)
                .limit(1)
            )

    def assign_owner(self, mission_id: str, owner_agent: str) -> Mission:
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")
            if mission.status is not MissionStatus.QUEUED:
                raise ValueError("mission must be queued before owner assignment")
            mission.owner_agent = owner_agent
            db.commit()
            db.refresh(mission)
            return mission

    def transition(
        self,
        mission_id: str,
        status: MissionStatus | str,
        *,
        result: dict | None = None,
        error_state: dict | None = None,
    ) -> Mission:
        target = MissionStatus(status)
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")
            previous = mission.status
            if target not in _ALLOWED_TRANSITIONS[previous]:
                raise ValueError(
                    f"invalid mission transition: {previous.value} -> {target.value}"
                )
            mission.status = target
            if result is not None:
                mission.result = result
            if error_state is not None:
                mission.error_state = error_state
            if self.ledger is not None:
                self.ledger.add_to_session(
                    db,
                    mission_id=mission.id,
                    agent_key=mission.owner_agent,
                    event_type=LedgerEventType.MISSION_STATUS_CHANGED,
                    summary=f"Mission status changed to {target.value}",
                    metadata={"from": previous.value, "to": target.value},
                )
            db.commit()
            db.refresh(mission)
            return mission
