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


def test_production_check_covers_dripvid_and_ai_hq_without_secrets():
    text = Path("deploy/check-production.sh").read_text()
    assert "https://dripvid.uk/" in text
    assert "https://dripvid.uk/ai-hq/login" in text
    assert "https://dripvid.uk/ai-hq/health/live" in text
    assert "https://dripvid.uk/ai-hq/health/ready" in text
    assert "AI_HQ_ADMIN_PASSWORD_HASH" not in text
    assert "AI_HQ_SESSION_SECRET" not in text
