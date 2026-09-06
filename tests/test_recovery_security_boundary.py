import ast
from pathlib import Path

from ai_hq.host_helper.contracts import HostAllowLists, validate_request
from ai_hq.host_helper.executor import DRIPVID_READINESS_URL, RECOVERY_SERVICE_UNITS
from ai_hq.host_helper.server import _default_allow_lists


RECOVERY_PACKAGE = Path("src/ai_hq/recovery")
RECOVERY_BOOTSTRAP = RECOVERY_PACKAGE / "bootstrap.py"
WORKER = Path("src/ai_hq/worker.py")


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def _called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_recovery_domain_modules_have_no_shell_or_host_mutation_authority():
    for path in RECOVERY_PACKAGE.glob("*.py"):
        imports = _imported_modules(path)
        assert "subprocess" not in imports
        assert "os" not in imports
        assert "shlex" not in imports

        calls = _called_names(path)
        assert "service_recover" not in calls
        assert "service_restart" not in calls
        assert "deployment_deploy" not in calls
        assert "deployment_rollback" not in calls


def test_worker_registers_recovery_but_cannot_execute_host_mutation_directly():
    imports = _imported_modules(WORKER)
    assert "subprocess" not in imports
    assert "ai_hq.host_helper.executor" not in imports

    calls = _called_names(WORKER)
    assert "service_recover" not in calls
    assert "service_restart" not in calls
    assert "deployment_deploy" not in calls
    assert "deployment_rollback" not in calls


def test_recovery_component_to_systemd_mapping_is_fixed_server_side():
    assert RECOVERY_SERVICE_UNITS == {
        "app": "dripvid.service",
        "mcp": "dripvid-mcp.service",
        "proxy": "nginx.service",
        "tunnel": "cloudflared.service",
        "database": "postgresql.service",
    }


def test_diagnostic_only_targets_are_not_generic_mutation_targets():
    allow_lists = _default_allow_lists()

    assert allow_lists.diagnostic_services == frozenset(
        {"dripvid-mcp", "cloudflared", "postgresql"}
    )
    assert allow_lists.diagnostic_services.isdisjoint(allow_lists.services)
    assert allow_lists.diagnostic_logs.isdisjoint(allow_lists.services)


def test_dripvid_readiness_endpoint_is_fixed_to_host_loopback():
    assert DRIPVID_READINESS_URL == "http://127.0.0.1:3000/health/ready"


def test_dripvid_readiness_contract_accepts_no_caller_controlled_network_input():
    allow_lists = HostAllowLists(
        services=frozenset({"dripvid"}),
        containers=frozenset(),
        logs=frozenset({"dripvid"}),
    )

    request = validate_request(
        {"capability": "dripvid.readiness", "target": None, "params": {}},
        allow_lists,
    )
    assert request.target is None
    assert request.params == {}

    for payload in (
        {
            "capability": "dripvid.readiness",
            "target": "dripvid",
            "params": {},
        },
        {
            "capability": "dripvid.readiness",
            "target": None,
            "params": {"url": "http://172.23.0.1:3000/health/ready"},
        },
        {
            "capability": "dripvid.readiness",
            "target": None,
            "params": {"host": "172.23.0.1"},
        },
        {
            "capability": "dripvid.readiness",
            "target": None,
            "params": {"path": "/health/live"},
        },
    ):
        try:
            validate_request(payload, allow_lists)
        except ValueError:
            pass
        else:
            raise AssertionError("readiness capability accepted caller-controlled network input")


def test_production_recovery_bootstrap_does_not_use_container_local_http_probe():
    source = RECOVERY_BOOTSTRAP.read_text(encoding="utf-8")
    imports = _imported_modules(RECOVERY_BOOTSTRAP)
    calls = _called_names(RECOVERY_BOOTSTRAP)

    assert "httpx" not in imports
    assert "DripVidReadinessProbe" not in calls
    assert "recovery_dripvid_ready_url" not in source
    assert "HostHelperDripVidReadinessProbe" in calls
