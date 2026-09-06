from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ai_hq.worker as worker
from ai_hq.db import Base
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox
from ai_hq.missions.executor import MissionExecutor
from ai_hq.missions.worker import AutonomousMissionRunner
from ai_hq.tool_gateway.service import ToolGateway


def isolated_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


class FakeSettings:
    host_helper_credential = None
    host_helper_socket = "/unused"
    ai_hq_repository_source_path = None
    repository_sandbox_root_path = None


class FakeModelClient:
    def reply(self, system_prompt, messages):
        raise AssertionError("model must not be invoked while wiring the worker")


def test_real_worker_exposes_autonomous_runner_builder():
    assert hasattr(worker, "build_autonomous_mission_runner")


def test_real_worker_autonomous_builder_returns_gateway_backed_runner():
    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert isinstance(runner, AutonomousMissionRunner)
    assert isinstance(runner.executor, MissionExecutor)
    assert isinstance(runner.executor.gateway, ToolGateway)


def test_autonomous_runner_builder_does_not_return_legacy_department_runner():
    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert not isinstance(runner, worker.DepartmentRunner)


def test_configured_worker_wires_verified_ai_hq_repository_sandbox(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "example.py").write_text("VALUE = 1\n")
    sandbox_root = tmp_path / "sandbox"

    class ConfiguredSettings(FakeSettings):
        ai_hq_repository_source_path = Path(source).resolve()
        repository_sandbox_root_path = Path(sandbox_root).resolve()

    monkeypatch.setattr(
        worker,
        "build_chat_model_client",
        lambda settings: FakeModelClient(),
        raising=False,
    )

    runner = worker.build_autonomous_mission_runner(
        ConfiguredSettings(),
        session_factory=isolated_session_factory(),
    )

    assert isinstance(runner.delivery_runner, DeliveryAgentRunner)
    assert isinstance(
        runner.delivery_runner.workspace_service,
        IsolatedRepositorySandbox,
    )
    workspace = runner.delivery_runner.workspace_service.prepare(mission_id="mission-1")
    assert workspace.repository == "ai-hq"
    assert workspace.workspace_id
    assert sandbox_root.exists()


def test_worker_stays_fail_closed_when_repository_sandbox_is_unconfigured(monkeypatch):
    monkeypatch.setattr(
        worker,
        "build_chat_model_client",
        lambda settings: FakeModelClient(),
        raising=False,
    )

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert runner.delivery_runner is None


class FakeAutonomousRunner:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    def run_once(self):
        self.calls += 1
        return self.result


class FakeDepartmentRunner:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    def run_once(self):
        self.calls += 1
        return self.result


def test_worker_iteration_prefers_autonomous_execution():
    autonomous = FakeAutonomousRunner(result=object())
    legacy = FakeDepartmentRunner(result=object())

    result = worker.run_worker_iteration(
        autonomous_runner=autonomous,
        department_runner=legacy,
    )

    assert result is True
    assert autonomous.calls == 1
    assert legacy.calls == 0


def test_worker_iteration_falls_back_to_legacy_unplanned_work():
    autonomous = FakeAutonomousRunner(result=None)
    legacy = FakeDepartmentRunner(result=object())

    result = worker.run_worker_iteration(
        autonomous_runner=autonomous,
        department_runner=legacy,
    )

    assert result is True
    assert autonomous.calls == 1
    assert legacy.calls == 1


def test_worker_iteration_reports_idle_when_neither_path_has_work():
    autonomous = FakeAutonomousRunner(result=None)
    legacy = FakeDepartmentRunner(result=None)

    result = worker.run_worker_iteration(
        autonomous_runner=autonomous,
        department_runner=legacy,
    )

    assert result is False
    assert autonomous.calls == 1
    assert legacy.calls == 1


def test_autonomous_worker_registers_read_only_operational_capabilities():
    class HostSettings(FakeSettings):
        host_helper_credential = "test-credential"
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        HostSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("system.health.read") is not None
    assert registry.resolve("service.status.read") is not None
    assert registry.resolve("service.logs.read") is not None


def test_autonomous_worker_keeps_mutating_operations_unregistered():
    class HostSettings(FakeSettings):
        host_helper_credential = "test-credential"
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        HostSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("service.restart") is None
    assert registry.resolve("deployment.deploy") is None
    assert registry.resolve("deployment.rollback") is None


def test_autonomous_worker_stays_fail_closed_without_host_helper_credential():
    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("system.health.read") is None
    assert registry.resolve("service.status.read") is None
    assert registry.resolve("service.logs.read") is None
