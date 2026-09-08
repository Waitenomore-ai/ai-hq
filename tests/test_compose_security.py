from pathlib import Path

import yaml

RUNTIME_BIND = "/run/ai-hq:/run/ai-hq:ro"
MCP_RUNTIME_BIND = "/run/dripvid-mcp:/run/dripvid-mcp:ro"


def load_compose() -> dict:
    return yaml.safe_load(Path("compose.yaml").read_text())


def test_host_helper_runtime_is_mounted_read_only_only_into_worker():
    services = load_compose()["services"]
    worker_volumes = services["worker"].get("volumes", [])
    web_volumes = services["web"].get("volumes", [])

    assert RUNTIME_BIND in worker_volumes
    assert all("/run/ai-hq" not in str(volume) for volume in web_volumes)


def test_ai_hq_compose_has_no_docker_socket_or_privileged_service():
    services = load_compose()["services"]
    for service in services.values():
        volumes = service.get("volumes", [])
        assert all("/var/run/docker.sock" not in str(volume) for volume in volumes)
        assert service.get("privileged") is not True
        assert service.get("network_mode") != "host"


def test_web_receives_only_read_only_repository_mirrors():
    services = load_compose()["services"]
    web_volumes = services["web"].get("volumes", [])

    assert (
        "/opt/ai-hq/repository-mirrors:"
        "/srv/ai-hq/repository-mirrors:ro"
    ) in web_volumes

    assert all(
        "/srv/ai-hq/repository-sandboxes"
        not in str(volume)
        for volume in web_volumes
    )


def test_dripvid_mcp_socket_and_token_are_exposed_only_to_worker():
    compose = load_compose()
    services = compose["services"]
    web = services["web"]
    worker = services["worker"]

    assert MCP_RUNTIME_BIND in worker.get("volumes", [])
    assert all("/run/dripvid-mcp" not in str(volume) for volume in web.get("volumes", []))

    worker_secrets = worker.get("secrets", [])
    assert {
        "source": "dripvid_mcp_token",
        "target": "dripvid-mcp-token",
        "mode": 0o400,
    } in worker_secrets
    assert all(
        secret.get("source") != "dripvid_mcp_token"
        for secret in web.get("secrets", [])
        if isinstance(secret, dict)
    )

    assert compose["secrets"]["dripvid_mcp_token"]["file"] == (
        "${AI_HQ_DRIPVID_MCP_TOKEN_SOURCE:-/dev/null}"
    )
