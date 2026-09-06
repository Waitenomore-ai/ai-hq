import ast
from pathlib import Path

DELIVERY_MODULES = (
    Path("src/ai_hq/delivery/agent_runner.py"),
    Path("src/ai_hq/delivery/candidate_verifier.py"),
    Path("src/ai_hq/delivery/model_agents.py"),
    Path("src/ai_hq/delivery/repository_workspace.py"),
    Path("src/ai_hq/delivery/runtime.py"),
    Path("src/ai_hq/delivery/service.py"),
)

SANDBOX_MODULE = Path("src/ai_hq/delivery/repository_sandbox.py")

FORBIDDEN_IMPORT_PREFIXES = (
    "ai_hq.host_helper",
    "ai_hq.operations",
    "ai_hq.tool_gateway",
    "subprocess",
)

SANDBOX_FORBIDDEN_IMPORT_PREFIXES = (
    "ai_hq.host_helper",
    "ai_hq.operations",
    "ai_hq.tool_gateway",
    "docker",
    "systemd",
)

FORBIDDEN_CALL_NAMES = {
    "system",
    "popen",
    "run",
    "Popen",
    "deploy",
    "rollback",
    "restart",
}


def _source_tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def test_delivery_candidate_modules_do_not_import_production_execution_paths():
    for path in DELIVERY_MODULES:
        tree = _source_tree(path)

        for name in _import_names(tree):
            assert not name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
                f"{path} imports prohibited authority: {name}"
            )


def test_only_repository_sandbox_may_import_subprocess():
    delivery_root = Path("src/ai_hq/delivery")
    subprocess_importers = []

    for path in sorted(delivery_root.glob("*.py")):
        tree = _source_tree(path)
        if any(name.startswith("subprocess") for name in _import_names(tree)):
            subprocess_importers.append(path)

    assert subprocess_importers == [SANDBOX_MODULE]


def test_repository_sandbox_cannot_import_production_authority():
    tree = _source_tree(SANDBOX_MODULE)

    for name in _import_names(tree):
        assert not name.startswith(SANDBOX_FORBIDDEN_IMPORT_PREFIXES), (
            f"{SANDBOX_MODULE} imports prohibited production authority: {name}"
        )


def test_delivery_candidate_modules_do_not_call_production_execution_primitives():
    for path in DELIVERY_MODULES:
        tree = _source_tree(path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            called = node.func
            if isinstance(called, ast.Name):
                name = called.id
            elif isinstance(called, ast.Attribute):
                name = called.attr
            else:
                continue

            assert name not in FORBIDDEN_CALL_NAMES, (
                f"{path} calls prohibited execution primitive: {name}"
            )


def test_repository_sandbox_has_no_public_command_or_deployment_api():
    from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox

    exposed = {name for name in dir(IsolatedRepositorySandbox) if not name.startswith("_")}
    forbidden = {
        "run",
        "command",
        "shell",
        "execute",
        "execute_shell",
        "restart",
        "deploy",
        "rollback",
        "push",
        "merge",
    }

    assert forbidden.isdisjoint(exposed)
    assert {"prepare", "apply_changes", "snapshot", "run_tests"}.issubset(exposed)


def test_repository_workspace_protocol_has_no_generic_command_api():
    from ai_hq.delivery.repository_workspace import RepositoryWorkspaceService

    exposed = set(dir(RepositoryWorkspaceService))
    forbidden = {
        "run",
        "command",
        "shell",
        "execute",
        "execute_shell",
        "restart",
        "deploy",
        "rollback",
        "push",
        "merge",
    }

    assert forbidden.isdisjoint(exposed)
