from fastapi.testclient import TestClient

from ai_hq.app import create_app


def test_liveness_is_process_only():
    client = TestClient(create_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_dependency_state():
    app = create_app(database_probe=lambda: True, redis_probe=lambda: True)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "redis": "ok"}


def test_readiness_fails_closed_when_dependency_is_down():
    app = create_app(database_probe=lambda: True, redis_probe=lambda: False)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "ok",
        "redis": "unavailable",
    }
