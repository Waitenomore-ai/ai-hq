from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), OperationsLedger(factory)


def create_mission(service):
    return service.create_mission(
        title="Audit this mission",
        description="A durable mission used to verify ledger behavior.",
        owner_agent="commander",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.GREEN,
    )


def test_ledger_records_ordered_append_only_events_for_a_mission():
    missions, ledger = build_services()
    mission = create_mission(missions)
    first = ledger.record(
        mission_id=mission.id,
        agent_key="commander",
        event_type=LedgerEventType.MISSION_CREATED,
        summary="Mission created",
        metadata={"source": "direct_user_request"},
    )
    second = ledger.record(
        mission_id=mission.id,
        agent_key="commander",
        event_type=LedgerEventType.MISSION_STATUS_CHANGED,
        summary="Mission moved to running",
        metadata={"from": "QUEUED", "to": "RUNNING"},
    )

    events = ledger.for_mission(mission.id)
    assert [event.id for event in events] == [first.id, second.id]
    assert events[0].event_data == {"source": "direct_user_request"}
    assert events[1].event_type is LedgerEventType.MISSION_STATUS_CHANGED


def test_ledger_service_exposes_no_update_or_delete_operation():
    _, ledger = build_services()
    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")
    assert not hasattr(ledger, "remove")
