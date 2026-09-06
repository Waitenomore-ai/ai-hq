from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ai_hq.worker as worker
from ai_hq.agents.registry import AgentRegistry
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.host_helper.contracts import HelperResponse, HostCapability
from ai_hq.operations.targets import OperationalTarget
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.recovery.bootstrap import RecoveryWorkerCoordinator, build_recovery_coordinator


def isolated_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class FakeSettings:
    recovery_enabled = True
    recovery_observe_only = True
    recovery_observation_seconds = 30
    recovery_failure_threshold = 3
    recovery_cooldown_seconds = 300
    recovery_attempt_budget = 2
    recovery_budget_window_seconds = 3600
    recovery_verify_seconds = 60
    recovery_dripvid_ready_url = "http://127.0.0.1:3000/health/ready"
    operating_mode = OperatingMode.SAFE
    host_helper_credential = "test-credential"
    host_helper_socket = "/tmp/test-ai-hq.sock"


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeCycle:
    def __init__(self):
        self.calls = []
        self.execution_results = []

    def run_once(self, *, observe_only):
        self.calls.append(observe_only)
        return True

    def handle_execution_result(self, result):
        self.execution_results.append(result)


def test_disabled_recovery_constructs_no_coordinator():
    settings = FakeSettings()
    settings.recovery_enabled = False

    assert build_recovery_coordinator(
        settings,
        session_factory=isolated_session_factory(),
    ) is None


def test_missing_host_helper_credential_fails_closed():
    settings = FakeSettings()
    settings.host_helper_credential = None

    assert build_recovery_coordinator(
        settings,
        session_factory=isolated_session_factory(),
    ) is None


def test_observe_only_mode_is_forwarded_to_cycle_without_mutating_scheduler():
    clock = Clock()
    cycle = FakeCycle()
    coordinator = RecoveryWorkerCoordinator(cycle, clock=clock)
    settings = FakeSettings()
    settings.recovery_observe_only = True

    assert coordinator.run_if_due(settings) is True
    assert cycle.calls == [True]


def test_recovery_observation_never_runs_faster_than_configured_interval():
    clock = Clock()
    cycle = FakeCycle()
    coordinator = RecoveryWorkerCoordinator(cycle, clock=clock)
    settings = FakeSettings()

    assert coordinator.run_if_due(settings) is True
    assert coordinator.run_if_due(settings) is False
    assert cycle.calls == [True]

    clock.advance(29)
    assert coordinator.run_if_due(settings) is False

    clock.advance(1)
    assert coordinator.run_if_due(settings) is True
    assert cycle.calls == [True, True]


def test_freeze_performs_no_recovery_work():
    clock = Clock()
    cycle = FakeCycle()
    coordinator = RecoveryWorkerCoordinator(cycle, clock=clock)
    settings = FakeSettings()
    settings.operating_mode = OperatingMode.FREEZE

    assert coordinator.run_if_due(settings) is False
    assert cycle.calls == []


def test_worker_observation_does_not_displace_autonomous_mission_processing():
    class Autonomous:
        def __init__(self):
            self.calls = 0
            self.result = SimpleNamespace(mission_id="mission-1", outcome=None)

        def run_once(self):
            self.calls += 1
            return self.result

    class Legacy:
        calls = 0

        def run_once(self):
            self.calls += 1
            return object()

    class Recovery:
        def __init__(self):
            self.observations = 0
            self.results = []

        def run_if_due(self, settings):
            self.observations += 1
            return True

        def handle_execution_result(self, result):
            self.results.append(result)

    autonomous = Autonomous()
    legacy = Legacy()
    recovery = Recovery()
    settings = FakeSettings()

    worked = worker.run_worker_iteration(
        autonomous_runner=autonomous,
        department_runner=legacy,
        recovery_coordinator=recovery,
        settings=settings,
    )

    assert worked is True
    assert recovery.observations == 1
    assert autonomous.calls == 1
    assert legacy.calls == 0
    assert recovery.results == [autonomous.result]


def test_autonomous_worker_registers_only_service_recover_as_new_mutation():
    settings = FakeSettings()
    runner = worker.build_autonomous_mission_runner(
        settings,
        session_factory=isolated_session_factory(),
    )
    registry = runner.executor.gateway.registry

    assert registry.resolve("service.recover") is not None
    assert registry.resolve("service.restart") is None
    assert registry.resolve("deployment.deploy") is None
    assert registry.resolve("deployment.rollback") is None


def test_sysadmin_agent_is_not_auto_granted_recovery_permission():
    factory = isolated_session_factory()
    agents = AgentRegistry(factory)
    agents.ensure_phase1_agents()

    sysadmin = agents.get_by_key("sysadmin")
    assert "service.recover" not in sysadmin.permissions


def test_diagnostic_transport_uses_fixed_host_helper_target_mapping():
    class Client:
        def __init__(self):
            self.requests = []

        def execute(self, request):
            self.requests.append(request)
            return HelperResponse(
                ok=True,
                capability=request.capability,
                target=request.target,
                data={"active_state": "active"},
            )

    client = Client()
    transport = HostHelperOperationalTransport(client)
    target = OperationalTarget(
        key="dripvid-database",
        service_unit="postgresql.service",
        log_unit="postgresql.service",
        allowed_capabilities=frozenset(
            {"service.status.read", "service.logs.read"}
        ),
        host_helper_service_target="postgresql",
        host_helper_log_target="postgresql",
    )

    transport.service_status(target)
    transport.service_logs(target, lines=100)

    assert client.requests[0].target == "postgresql"
    assert client.requests[0].capability is HostCapability.SERVICE_STATUS
    assert client.requests[1].target == "postgresql"
    assert client.requests[1].capability is HostCapability.LOGS_RECENT


def test_recovery_coordinator_constructor_has_no_mutation_transport_dependency():
    parameters = RecoveryWorkerCoordinator.__init__.__annotations__
    serialized = repr(parameters).casefold()
    assert "hosthelper" not in serialized
    assert "toolgateway" not in serialized
