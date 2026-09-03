from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.approvals.service import ApprovalService
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk
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
    return {"Cookie": f"ai_hq_session={token}"}


def seed_approval(factory):
    mission = MissionService(factory).create_mission(
        title="Approval API",
        description="Read-only approval endpoint test.",
        owner_agent="sysadmin",
        source="test",
        risk=MissionRisk.AMBER,
    )
    approval = ApprovalService(factory).create_request(
        mission_id=mission.id,
        requester_agent="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "health failure"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return mission, approval


def test_approval_api_requires_authentication():
    client, factory = build_client()
    _mission, approval = seed_approval(factory)
    assert client.get("/api/approvals").status_code == 401
    assert client.get(f"/api/approvals/{approval.id}").status_code == 401


def test_authenticated_approval_list_and_detail_are_read_only():
    client, factory = build_client()
    mission, approval = seed_approval(factory)
    auth_headers = login(client, factory)

    listing = client.get("/api/approvals", headers=auth_headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [approval.id]

    filtered = client.get(
        f"/api/approvals?mission_id={mission.id}",
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()[0]["action_fingerprint"] == approval.action_fingerprint

    detail = client.get(f"/api/approvals/{approval.id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["state"] == "pending"
    assert detail.json()["action"] == "service.restart"

    assert client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers).status_code == 404
    assert client.post(f"/api/approvals/{approval.id}/execute", headers=auth_headers).status_code == 404
