from pathlib import Path


def test_deploy_script_uses_versioned_releases_lock_and_rollback():
    text = Path("deploy/ai-hq-deploy").read_text()
    for required in (
        "BASE=/opt/ai-hq",
        'RELEASES="$BASE/releases"',
        'APP_LINK="$BASE/app"',
        "ENV_FILE=/etc/ai-hq/ai-hq.env",
        "/run/lock/ai-hq-deploy.lock",
        "flock -n",
        "127.0.0.1:8090/health/ready",
        "PREVIOUS=",
        "rollback",
        "KEEP_RELEASES=5",
        "docker compose",
        "nginx",
    ):
        assert required in text
    assert "/opt/dripvid/app" not in text
    assert "/etc/dripvid/dripvid.env" not in text


def test_deploy_script_validates_exact_sha_archive_contract():
    text = Path("deploy/ai-hq-deploy").read_text()
    assert "^[0-9a-f]{40}$" in text
    assert "/tmp/ai-hq-release-${SHA}.tgz" in text
    assert "unexpected archive path" in text


def test_deploy_script_never_rolls_back_across_a_database_revision_change():
    text = Path("deploy/ai-hq-deploy").read_text()

    assert "database_revision()" in text
    assert "DB_REVISION_BEFORE=" in text
    assert "DB_REVISION_AFTER=" in text
    assert '[[ "$DB_REVISION_AFTER" == "$DB_REVISION_BEFORE" ]]' in text
    assert "database revision changed during deployment" in text
    assert "automatic rollback is unsafe" in text


def test_deploy_script_fails_closed_when_database_revision_cannot_be_verified():
    text = Path("deploy/ai-hq-deploy").read_text()

    assert "database revision could not be verified after readiness failure" in text
    assert "refusing automatic rollback" in text


def test_production_check_covers_dripvid_and_ai_hq_without_secrets():
    text = Path("deploy/check-production.sh").read_text()
    assert "https://dripvid.uk/" in text
    assert "https://dripvid.uk/ai-hq/login" in text
    assert "https://dripvid.uk/ai-hq/health/live" in text
    assert "https://dripvid.uk/ai-hq/health/ready" in text
    assert "AI_HQ_ADMIN_PASSWORD_HASH" not in text
    assert "AI_HQ_SESSION_SECRET" not in text


def test_host_helper_installer_restores_nonsecret_umask_and_secures_venv():
    text = Path("deploy/install-host-helper.sh").read_text()
    secret_umask = text.index("umask 077")
    normal_umask = text.index("umask 022")
    venv_create = text.index('python3 -m venv "$VENV"')

    assert secret_umask < normal_umask < venv_create
    assert 'chown -R root:ai-hq-helper "$VENV"' in text
    assert 'chmod -R u+rwX,g+rX,o-rwx "$VENV"' in text
    assert 'runuser -u ai-hq-helper -- "$VENV/bin/python" -c' in text


def test_deploy_script_requires_fixed_dripvid_mcp_socket_and_secure_token_source():
    text = Path("deploy/ai-hq-deploy").read_text()

    assert "DRIPVID_MCP_SOCKET=/run/dripvid-mcp/mcp.sock" in text
    assert "DRIPVID_MCP_TOKEN_SOURCE=/etc/ai-hq/dripvid-mcp.token" in text
    assert 'test -S "$DRIPVID_MCP_SOCKET"' in text
    assert (
        "AI_HQ_DRIPVID_MCP_TOKEN_SOURCE=/etc/ai-hq/dripvid-mcp.token"
        in text
    )
    assert "AI_HQ_DRIPVID_MCP_SOCKET=/run/dripvid-mcp/mcp.sock" in text
    assert "AI_HQ_DRIPVID_MCP_TOKEN_FILE=/run/secrets/dripvid-mcp-token" in text
    assert "DripVid MCP token file permissions are too broad" in text


def test_dripvid_mcp_credential_installer_copies_token_without_printing_it():
    text = Path("deploy/install-dripvid-mcp-token.sh").read_text()

    assert "SOURCE_ENV=/etc/dripvid/mcp.env" in text
    assert "TARGET_TOKEN=/etc/ai-hq/dripvid-mcp.token" in text
    assert "TARGET_ENV=/etc/ai-hq/ai-hq.env" in text
    assert "MCP_BEARER_TOKEN" in text
    assert 'chmod 600 "$TARGET_TOKEN"' in text
    assert 'chown root:root "$TARGET_TOKEN"' in text
    assert "AI_HQ_DRIPVID_MCP_TOKEN_SOURCE=/etc/ai-hq/dripvid-mcp.token" in text
    assert "AI_HQ_DRIPVID_MCP_TOKEN_FILE=/run/secrets/dripvid-mcp-token" in text
    assert "AI_HQ_DRIPVID_MCP_SOCKET=/run/dripvid-mcp/mcp.sock" in text
    assert 'echo "$TOKEN"' not in text
    assert 'printf "%s\\n" "$TOKEN"' not in text


def test_production_check_verifies_worker_only_mcp_and_live_read():
    text = Path("deploy/check-production.sh").read_text()

    assert "/run/dripvid-mcp|/run/dripvid-mcp|false" in text
    assert "web container must not have DripVid MCP runtime mount" in text
    assert "/run/secrets/dripvid-mcp-token" in text
    assert "DripVidMcpClient" in text
    assert "dripvid_health()" in text
    assert "MCP read-only health" in text
