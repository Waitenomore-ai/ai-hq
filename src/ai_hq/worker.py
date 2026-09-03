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
from ai_hq.queue import redis_ping
from ai_hq.safety.service import SafetyService


def execution_allowed(mode: OperatingMode) -> bool:
    return mode is not OperatingMode.FREEZE


class _UnavailableHostHelperClient:
    def execute(self, _request):
        raise HostHelperError("helper_not_configured")


def build_department_runner(settings: Settings) -> DepartmentRunner:
    session_factory = get_session_factory()
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


def run_worker() -> int:
    settings = get_settings()
    if not redis_ping():
        return 1
    if not execution_allowed(settings.operating_mode):
        return 0

    runner = build_department_runner(settings)
    while execution_allowed(settings.operating_mode):
        if not runner.run_once():
            time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_worker())
