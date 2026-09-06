from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "install-host-helper.sh"
SMOKE = ROOT / "deploy" / "check-production.sh"
UNIT = ROOT / "deploy" / "ai-hq-host-helper.service"
DEPLOY = ROOT / "deploy" / "ai-hq-deploy"
COMPOSE = ROOT / "compose.yaml"


def test_host_helper_installer_is_root_only_and_never_accepts_secret_on_command_line():
    text = INSTALLER.read_text()
    assert "EUID" in text
    assert "host-helper.env" in text
    assert "chmod 600" in text or "-m 0600" in text
    assert "read -r -s" in text
    assert "AI_HQ_HOST_HELPER_CREDENTIAL" in text
    assert "$1" not in text
    assert "echo \"$credential\"" not in text
    assert "printf '%s\\n' \"$credential\"" not in text


def test_installer_builds_dedicated_venv_installs_unit_and_waits_for_socket():
    text = INSTALLER.read_text()
    assert "/opt/ai-hq/host-helper-venv" in text
    assert "ai-hq-host-helper.service" in text
    assert "systemctl daemon-reload" in text
    assert "systemctl enable" in text
    assert "test -S /run/ai-hq/host-helper.sock" in text


def test_systemd_helper_has_no_public_network_listener_and_is_hardened():
    text = UNIT.read_text()
    assert "RestrictAddressFamilies=AF_UNIX AF_INET" in text
    assert "IPAddressDeny=any" in text
    assert "IPAddressAllow=127.0.0.1" in text
    assert "AF_INET6" not in text
    assert "NoNewPrivileges=true" in text
    assert "ProtectSystem=strict" in text
    assert "EnvironmentFile=/etc/ai-hq/host-helper.env" in text
    assert "0.0.0.0" not in text
    assert "ListenStream" not in text


def test_compose_keeps_socket_worker_only_without_docker_socket_or_privileged_mode():
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    worker_text = repr(services["worker"])
    web_text = repr(services["web"])
    assert "host-helper.sock" in worker_text
    assert "host-helper.sock" not in web_text
    assert "/var/run/docker.sock" not in COMPOSE.read_text()
    assert all(service.get("privileged") is not True for service in services.values())


def test_deploy_preflights_socket_before_starting_new_worker():
    text = DEPLOY.read_text()
    socket_check = text.index("test -S /run/ai-hq/host-helper.sock")
    compose_up = text.index('compose_release "$RELEASE" up -d --build')
    assert socket_check < compose_up


def test_production_smoke_checks_helper_socket_local_request_and_dripvid_root():
    text = SMOKE.read_text()
    assert 'check_url "DripVid root" "https://dripvid.uk/"' in text
    assert "test -S /run/ai-hq/host-helper.sock" in text
    assert "/etc/ai-hq/host-helper.env" in text
    assert "AF_UNIX" in text
    assert "host.health" in text
    assert "AI_HQ_HOST_HELPER_CREDENTIAL" in text
    assert "docker inspect" in text
    assert "host-helper.sock" in text
    assert "/var/run/docker.sock" in text
