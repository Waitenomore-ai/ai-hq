from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.models.admin_session import AdminSession
from ai_hq.models.system_state import SystemState


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


def proxied_auth_headers(client, **extra):
    token = client.cookies.get("ai_hq_session")
    headers = {"Cookie": f"ai_hq_session={token}"}
    headers.update(extra)
    return headers


def test_unauthenticated_home_redirects_to_prefixed_login():
    client, _ = build_client()
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ai-hq/login"


def test_successful_login_sets_secure_scoped_cookie_and_unlocks_home():
    client, _ = build_client()
    response = client.post(
        "/login",
        data={"password": "separate-ai-hq-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ai-hq/"
    cookie = response.headers["set-cookie"]
    assert "ai_hq_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/ai-hq" in cookie

    home = client.get("/", headers=proxied_auth_headers(client), follow_redirects=False)
    assert home.status_code == 200
    assert "Authenticated administrator session." in home.text


def test_home_renders_durable_runtime_simulation_state():
    client, factory = build_client()
    login = client.post(
        "/login",
        data={"password": "separate-ai-hq-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    with factory() as db:
        db.add(SystemState(id=1, operating_mode="safe", simulation_mode=False))
        db.commit()

    home = client.get("/", headers=proxied_auth_headers(client), follow_redirects=False)
    assert home.status_code == 200
    assert "Safe Mode" in home.text
    assert "Simulation Off" in home.text
    assert "Simulation On" not in home.text


def test_bad_password_is_generic_and_does_not_authenticate():
    client, _ = build_client()
    response = client.post(
        "/login",
        data={"password": "wrong-password"},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.text
    assert "argon2" not in response.text.lower()
    assert client.get("/api/session").status_code == 401


def test_health_endpoints_remain_public():
    client, _ = build_client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_logout_requires_csrf_and_revokes_session():
    client, factory = build_client()
    login = client.post(
        "/login",
        data={"password": "separate-ai-hq-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    with factory() as db:
        record = db.scalar(select(AdminSession))
        assert record is not None
        csrf_token = record.csrf_token

    rejected = client.post(
        "/logout",
        data={"csrf_token": "wrong"},
        headers=proxied_auth_headers(client, Origin="https://testserver"),
        follow_redirects=False,
    )
    assert rejected.status_code == 403

    logged_out = client.post(
        "/logout",
        data={"csrf_token": csrf_token},
        headers=proxied_auth_headers(client, Origin="https://testserver"),
        follow_redirects=False,
    )
    assert logged_out.status_code == 303
    assert logged_out.headers["location"] == "/ai-hq/login"
    assert client.get(
        "/api/session", headers=proxied_auth_headers(client), follow_redirects=False
    ).status_code == 401
