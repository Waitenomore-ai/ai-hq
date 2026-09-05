import time

from ai_hq.agents.registry import AgentRegistry
from ai_hq.config import OperatingMode, Settings, get_settings
from ai_hq.db import get_session_factory
from ai_hq.departments.runner import DepartmentRunner
from ai_hq.departments.sysadmin import SysAdminService
from ai_hq.host_helper.client import HostHelperClient, HostHelperError
from ai_hq.host_helper.contracts import HostAllowLists
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.service import MissionService
from ai_hq.delivery.runtime import DeliveryRuntime
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.executor import MissionExecutor
from ai_hq.missions.worker import AutonomousMissionRunner
from ai_hq.operations.adapters import ServiceLogsAdapter, ServiceStatusAdapter, SystemHealthAdapter
from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.tool_gateway.registry import ToolRegistry
from ai_hq.tool_gateway.service import ToolGateway
from ai_hq.queue import redis_ping
from ai_hq.safety.service import SafetyService
from ai_hq.system_state import ensure_system_state


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



def build_autonomous_mission_runner(
    settings: Settings,
    *,
    session_factory=None,
) -> AutonomousMissionRunner:
    """
    Build the autonomous mission execution path.

    Autonomous execution is always:

        AutonomousMissionRunner -> MissionExecutor -> ToolGateway

    The default worker registry is intentionally empty. Real operational
    capabilities remain fail-closed until trusted production configuration
    is explicitly installed and verified.
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

        targets = OperationalTargetRegistry([
            OperationalTarget(
                key="ai-hq",
                service_unit="ai-hq",
                log_unit="ai-hq",
                allowed_capabilities=frozenset({
                    "system.health.read",
                    "service.status.read",
                    "service.logs.read",
                }),
            )
        ])

        registry = ToolRegistry([
            SystemHealthAdapter(targets=targets, transport=transport),
            ServiceStatusAdapter(targets=targets, transport=transport),
            ServiceLogsAdapter(targets=targets, transport=transport),
        ])

    gateway = ToolGateway(
        session_factory,
        registry=registry,
        safety=safety,
        ledger=ledger,
    )

    executor = MissionExecutor(
        missions,
        gateway,
    )

    delivery_runtime = DeliveryRuntime(
        DeliveryService(session_factory)
    )

    return AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runtime=delivery_runtime,
    )


def run_worker_iteration(
    *,
    autonomous_runner: AutonomousMissionRunner,
    department_runner: DepartmentRunner,
) -> bool:
    """
    Execute at most one unit of worker activity.

    Persisted autonomous plans are routed through MissionExecutor and
    ToolGateway first. Legacy unplanned missions remain handled by the
    existing DepartmentRunner fallback.
    """
    if autonomous_runner.run_once() is not None:
        return True

    return bool(department_runner.run_once())

def run_worker() -> int:
    settings = get_settings()

    if not redis_ping():
        return 1

    autonomous_runner = None
    department_runner = None

    while True:
        settings = get_settings()

        if not execution_allowed(settings.operating_mode):
            time.sleep(5)
            continue

        if autonomous_runner is None:
            autonomous_runner = build_autonomous_mission_runner(settings)

        if department_runner is None:
            department_runner = build_department_runner(settings)

        worked = run_worker_iteration(
            autonomous_runner=autonomous_runner,
            department_runner=department_runner,
        )

        if not worked:
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(run_worker())
