import time

from ai_hq.agents.registry import AgentRegistry
from ai_hq.chat.model_client import build_chat_model_client
from ai_hq.config import OperatingMode, Settings, get_settings
from ai_hq.db import get_session_factory
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent, ModelBackedQAAgent
from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
)
from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox
from ai_hq.delivery.runtime import DeliveryRuntime
from ai_hq.delivery.service import DeliveryService
from ai_hq.departments.runner import DepartmentRunner
from ai_hq.departments.sysadmin import SysAdminService
from ai_hq.host_helper.client import HostHelperClient, HostHelperError
from ai_hq.host_helper.contracts import HostAllowLists
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.executor import MissionExecutor
from ai_hq.missions.service import MissionService
from ai_hq.missions.worker import AutonomousMissionRunner
from ai_hq.operations.adapters import (
    ServiceLogsAdapter,
    ServiceRecoverAdapter,
    ServiceStatusAdapter,
    SystemHealthAdapter,
)
from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.queue import redis_ping
from ai_hq.recovery.bootstrap import RecoveryWorkerCoordinator, build_recovery_coordinator
from ai_hq.safety.service import SafetyService
from ai_hq.system_state import ensure_system_state
from ai_hq.tool_gateway.registry import ToolRegistry
from ai_hq.tool_gateway.service import ToolGateway


def execution_allowed(mode: OperatingMode) -> bool:
    return mode is not OperatingMode.FREEZE


class _UnavailableHostHelperClient:
    def execute(self, _request):
        raise HostHelperError("helper_not_configured")


def build_department_runner(settings: Settings) -> DepartmentRunner:
    session_factory = get_session_factory()
    ensure_system_state(session_factory)
    ledger = OperationsLedger(session_factory)
    missions = MissionService(session_factory, ledger)
    agents = AgentRegistry(session_factory)
    agents.ensure_phase1_agents()
    safety = SafetyService(session_factory, ledger=ledger)
    if settings.host_helper_credential:
        helper = HostHelperClient(
            settings.host_helper_socket,
            settings.host_helper_credential,
        )
    else:
        helper = _UnavailableHostHelperClient()
    sysadmin = SysAdminService(
        safety=safety,
        helper=helper,
        ledger=ledger,
        allow_lists=HostAllowLists(
            services=frozenset({"ai-hq", "nginx", "dripvid"}),
            containers=frozenset({"ai-hq-web", "ai-hq-worker", "dripvid"}),
            logs=frozenset({"ai-hq", "nginx", "dripvid"}),
        ),
    )
    return DepartmentRunner(
        mission_service=missions,
        agent_registry=agents,
        sysadmin=sysadmin,
    )


def _build_verified_delivery_runner(
    settings: Settings,
    *,
    session_factory,
) -> DeliveryAgentRunner | None:
    source_path = getattr(settings, "ai_hq_repository_source_path", None)
    sandbox_root = getattr(settings, "repository_sandbox_root_path", None)
    if source_path is None or sandbox_root is None:
        return None

    model_client = build_chat_model_client(settings)
    if model_client is None:
        return None

    profile = build_ai_hq_repository_profile(source_path=source_path)
    profile_registry = RepositoryProfileRegistry((profile,))
    sandbox = IsolatedRepositorySandbox(
        profile_registry=profile_registry,
        repository_key="ai-hq",
        sandbox_root=sandbox_root,
    )
    runtime = DeliveryRuntime(DeliveryService(session_factory))

    return DeliveryAgentRunner(
        runtime=runtime,
        developer=ModelBackedDeveloperAgent(model_client),
        qa=ModelBackedQAAgent(model_client),
        candidate_verifier=CandidateVerifier(),
        workspace_service=sandbox,
    )


def build_autonomous_mission_runner(
    settings: Settings,
    *,
    session_factory=None,
) -> AutonomousMissionRunner:
    """Build the guarded autonomous mission execution path.

    Operational mutations remain MissionExecutor -> ToolGateway. Recovery adds
    only the bounded ``service.recover`` capability; verified repository
    delivery remains separately confined to the isolated repository sandbox.
    """
    if session_factory is None:
        session_factory = get_session_factory()

    ensure_system_state(session_factory)

    ledger = OperationsLedger(session_factory)
    missions = MissionService(session_factory, ledger)
    safety = SafetyService(session_factory, ledger=ledger)
    registry = ToolRegistry([])

    if settings.host_helper_credential:
        helper = HostHelperClient(
            settings.host_helper_socket,
            settings.host_helper_credential,
        )
        transport = HostHelperOperationalTransport(helper)
        targets = OperationalTargetRegistry(
            [
                OperationalTarget(
                    key="ai-hq",
                    service_unit="ai-hq",
                    log_unit="ai-hq",
                    allowed_capabilities=frozenset(
                        {
                            "system.health.read",
                            "service.status.read",
                            "service.logs.read",
                        }
                    ),
                ),
                OperationalTarget(
                    key="dripvid",
                    service_unit="dripvid.service",
                    log_unit="dripvid.service",
                    allowed_capabilities=frozenset({"service.recover"}),
                ),
            ]
        )
        registry = ToolRegistry(
            [
                SystemHealthAdapter(targets=targets, transport=transport),
                ServiceStatusAdapter(targets=targets, transport=transport),
                ServiceLogsAdapter(targets=targets, transport=transport),
                ServiceRecoverAdapter(targets=targets, transport=transport),
            ]
        )

    gateway = ToolGateway(
        session_factory,
        registry=registry,
        safety=safety,
        ledger=ledger,
    )
    executor = MissionExecutor(missions, gateway)
    delivery_runner = _build_verified_delivery_runner(
        settings,
        session_factory=session_factory,
    )

    return AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runner=delivery_runner,
    )


def run_worker_iteration(
    *,
    autonomous_runner: AutonomousMissionRunner,
    department_runner: DepartmentRunner,
    recovery_coordinator: RecoveryWorkerCoordinator | None = None,
    settings: Settings | None = None,
) -> bool:
    """Execute at most one unit of worker activity.

    Recovery observation may persist a mission, but autonomous mission
    execution remains the first executable path. Any recovery mutation still
    happens later through MissionExecutor -> ToolGateway.
    """
    recovery_worked = False
    if recovery_coordinator is not None and settings is not None:
        recovery_worked = recovery_coordinator.run_if_due(settings)

    autonomous_result = autonomous_runner.run_once()
    if autonomous_result is not None:
        if recovery_coordinator is not None:
            recovery_coordinator.handle_execution_result(autonomous_result)
        return True

    if department_runner.run_once():
        return True

    return recovery_worked


def run_worker() -> int:
    settings = get_settings()

    if not redis_ping():
        return 1

    autonomous_runner = None
    department_runner = None
    recovery_coordinator = None
    recovery_initialized = False

    while True:
        settings = get_settings()

        if not execution_allowed(settings.operating_mode):
            time.sleep(5)
            continue

        if autonomous_runner is None:
            autonomous_runner = build_autonomous_mission_runner(settings)

        if department_runner is None:
            department_runner = build_department_runner(settings)

        if not recovery_initialized:
            recovery_coordinator = build_recovery_coordinator(settings)
            recovery_initialized = True

        worked = run_worker_iteration(
            autonomous_runner=autonomous_runner,
            department_runner=department_runner,
            recovery_coordinator=recovery_coordinator,
            settings=settings,
        )

        if not worked:
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(run_worker())
