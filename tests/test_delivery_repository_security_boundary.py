import ast
from pathlib import Path

DELIVERY_MODULES = (
    Path("src/ai_hq/delivery/agent_runner.py"),
    Path("src/ai_hq/delivery/candidate_verifier.py"),
    Path("src/ai_hq/delivery/model_agents.py"),
    Path("src/ai_hq/delivery/repository_workspace.py"),
)

FORBIDDEN_IMPORT_PREFIXES = (
    "ai_hq.host_helper",
    "ai_hq.operations",
    "ai_hq.tool_gateway",
    "subprocess",
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


def test_delivery_candidate_modules_do_not_import_production_execution_paths():
    for path in DELIVERY_MODULES:
        tree = _source_tree(path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue

            for name in names:
                assert not name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
                    f"{path} imports prohibited authority: {name}"
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
    }

    assert forbidden.isdisjoint(exposed)
