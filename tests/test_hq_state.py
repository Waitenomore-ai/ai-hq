from datetime import UTC, datetime, timedelta

from ai_hq.hq.state import HQStateService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.db import Base
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
