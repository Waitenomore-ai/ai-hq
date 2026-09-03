from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.models.admin_session import AdminSession
from ai_hq.notifications.service import NotificationService


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
        csrf = record.csrf_token
    return {"Cookie": f"ai_hq_session={token}"}, csrf


def seed(factory):
    service = NotificationService(factory)
    first = service.notify(
        severity="attention",
        title="Storage warning",
        message="Storage threshold exceeded.",
        source_type="sysadmin",
        source_id="storage-1",
        group_key="storage:warning",
    )
    second = service.notify(
        severity="approval_required",
        title="Approval required",
        message="A proposed action is waiting for approval.",
        source_type="mission",
        source_id="mission-1",
        group_key="approval:mission-1",
    )
    return first, second


def test_notification_api_requires_authentication():
    client, factory = build_client()
    first, _second = seed(factory)
    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/notifications/unread-count").status_code == 401
    assert client.get(f"/api/notifications/{first.id}").status_code == 401
    assert client.post(f"/api/notifications/{first.id}/read").status_code == 401
    assert client.post("/api/notifications/read-all").status_code == 401
    assert client.post(f"/api/notifications/{first.id}/dismiss").status_code == 401


def test_authenticated_notification_list_detail_and_unread_count():
    client, factory = build_client()
    first, second = seed(factory)
    auth, _csrf = login(client, factory)

    listing = client.get("/api/notifications", headers=auth)
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()}
    assert ids == {first.id, second.id}

    count = client.get("/api/notifications/unread-count", headers=auth)
    assert count.status_code == 200
    assert count.json() == {"unread": 2}

    detail = client.get(f"/api/notifications/{second.id}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["severity"] == "approval_required"
    assert detail.json()["occurrence_count"] == 1


def test_notification_mutations_require_csrf_and_update_counts():
    client, factory = build_client()
    first, second = seed(factory)
    auth, csrf = login(client, factory)

    assert client.post(f"/api/notifications/{first.id}/read", headers=auth).status_code == 403
    marked = client.post(
        f"/api/notifications/{first.id}/read",
        headers={**auth, "x-csrf-token": csrf},
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert client.get("/api/notifications/unread-count", headers=auth).json() == {"unread": 1}

    read_all = client.post(
        "/api/notifications/read-all",
        headers={**auth, "x-csrf-token": csrf},
    )
    assert read_all.status_code == 200
    assert read_all.json() == {"marked_read": 1}
    assert client.get("/api/notifications/unread-count", headers=auth).json() == {"unread": 0}

    dismissed = client.post(
        f"/api/notifications/{second.id}/dismiss",
        headers={**auth, "x-csrf-token": csrf},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None
    visible_ids = {item["id"] for item in client.get("/api/notifications", headers=auth).json()}
    assert second.id not in visible_ids


def test_notification_filters_and_no_browser_create_route():
    client, factory = build_client()
    first, second = seed(factory)
    auth, _csrf = login(client, factory)

    attention = client.get("/api/notifications?severity=attention", headers=auth)
    assert attention.status_code == 200
    assert [item["id"] for item in attention.json()] == [first.id]

    unread = client.get("/api/notifications?unread=true", headers=auth)
    assert unread.status_code == 200
    assert {item["id"] for item in unread.json()} == {first.id, second.id}

    assert client.post("/api/notifications", headers=auth, json={}).status_code == 405
