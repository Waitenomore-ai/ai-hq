from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base


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


def build_authenticated_client():
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
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/login",
        data={"password": "separate-ai-hq-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    token = client.cookies.get("ai_hq_session")
    return client, {"Cookie": f"ai_hq_session={token}"}


def test_authenticated_home_renders_first_hq_floor_contract():
    client, auth = build_authenticated_client()
    response = client.get("/", headers=auth)
    assert response.status_code == 200
    html = response.text
    assert "data-hq-viewport" in html
    for key in ("commander", "communications", "calendar", "sysadmin", "approvals", "knowledge"):
        assert f'data-room-key="{key}"' in html
    assert "/ai-hq/static/hq.css" in html
    assert "/ai-hq/static/hq.js" in html
    assert "Safe Mode" in html
    assert "Simulation" in html
    assert "Status legend" in html
    assert "Sign out" in html


def test_hq_rooms_are_keyboard_controls_with_text_status():
    client, auth = build_authenticated_client()
    html = client.get("/", headers=auth).text
    assert html.count('class="hq-room') >= 6
    assert html.count('type="button"') >= 6
    assert 'data-agent-state="OFFLINE"' in html
    assert "Status: Offline" in html


def test_hq_interface_exposes_no_execution_controls():
    client, auth = build_authenticated_client()
    html = client.get("/", headers=auth).text.casefold()
    for forbidden in ("execute mission", "send email", "restart service", "delete mission"):
        assert forbidden not in html


def test_hq_mobile_and_reduced_motion_contract():
    client, auth = build_authenticated_client()
    html = client.get("/", headers=auth).text
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
    css = client.get("/static/hq.css")
    assert css.status_code == 200
    assert "prefers-reduced-motion: reduce" in css.text
