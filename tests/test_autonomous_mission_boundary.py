from pathlib import Path


def test_autonomous_executor_has_no_direct_host_or_shell_execution():
    source = Path("src/ai_hq/missions/executor.py").read_text()

    forbidden = (
        "subprocess.",
        "os.system(",
        "os.popen(",
        "HostHelper",
        "host_adapter",
        ".adapter.execute(",
    )

    for token in forbidden:
        assert token not in source


def test_autonomous_executor_routes_execution_through_gateway():
    source = Path("src/ai_hq/missions/executor.py").read_text()

    assert "self.gateway.execute(" in source
    assert "ToolRequest(" in source
