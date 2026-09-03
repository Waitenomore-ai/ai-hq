from pathlib import Path

import yaml


def load_compose():
    return yaml.safe_load(Path("compose.yaml").read_text())


def test_compose_has_only_core_services_and_no_docker_socket():
    compose = load_compose()
    services = compose["services"]
    assert set(services) == {"web", "worker", "postgres", "redis"}
    assert "ports" in services["web"]
    assert "ports" not in services["worker"]
    for name in ("web", "worker"):
        mounts = services[name].get("volumes", [])
        assert all("/var/run/docker.sock" not in str(mount) for mount in mounts)


def test_postgres_and_redis_use_named_volumes():
    compose = load_compose()
    services = compose["services"]
    assert "postgres_data:/var/lib/postgresql/data" in services["postgres"]["volumes"]
    assert "redis_data:/data" in services["redis"]["volumes"]
