from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.db import Base
from ai_hq.hq.state import HQStateService
from ai_hq.knowledge.models import (
    KnowledgeMemory,
    MemoryCategory,
    MemoryVisibility,
    VerificationState,
)
from ai_hq.missions.models import Mission, MissionRisk, MissionStatus


def factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_snapshot_uses_durable_agent_and_mission_state():
    sessions = factory()
    with sessions() as db:
        mission = Mission(
            title="Check DripVid health",
            description="Read-only health check",
            owner_agent="sysadmin",
            source="user",
            status=MissionStatus.RUNNING,
        )
        db.add(mission)
        db.flush()
        db.add_all(
            [
                Agent(
                    key="commander",
                    display_name="Commander",
                    role="Coordinator",
                    status=AgentStatus.IDLE,
                ),
                Agent(
                    key="sysadmin",
                    display_name="SysAdmin",
                    role="Infrastructure",
                    status=AgentStatus.WORKING,
                    current_mission_id=mission.id,
                ),
            ]
        )
        db.commit()

    rooms = {room["key"]: room for room in HQStateService(sessions).snapshot()["rooms"]}
    assert rooms["commander"]["state"] == "IDLE"
    assert rooms["sysadmin"]["state"] == "WORKING"
    assert rooms["sysadmin"]["mission_title"] == "Check DripVid health"
    assert rooms["communications"]["state"] == "OFFLINE"
    assert rooms["calendar"]["state"] == "OFFLINE"


def test_commander_working_state_is_durable_and_clears_after_routing():
    sessions = factory()
    with sessions() as db:
        mission = Mission(
            title="Is Nginx running?",
            description="Read-only service observation",
            owner_agent="commander",
            source="user",
            status=MissionStatus.QUEUED,
        )
        db.add(mission)
        db.flush()
        db.add(
            Agent(
                key="commander",
                display_name="Commander",
                role="Coordinator",
                status=AgentStatus.WORKING,
                current_mission_id=mission.id,
            )
        )
        db.commit()

    service = HQStateService(sessions)
    rooms = {room["key"]: room for room in service.snapshot()["rooms"]}
    assert rooms["commander"]["state"] == "WORKING"
    assert rooms["commander"]["mission_title"] == "Is Nginx running?"

    with sessions() as db:
        commander = db.scalar(select(Agent).where(Agent.key == "commander"))
        commander.status = AgentStatus.IDLE
        commander.current_mission_id = None
        db.commit()

    rooms = {room["key"]: room for room in service.snapshot()["rooms"]}
    assert rooms["commander"]["state"] == "IDLE"
    assert rooms["commander"]["mission_title"] is None


def test_sysadmin_completed_mission_projects_idle_after_agent_cleanup():
    sessions = factory()
    with sessions() as db:
        mission = Mission(
            title="Check AI HQ health",
            description="Read-only health observation",
            owner_agent="sysadmin",
            source="user",
            status=MissionStatus.RUNNING,
        )
        db.add(mission)
        db.flush()
        mission_id = mission.id
        db.add(
            Agent(
                key="sysadmin",
                display_name="SysAdmin",
                role="Infrastructure",
                status=AgentStatus.WORKING,
                current_mission_id=mission_id,
            )
        )
        db.commit()

    service = HQStateService(sessions)
    rooms = {room["key"]: room for room in service.snapshot()["rooms"]}
    assert rooms["sysadmin"]["state"] == "WORKING"
    assert rooms["sysadmin"]["mission_title"] == "Check AI HQ health"

    with sessions() as db:
        mission = db.get(Mission, mission_id)
        sysadmin = db.scalar(select(Agent).where(Agent.key == "sysadmin"))
        mission.status = MissionStatus.COMPLETED
        sysadmin.status = AgentStatus.IDLE
        sysadmin.current_mission_id = None
        db.commit()

    rooms = {room["key"]: room for room in service.snapshot()["rooms"]}
    assert rooms["sysadmin"]["state"] == "IDLE"
    assert rooms["sysadmin"]["mission_title"] is None


def test_shared_rooms_report_real_counts_without_agent_avatar():
    sessions = factory()
    with sessions() as db:
        mission = Mission(
            title="Approval mission",
            description="Needs approval",
            owner_agent="communications",
            source="user",
            status=MissionStatus.WAITING_APPROVAL,
        )
        db.add(mission)
        db.flush()
        db.add(
            ApprovalRequest(
                mission_id=mission.id,
                requester_agent="communications",
                action="email.send",
                target="person@example.test",
                risk=MissionRisk.AMBER,
                action_plan={},
                action_fingerprint="a" * 64,
                state=ApprovalState.PENDING,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.add(
            KnowledgeMemory(
                category=MemoryCategory.CONFIRMED_FACT,
                content="DripVid is an owned service",
                owner_scope="shared",
                provenance={"source": "user"},
                confidence=1.0,
                verification_state=VerificationState.CONFIRMED,
                visibility=MemoryVisibility.SHARED,
            )
        )
        db.commit()

    rooms = {room["key"]: room for room in HQStateService(sessions).snapshot()["rooms"]}
    assert rooms["approvals"]["agent"] is None
    assert rooms["approvals"]["state"] == "WAITING_APPROVAL"
    assert rooms["approvals"]["count"] == 1
    assert rooms["knowledge"]["agent"] is None
    assert rooms["knowledge"]["state"] == "IDLE"
    assert rooms["knowledge"]["count"] == 1


def test_completed_agent_status_projects_to_idle():
    sessions = factory()
    with sessions() as db:
        db.add(
            Agent(
                key="calendar",
                display_name="Calendar",
                role="Planning",
                status=AgentStatus.COMPLETED,
            )
        )
        db.commit()

    rooms = {room["key"]: room for room in HQStateService(sessions).snapshot()["rooms"]}
    assert rooms["calendar"]["state"] == "IDLE"
