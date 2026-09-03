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


def test_web_is_published_only_on_localhost_8090():
    compose = load_compose()
    ports = compose["services"]["web"]["ports"]
    assert ports == ["127.0.0.1:8090:8000"]
    assert all("0.0.0.0" not in str(port) for port in ports)
    assert "8090:8000" not in ports


def test_postgres_and_redis_use_named_volumes_without_host_ports():
    compose = load_compose()
    services = compose["services"]
    assert "postgres_data:/var/lib/postgresql/data" in services["postgres"]["volumes"]
    assert "redis_data:/data" in services["redis"]["volumes"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis"]


def test_compose_accepts_external_production_env_file():
    text = Path("compose.yaml").read_text()
    assert "AI_HQ_ENV_FILE" in text
    env_example = Path(".env.example").read_text()
    assert "AI_HQ_ROOT_PATH=/ai-hq" in env_example
