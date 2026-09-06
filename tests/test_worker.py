from types import SimpleNamespace

import pytest

from ai_hq import worker
from ai_hq.config import OperatingMode
from ai_hq.worker import execution_allowed


def test_freeze_mode_blocks_worker_execution():
    assert execution_allowed(OperatingMode.FREEZE) is False


def test_safe_mode_allows_read_only_worker_loop():
    assert execution_allowed(OperatingMode.SAFE) is True


def test_worker_stays_alive_in_safe_mode(monkeypatch):
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(operating_mode=OperatingMode.SAFE),
    )
    monkeypatch.setattr(worker, "redis_ping", lambda: True)

    sleeps = 0

    class StopProbe(RuntimeError):
        pass

    def probe_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise StopProbe

    monkeypatch.setattr(worker.time, "sleep", probe_sleep)
    monkeypatch.setattr(
        worker,
        "build_department_runner",
        lambda _settings: SimpleNamespace(run_once=lambda: False),
    )
    monkeypatch.setattr(
        worker,
        "build_autonomous_mission_runner",
        lambda _settings: SimpleNamespace(run_once=lambda: None),
    )

    with pytest.raises(StopProbe):
        worker.run_worker()

    assert sleeps == 2


def test_worker_repeatedly_runs_missions_and_sleeps_only_when_idle(monkeypatch):
    settings = SimpleNamespace(operating_mode=OperatingMode.SAFE)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "redis_ping", lambda: True)

    calls = 0
    sleeps = 0

    class StopProbe(RuntimeError):
        pass

    class FakeRunner:
        def run_once(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                return True
            if calls == 2:
                return False
            raise StopProbe

    runner = FakeRunner()
    builds = 0

    def build_runner(_settings):
        nonlocal builds
        builds += 1
        return runner

    def probe_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1

    monkeypatch.setattr(worker.time, "sleep", probe_sleep)
    monkeypatch.setattr(
        worker,
        "build_autonomous_mission_runner",
        lambda _settings: SimpleNamespace(run_once=lambda: None),
    )
    monkeypatch.setattr(worker, "build_department_runner", build_runner)

    with pytest.raises(StopProbe):
        worker.run_worker()

    assert builds == 1
    assert calls == 3
    assert sleeps == 1


def test_freeze_mode_never_constructs_or_runs_department_runner(monkeypatch):
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(operating_mode=OperatingMode.FREEZE),
    )
    monkeypatch.setattr(worker, "redis_ping", lambda: True)

    def forbidden(_settings):
        raise AssertionError("frozen worker must not construct runner")

    monkeypatch.setattr(worker, "build_department_runner", forbidden)

    class StopProbe(RuntimeError):
        pass

    monkeypatch.setattr(
        worker.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopProbe()),
    )

    with pytest.raises(StopProbe):
        worker.run_worker()


def isolated_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from ai_hq.db import Base

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    return sessionmaker(bind=engine, expire_on_commit=False)


def test_production_autonomous_runner_fails_closed_without_workspace_backend():
    class FakeSettings:
        host_helper_credential = None
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert runner.delivery_runner is None


def test_worker_bootstrap_does_not_wire_direct_delivery_runtime_bridge():
    import inspect

    source = inspect.getsource(worker.build_autonomous_mission_runner)

    assert "DeliveryRuntime" not in source
    assert "handoff_to_developer" not in source
