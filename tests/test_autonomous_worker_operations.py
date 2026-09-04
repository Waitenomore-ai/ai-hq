from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.executor import MissionExecutor
from ai_hq.missions.worker import AutonomousMissionRunner
from ai_hq.tool_gateway.service import ToolGateway
import ai_hq.worker as worker



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

def test_real_worker_exposes_autonomous_runner_builder():
    assert hasattr(worker, "build_autonomous_mission_runner")


def test_real_worker_autonomous_builder_returns_gateway_backed_runner(monkeypatch):
    """
    The production worker's autonomous path must be:

        worker -> AutonomousMissionRunner
               -> MissionExecutor
               -> ToolGateway

    It must not route autonomous missions through DepartmentRunner,
    SysAdminService, Host Helper, an adapter, transport, or subprocess
    directly.
    """

    class FakeSettings:
        host_helper_credential = None
        host_helper_socket = "/unused"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert isinstance(runner, AutonomousMissionRunner)
    assert isinstance(runner.executor, MissionExecutor)
    assert isinstance(runner.executor.gateway, ToolGateway)


def test_autonomous_runner_builder_does_not_return_legacy_department_runner():
    class FakeSettings:
        host_helper_credential = None
        host_helper_socket = "/unused"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    assert not isinstance(runner, worker.DepartmentRunner)


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
    class FakeSettings:
        host_helper_credential = "test-credential"
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("system.health.read") is not None
    assert registry.resolve("service.status.read") is not None
    assert registry.resolve("service.logs.read") is not None


def test_autonomous_worker_keeps_mutating_operations_unregistered():
    class FakeSettings:
        host_helper_credential = "test-credential"
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("service.restart") is None
    assert registry.resolve("deployment.deploy") is None
    assert registry.resolve("deployment.rollback") is None


def test_autonomous_worker_stays_fail_closed_without_host_helper_credential():
    class FakeSettings:
        host_helper_credential = None
        host_helper_socket = "/tmp/test-host-helper.sock"

    runner = worker.build_autonomous_mission_runner(
        FakeSettings(),
        session_factory=isolated_session_factory(),
    )

    registry = runner.executor.gateway.registry

    assert registry.resolve("system.health.read") is None
    assert registry.resolve("service.status.read") is None
    assert registry.resolve("service.logs.read") is None
