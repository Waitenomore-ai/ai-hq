from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.missions.models import Mission, MissionStatus
from ai_hq.models.admin_session import AdminSession

HELPER_SECRET_SENTINEL = "hq-helper-secret-must-never-reach-browser"
RAW_HELPER_BODY_SENTINEL = "raw-helper-request-body-must-never-reach-browser"


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, _key, _seconds):
        return True

    def delete(self, key):
        self.values.pop(key, None)
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
        host_helper_credential=HELPER_SECRET_SENTINEL,
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
        assert db.scalar(select(AdminSession)) is not None
    return {"Cookie": f"ai_hq_session={token}"}


def test_hq_state_requires_authentication():
    client, _factory = build_client()
    assert client.get("/api/hq/state").status_code == 401


def test_hq_state_returns_stable_first_floor_rooms():
    client, factory = build_client()
    auth = login(client, factory)
    response = client.get("/api/hq/state", headers=auth)
    assert response.status_code == 200
    assert response.json()["floor"]["key"] == "operations"
    assert [room["key"] for room in response.json()["rooms"]] == [
        "commander",
        "communications",
        "calendar",
        "sysadmin",
        "approvals",
        "knowledge",
    ]


def test_hq_state_exposes_only_friendly_mission_projection_not_helper_secrets():
    client, factory = build_client()
    with factory() as db:
        mission = Mission(
            title="Is Nginx running?",
            description=RAW_HELPER_BODY_SENTINEL,
            owner_agent="sysadmin",
            source="user",
            status=MissionStatus.RUNNING,
        )
        db.add(mission)
        db.flush()
        db.add(
            Agent(
                key="sysadmin",
                display_name="SysAdmin",
                role="Infrastructure",
                status=AgentStatus.WORKING,
                current_mission_id=mission.id,
            )
        )
        db.commit()

    auth = login(client, factory)
    response = client.get("/api/hq/state", headers=auth)

    assert response.status_code == 200
    assert "Is Nginx running?" in response.text
    assert HELPER_SECRET_SENTINEL not in response.text
    assert RAW_HELPER_BODY_SENTINEL not in response.text


def test_hq_state_api_is_read_only():
    client, factory = build_client()
    auth = login(client, factory)
    assert client.post("/api/hq/state", headers=auth).status_code == 405
