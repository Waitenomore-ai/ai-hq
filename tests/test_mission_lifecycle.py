from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import MissionStatus
from ai_hq.missions.service import MissionService
from ai_hq.models.admin_session import AdminSession


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1


def build_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        environment="production",
        database_url="sqlite+pysqlite://",
        redis_url="redis://unused:6379/0",
        admin_password_hash=PasswordHasher().hash("separate-ai-hq-password"),
        session_secret="s" * 48,
    )
    app = create_app(
        settings=settings,
        session_factory=factory,
        redis_client=FakeRedis(),
        database_probe=lambda: True,
        redis_probe=lambda: True,
    )
    return TestClient(app, base_url="https://testserver"), factory


def login(client, factory):
    response = client.post(
        "/login",
        data={"password": "separate-ai-hq-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    token = client.cookies.get("ai_hq_session")
    with factory() as db:
        record = db.scalar(select(AdminSession))
        assert record is not None
        csrf_token = record.csrf_token
    return {"Cookie": f"ai_hq_session={token}"}, csrf_token


def test_mission_api_requires_existing_admin_session():
    client, _ = build_client()
    assert client.get("/api/missions").status_code == 401
    assert client.post("/api/missions", json={}).status_code == 401


def test_authenticated_creation_requires_csrf_and_records_creation_event():
    client, factory = build_client()
    auth_headers, csrf_token = login(client, factory)
    payload = {
        "title": "Inspect service health",
        "description": "Create a local read-only mission record.",
        "owner_agent": "sysadmin",
        "source": "direct_user_request",
        "priority": "normal",
        "risk": "green",
        "objectives": ["inspect health"],
        "dependencies": [],
    }

    rejected = client.post("/api/missions", json=payload, headers=auth_headers)
    assert rejected.status_code == 403

    created = client.post(
        "/api/missions",
        json=payload,
        headers={**auth_headers, "X-CSRF-Token": csrf_token},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "QUEUED"
    assert body["owner_agent"] == "sysadmin"

    ledger = OperationsLedger(factory)
    events = ledger.for_mission(body["id"])
    assert [event.event_type for event in events] == [LedgerEventType.MISSION_CREATED]


def test_mission_service_transition_records_status_change_atomically():
    client, factory = build_client()
    auth_headers, csrf_token = login(client, factory)
    created = client.post(
        "/api/missions",
        json={
            "title": "Prepare a briefing",
            "description": "Local mission lifecycle test.",
            "owner_agent": "commander",
            "source": "direct_user_request",
            "priority": "normal",
            "risk": "green",
        },
        headers={**auth_headers, "X-CSRF-Token": csrf_token},
    ).json()

    service = MissionService(factory, ledger=OperationsLedger(factory))
    running = service.transition(created["id"], MissionStatus.RUNNING)
    assert running.status is MissionStatus.RUNNING
    events = OperationsLedger(factory).for_mission(created["id"])
    assert [event.event_type for event in events] == [
        LedgerEventType.MISSION_CREATED,
        LedgerEventType.MISSION_STATUS_CHANGED,
    ]
    assert events[-1].event_data == {"from": "QUEUED", "to": "RUNNING"}


def test_authenticated_list_and_detail_expose_local_mission_records_only():
    client, factory = build_client()
    auth_headers, csrf_token = login(client, factory)
    created = client.post(
        "/api/missions",
        json={
            "title": "List me",
            "description": "Mission API read contract.",
            "owner_agent": "calendar",
            "source": "direct_user_request",
            "priority": "normal",
            "risk": "green",
        },
        headers={**auth_headers, "X-CSRF-Token": csrf_token},
    ).json()

    listing = client.get("/api/missions", headers=auth_headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [created["id"]]

    detail = client.get(f"/api/missions/{created['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["title"] == "List me"
    assert client.post(f"/api/missions/{created['id']}/execute", headers=auth_headers).status_code == 404


def test_mission_detail_exposes_persisted_plan_progress():
    client, factory = build_client()
    auth_headers, csrf_token = login(client, factory)

    created = client.post(
        "/api/missions",
        json={
            "title": "Inspectable autonomous mission",
            "description": "Expose autonomous plan progress.",
            "owner_agent": "sysadmin",
            "source": "direct_user_request",
            "priority": "normal",
            "risk": "green",
        },
        headers={**auth_headers, "X-CSRF-Token": csrf_token},
    ).json()

    service = MissionService(factory)
    service.create_plan(
        created["id"],
        [
            {
                "description": "Inspect readiness",
                "tool_name": "host.health",
                "tool_arguments": {"target": "ai-hq"},
            }
        ],
    )

    detail = client.get(
        f"/api/missions/{created['id']}",
        headers=auth_headers,
    )

    assert detail.status_code == 200
    plan = detail.json()["plan"]

    assert len(plan) == 1
    assert plan[0]["position"] == 1
    assert plan[0]["description"] == "Inspect readiness"
    assert plan[0]["tool_name"] == "host.health"
    assert plan[0]["status"] == "PENDING"
