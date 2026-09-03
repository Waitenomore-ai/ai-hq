from pathlib import Path


def test_bootstrap_requires_root_and_creates_isolated_ai_hq_paths():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "EUID" in text
    assert "/etc/ai-hq/ai-hq.env" in text
    assert "/opt/ai-hq" in text
    assert "/etc/dripvid/dripvid.env" not in text


def test_bootstrap_never_stores_plaintext_admin_password():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "hash-admin-password" in text
    assert "AI_HQ_ADMIN_PASSWORD_HASH" in text
    assert "AI_HQ_ADMIN_PASSWORD=" not in text
    assert "AI_HQ_SESSION_SECRET" in text
    assert "openssl rand -hex 32" in text


def test_bootstrap_forces_safe_first_launch_defaults():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "AI_HQ_ENVIRONMENT=production" in text
    assert "AI_HQ_OPERATING_MODE=safe" in text
    assert "AI_HQ_SIMULATION_MODE=true" in text
    assert "AI_HQ_ROOT_PATH=/ai-hq" in text


def test_bootstrap_validates_nginx_before_reload_and_preserves_backup():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "nginx -t" in text
    assert "systemctl reload nginx" in text
    assert ".pre-ai-hq." in text
    assert text.index("nginx -t") < text.index("systemctl reload nginx")


def test_bootstrap_requires_exact_release_sha_and_archive():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "^[0-9a-f]{40}$" in text
    assert "/tmp/ai-hq-release-${SHA}.tgz" in text
    assert "ai-hq-deploy" in text
    assert "check-production.sh" in text


def test_bootstrap_fetches_missing_exact_sha_archive_from_github():
    text = Path("deploy/bootstrap-production.sh").read_text()
    assert "curl" in text
    assert "Waitenomore-ai/ai-hq/archive/${SHA}.tar.gz" in text
    assert "curl -fL" in text
    assert "tar -tzf" in text
