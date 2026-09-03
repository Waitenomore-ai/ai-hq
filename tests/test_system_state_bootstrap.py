from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.app import create_app
from ai_hq.config import Settings
from ai_hq.db import Base
from ai_hq.models.system_state import SystemState


class FakeRedis:
    def get(self, _key):
        return None

    def incr(self, _key):
        return 1

    def expire(self, _key, _seconds):
        return True

    def delete(self, _key):
        return 1


def build_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def build_settings():
    return Settings(
        environment="development",
        database_url="sqlite+pysqlite://",
        redis_url="redis://unused:6379/0",
    )


def test_create_app_bootstraps_missing_system_state_fail_closed():
    factory = build_factory()

    app = create_app(
        settings=build_settings(),
        session_factory=factory,
        redis_client=FakeRedis(),
        database_probe=lambda: True,
        redis_probe=lambda: True,
    )
    TestClient(app)

    with factory() as db:
        state = db.get(SystemState, 1)
        assert state is not None
        assert state.operating_mode == "freeze"
        assert state.simulation_mode is True


def test_create_app_preserves_existing_runtime_system_state():
    factory = build_factory()
    with factory() as db:
        db.add(SystemState(id=1, operating_mode="safe", simulation_mode=False))
        db.commit()

    app = create_app(
        settings=build_settings(),
        session_factory=factory,
        redis_client=FakeRedis(),
        database_probe=lambda: True,
        redis_probe=lambda: True,
    )
    TestClient(app)

    with factory() as db:
        state = db.get(SystemState, 1)
        assert state is not None
        assert state.operating_mode == "safe"
        assert state.simulation_mode is False
