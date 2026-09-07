from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import (
    Mission,
    MissionPriority,
    MissionRisk,
    MissionStatus,
    MissionStep,
    MissionStepStatus,
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


_ALLOWED_STEP_TRANSITIONS: dict[MissionStepStatus, set[MissionStepStatus]] = {
    MissionStepStatus.PENDING: {
        MissionStepStatus.RUNNING,
    },
    MissionStepStatus.RUNNING: {
        MissionStepStatus.WAITING_APPROVAL,
        MissionStepStatus.SUCCEEDED,
        MissionStepStatus.FAILED,
    },
    MissionStepStatus.WAITING_APPROVAL: {
        MissionStepStatus.RUNNING,
        MissionStepStatus.FAILED,
    },
    MissionStepStatus.SUCCEEDED: set(),
    MissionStepStatus.FAILED: set(),
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

    def next_pending_step(self, mission_id: str) -> MissionStep | None:
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            return db.scalar(
                select(MissionStep)
                .where(
                    MissionStep.mission_id == mission_id,
                    MissionStep.status == MissionStepStatus.PENDING,
                )
                .order_by(MissionStep.position, MissionStep.id)
                .limit(1)
            )

    def claim_next_pending_step(
        self,
        mission_id: str,
    ) -> MissionStep | None:
        """
        Atomically claim only the mission's first incomplete step.

        A later step must never become runnable while an earlier step is
        RUNNING, WAITING_APPROVAL, FAILED, or otherwise incomplete.
        The conditional UPDATE prevents two workers from claiming the same
        pending step.
        """
        with self.session_factory() as db:
            first_incomplete_id = db.scalar(
                select(MissionStep.id)
                .where(
                    MissionStep.mission_id == mission_id,
                    MissionStep.status != MissionStepStatus.SUCCEEDED,
                )
                .order_by(
                    MissionStep.position,
                    MissionStep.id,
                )
                .limit(1)
            )

            if first_incomplete_id is None:
                return None

            claimed = db.execute(
                update(MissionStep)
                .where(
                    MissionStep.id == first_incomplete_id,
                    MissionStep.status == MissionStepStatus.PENDING,
                )
                .values(status=MissionStepStatus.RUNNING)
            )

            if claimed.rowcount != 1:
                db.rollback()
                return None

            db.commit()
            return db.get(MissionStep, first_incomplete_id)


    def transition_step(
        self,
        step_id: str,
        status: MissionStepStatus | str,
        *,
        result: dict | None = None,
        error_state: dict | None = None,
        approval_reference: str | None = None,
    ) -> MissionStep:
        target = MissionStepStatus(status)

        with self.session_factory() as db:
            step = db.get(MissionStep, step_id)
            if step is None:
                raise KeyError(f"mission step not found: {step_id}")

            previous = step.status
            if target not in _ALLOWED_STEP_TRANSITIONS[previous]:
                raise ValueError(
                    "invalid mission step transition: "
                    f"{previous.value} -> {target.value}"
                )

            step.status = target

            if result is not None:
                step.result = result

            if error_state is not None:
                step.error_state = error_state

            if approval_reference is not None:
                step.approval_reference = approval_reference

            db.commit()
            db.refresh(step)
            return step

    def list_plan_steps(self, mission_id: str) -> list[MissionStep]:
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            return list(
                db.scalars(
                    select(MissionStep)
                    .where(MissionStep.mission_id == mission_id)
                    .order_by(MissionStep.position, MissionStep.id)
                )
            )

    def waiting_approval_step(self, mission_id: str) -> MissionStep | None:
        with self.session_factory() as db:
            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")

            return db.scalar(
                select(MissionStep)
                .where(
                    MissionStep.mission_id == mission_id,
                    MissionStep.status == MissionStepStatus.WAITING_APPROVAL,
                )
                .order_by(MissionStep.position, MissionStep.id)
                .limit(1)
            )

    def plan_is_complete(self, mission_id: str) -> bool:
        steps = self.list_plan_steps(mission_id)
        return bool(steps) and all(
            step.status is MissionStepStatus.SUCCEEDED
            for step in steps
        )

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

    def claim_oldest_code_change(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 900,
    ) -> Mission | None:
        worker_id = (
            worker_id.strip()
            if isinstance(worker_id, str)
            else ""
        )

        if not worker_id:
            raise ValueError(
                "code-change worker id is required"
            )

        if lease_seconds < 60:
            raise ValueError(
                "code-change lease must be "
                "at least 60 seconds"
            )

        now = datetime.now(UTC)
        expires_at = now + timedelta(
            seconds=lease_seconds
        )

        with self.session_factory() as db:
            claimable = or_(
                Mission.status
                == MissionStatus.QUEUED,
                and_(
                    Mission.status
                    == MissionStatus.RUNNING,
                    Mission.lease_expires_at.is_not(
                        None
                    ),
                    Mission.lease_expires_at < now,
                ),
            )

            candidate_ids = list(
                db.scalars(
                    select(Mission.id)
                    .where(
                        Mission.source
                        == "hq_chat_code_change",
                        Mission.owner_agent
                        == "developer",
                        claimable,
                    )
                    .order_by(
                        Mission.created_at,
                        Mission.id,
                    )
                    .limit(8)
                )
            )

            for mission_id in candidate_ids:
                claimed = db.execute(
                    update(Mission)
                    .where(
                        Mission.id == mission_id,
                        Mission.source
                        == "hq_chat_code_change",
                        Mission.owner_agent
                        == "developer",
                        claimable,
                    )
                    .values(
                        status=(
                            MissionStatus.RUNNING
                        ),
                        lease_owner=worker_id,
                        lease_expires_at=expires_at,
                        attempt_count=(
                            Mission.attempt_count + 1
                        ),
                    )
                )

                if claimed.rowcount != 1:
                    db.rollback()
                    continue

                db.commit()

                mission = db.get(
                    Mission,
                    mission_id,
                )

                if mission is None:
                    raise RuntimeError(
                        "claimed mission disappeared"
                    )

                return mission

            return None

    def renew_code_change_lease(
        self,
        mission_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 900,
    ) -> bool:
        if lease_seconds < 60:
            raise ValueError(
                "code-change lease must be "
                "at least 60 seconds"
            )

        now = datetime.now(UTC)

        with self.session_factory() as db:
            renewed = db.execute(
                update(Mission)
                .where(
                    Mission.id == mission_id,
                    Mission.source
                    == "hq_chat_code_change",
                    Mission.owner_agent
                    == "developer",
                    Mission.status
                    == MissionStatus.RUNNING,
                    Mission.lease_owner
                    == worker_id,
                    Mission.lease_expires_at
                    .is_not(None),
                    Mission.lease_expires_at
                    >= now,
                )
                .values(
                    lease_expires_at=(
                        now
                        + timedelta(
                            seconds=lease_seconds
                        )
                    )
                )
            )

            if renewed.rowcount != 1:
                db.rollback()
                return False

            db.commit()
            return True

    def release_code_change_lease(
        self,
        mission_id: str,
        *,
        worker_id: str,
    ) -> bool:
        with self.session_factory() as db:
            released = db.execute(
                update(Mission)
                .where(
                    Mission.id == mission_id,
                    Mission.lease_owner
                    == worker_id,
                )
                .values(
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )

            if released.rowcount != 1:
                db.rollback()
                return False

            db.commit()
            return True

    def record_result(
        self,
        mission_id: str,
        *,
        result: dict,
    ) -> Mission:
        with self.session_factory() as db:
            mission = db.get(
                Mission,
                mission_id,
            )

            if mission is None:
                raise KeyError(
                    f"mission not found: {mission_id}"
                )

            mission.result = dict(result)

            db.commit()
            db.refresh(mission)

            return mission

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
