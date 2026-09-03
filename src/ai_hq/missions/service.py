from collections.abc import Callable

from sqlalchemy.orm import Session

from ai_hq.missions.models import Mission, MissionPriority, MissionRisk, MissionStatus

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
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

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
            if target not in _ALLOWED_TRANSITIONS[mission.status]:
                raise ValueError(
                    f"invalid mission transition: {mission.status.value} -> {target.value}"
                )
            mission.status = target
            if result is not None:
                mission.result = result
            if error_state is not None:
                mission.error_state = error_state
            db.commit()
            db.refresh(mission)
            return mission
