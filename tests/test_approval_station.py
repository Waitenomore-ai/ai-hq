"""Approval Station acceptance tests (handover report, section 21).

Pins that the human-facing approval layer shows the exact pending candidate,
its files/change summary and QA result, provides approve/deny controls bound
to the exact candidate reference, and retains session/CSRF/origin
protections. There is deliberately no "approve latest" action.
"""

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

    def get(self, key):
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
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
        environment="development",
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


def seed_delivery_approval(factory, *, expires_at=None):
    mission = MissionService(factory).create_mission(
        title="Approval Station",
        description="Delivery candidate approval test.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.AMBER,
    )
    approval = ApprovalService(factory).create_request(
        mission_id=mission.id,
        requester_agent="qa",
        action="approve_delivery_change",
        target="candidate-abc123",
        risk=MissionRisk.AMBER,
        action_plan={
            "change_ref": "candidate-abc123",
            "summary": "Reduce mobile menu spacing",
            "changed_files": ["public/css/mobile-member.css"],
            "developer_evidence": {"candidate_digest": "sha256:feedbeef"},
            "qa_evidence": {"result": "PASSED", "tests": "12 passed"},
        },
        expires_at=(expires_at or datetime.now(UTC) + timedelta(hours=24)),
    )
    return mission, approval


def test_expired_approval_can_be_decided_but_never_authorizes():
    client, factory = build_client()
    mission, approval = seed_delivery_approval(
        factory,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    service = ApprovalService(factory)
    decided = service.decide(approval.id, "approved")
    assert decided.state.value == "approved"
    assert not service.is_approved(mission.id, approval.action_fingerprint)


def test_decide_api_requires_authentication():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    response = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved"},
    )
    assert response.status_code == 401


def test_decide_api_requires_csrf_token():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, _csrf = login(client, factory)
    response = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved"},
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_decide_api_approves_the_exact_candidate():
    client, factory = build_client()
    mission, approval = seed_delivery_approval(factory)
    auth_headers, csrf = login(client, factory)
    response = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved"},
        headers={**auth_headers, "Origin": "https://testserver", "x-csrf-token": csrf},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == approval.id
    assert payload["state"] == "approved"
    assert payload["action_plan"]["change_ref"] == "candidate-abc123"
    service = ApprovalService(factory)
    assert service.is_approved(mission.id, approval.action_fingerprint)


def test_decide_api_denies_and_cannot_be_redecided():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, csrf = login(client, factory)
    headers = {**auth_headers, "Origin": "https://testserver", "x-csrf-token": csrf}
    denied = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "denied"},
        headers=headers,
    )
    assert denied.status_code == 200
    assert denied.json()["state"] == "denied"
    again = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert again.status_code == 409


def test_decide_api_returns_410_for_expired_request():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(
        factory,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    auth_headers, csrf = login(client, factory)
    response = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved"},
        headers={**auth_headers, "Origin": "https://testserver", "x-csrf-token": csrf},
    )
    assert response.status_code == 410


def test_decide_api_returns_404_for_unknown_request():
    client, factory = build_client()
    auth_headers, csrf = login(client, factory)
    response = client.post(
        "/api/approvals/does-not-exist/decide",
        json={"decision": "approved"},
        headers={**auth_headers, "Origin": "https://testserver", "x-csrf-token": csrf},
    )
    assert response.status_code == 404


def test_decide_api_rejects_unknown_decision_value():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, csrf = login(client, factory)
    response = client.post(
        f"/api/approvals/{approval.id}/decide",
        json={"decision": "approved-latest"},
        headers={**auth_headers, "Origin": "https://testserver", "x-csrf-token": csrf},
    )
    assert response.status_code == 422


def test_approval_page_requires_authentication():
    client, factory = build_client()
    seed_delivery_approval(factory)
    response = client.get("/approvals", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_approval_page_shows_exact_candidate_files_and_qa_result():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, _csrf = login(client, factory)
    response = client.get("/approvals", headers=auth_headers)
    assert response.status_code == 200
    body = response.text
    assert approval.target in body
    assert "candidate-abc123" in body
    assert "Reduce mobile menu spacing" in body
    assert "public/css/mobile-member.css" in body
    assert "12 passed" in body
    assert "Approve this candidate" in body
    assert "Deny" in body


def test_approval_page_hides_controls_after_decision():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, csrf = login(client, factory)
    headers = {**auth_headers, "Origin": "https://testserver"}
    decided = client.post(
        f"/approvals/{approval.id}/decide",
        data={"decision": "approve", "csrf_token": csrf},
        headers=headers,
        follow_redirects=False,
    )
    assert decided.status_code == 303
    page = client.get("/approvals", headers=auth_headers)
    assert page.status_code == 200
    assert page.text.count("Approve this candidate") == 0
    assert "approved" in page.text


def test_approval_form_requires_csrf_token():
    client, factory = build_client()
    _mission, approval = seed_delivery_approval(factory)
    auth_headers, _csrf = login(client, factory)
    missing = client.post(
        f"/approvals/{approval.id}/decide",
        data={"decision": "approve"},
        headers={**auth_headers, "Origin": "https://testserver"},
    )
    assert missing.status_code == 422
    wrong = client.post(
        f"/approvals/{approval.id}/decide",
        data={"decision": "approve", "csrf_token": "wrong-token"},
        headers={**auth_headers, "Origin": "https://testserver"},
    )
    assert wrong.status_code == 403
    assert ApprovalService(factory).get_request(approval.id).state.value == "pending"
