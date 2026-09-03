from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.knowledge.models import MemoryCategory
from ai_hq.knowledge.service import KnowledgeService
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
        csrf = record.csrf_token
    return {"Cookie": f"ai_hq_session={token}"}, csrf


def seed_memory(factory):
    return KnowledgeService(factory).create_memory(
        category=MemoryCategory.PROCEDURE,
        content="Verify backups before deployment.",
        owner_scope="shared",
        provenance={"kind": "user_confirmed", "reference": "runbook:test"},
        confidence=1.0,
        verification_state="confirmed",
        visibility="shared",
    )


def test_knowledge_api_requires_authentication_before_payload_validation():
    client, factory = build_client()
    memory = seed_memory(factory)
    assert client.get("/api/knowledge").status_code == 401
    assert client.get(f"/api/knowledge/{memory.id}").status_code == 401
    assert client.post("/api/knowledge", content=b"not-json").status_code == 401
    assert client.patch(f"/api/knowledge/{memory.id}", content=b"not-json").status_code == 401
    assert client.delete(f"/api/knowledge/{memory.id}").status_code == 401


def test_authenticated_list_and_detail_expose_provenance_and_verification():
    client, factory = build_client()
    memory = seed_memory(factory)
    auth, _csrf = login(client, factory)

    listing = client.get("/api/knowledge?q=backups", headers=auth)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [memory.id]
    assert listing.json()[0]["verification_state"] == "confirmed"

    detail = client.get(f"/api/knowledge/{memory.id}", headers=auth)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["provenance"]["reference"] == "runbook:test"
    assert payload["confidence"] == 1.0
    assert payload["revision"] == 1


def test_knowledge_mutations_require_csrf_and_support_lifecycle_controls():
    client, factory = build_client()
    auth, csrf = login(client, factory)

    payload = {
        "category": "working_memory",
        "content": "Investigate storage warning.",
        "owner_scope": "agent:sysadmin",
        "provenance": {"kind": "system_observation", "reference": "alert:test"},
        "confidence": 0.8,
        "visibility": "private",
    }
    assert client.post("/api/knowledge", headers=auth, json=payload).status_code == 403

    created = client.post(
        "/api/knowledge",
        headers={**auth, "x-csrf-token": csrf},
        json=payload,
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    updated = client.patch(
        f"/api/knowledge/{memory_id}",
        headers={**auth, "x-csrf-token": csrf},
        json={"content": "Investigate storage and backup warning."},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2

    locked = client.post(
        f"/api/knowledge/{memory_id}/lock",
        headers={**auth, "x-csrf-token": csrf},
        json={"locked": True},
    )
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    blocked_delete = client.delete(
        f"/api/knowledge/{memory_id}", headers={**auth, "x-csrf-token": csrf}
    )
    assert blocked_delete.status_code == 409

    client.post(
        f"/api/knowledge/{memory_id}/lock",
        headers={**auth, "x-csrf-token": csrf},
        json={"locked": False},
    )
    deleted = client.delete(
        f"/api/knowledge/{memory_id}", headers={**auth, "x-csrf-token": csrf}
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/knowledge/{memory_id}", headers=auth).status_code == 404


def test_contradiction_api_keeps_original_and_surfaces_review_item():
    client, factory = build_client()
    original = seed_memory(factory)
    auth, csrf = login(client, factory)

    response = client.post(
        f"/api/knowledge/{original.id}/contradictions",
        headers={**auth, "x-csrf-token": csrf},
        json={
            "content": "Backups should be verified after deployment.",
            "provenance": {"kind": "system_observation", "reference": "probe:test"},
            "confidence": 0.9,
        },
    )
    assert response.status_code == 201
    contradiction = response.json()
    assert contradiction["contradicts_memory_id"] == original.id
    assert contradiction["verification_state"] == "needs_review"

    detail = client.get(f"/api/knowledge/{original.id}", headers=auth)
    assert detail.json()["content"] == "Verify backups before deployment."
