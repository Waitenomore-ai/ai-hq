from pathlib import Path
import yaml


SOCKET_BIND = "/run/ai-hq/host-helper.sock:/run/ai-hq/host-helper.sock"


def load_compose() -> dict:
    return yaml.safe_load(Path("compose.yaml").read_text())


def test_host_helper_socket_is_mounted_only_into_worker():
    services = load_compose()["services"]
    worker_volumes = services["worker"].get("volumes", [])
    web_volumes = services["web"].get("volumes", [])

    assert SOCKET_BIND in worker_volumes
    assert all("host-helper.sock" not in str(volume) for volume in web_volumes)


def test_ai_hq_compose_has_no_docker_socket_or_privileged_service():
    services = load_compose()["services"]
    for service in services.values():
        volumes = service.get("volumes", [])
        assert all("/var/run/docker.sock" not in str(volume) for volume in volumes)
        assert service.get("privileged") is not True
