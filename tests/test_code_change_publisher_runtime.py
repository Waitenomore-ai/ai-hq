from pathlib import Path

import pytest
import yaml

from ai_hq.code_changes.runtime import load_github_publish_token
from ai_hq.config import Settings


TOKEN_PATH = "/run/secrets/ai-hq-github-publisher-token"


def settings(**overrides):
    values = {
        "database_url": "sqlite+pysqlite://",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_publisher_token_file_is_optional_non_secret_configuration():
    value = settings()

    assert value.github_publish_token_file is None
    assert "github_publish_token_file=None" in repr(value)

    configured = settings(github_publish_token_file=TOKEN_PATH)
    assert configured.github_publish_token_file_path == Path(TOKEN_PATH)
    assert "secret-token-contents" not in repr(configured)


def test_token_loader_accepts_only_restrictive_regular_file(tmp_path):
    token = tmp_path / "publisher-token"
    token.write_text("github-test-token\n")
    token.chmod(0o600)

    assert load_github_publish_token(token) == "github-test-token"

    token.chmod(0o644)
    with pytest.raises(ValueError, match="permission"):
        load_github_publish_token(token)


def test_token_loader_rejects_symlink_empty_or_missing_file(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="regular|file"):
        load_github_publish_token(missing)

    empty = tmp_path / "empty"
    empty.write_text("")
    empty.chmod(0o600)
    with pytest.raises(ValueError, match="empty"):
        load_github_publish_token(empty)

    real = tmp_path / "real"
    real.write_text("github-test-token")
    real.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink|regular"):
        load_github_publish_token(link)


def test_compose_exposes_publisher_secret_only_to_worker():
    compose = yaml.safe_load(Path("compose.yaml").read_text())
    services = compose["services"]

    worker_secrets = services["worker"].get("secrets", [])
    web_secrets = services["web"].get("secrets", [])

    assert any(
        isinstance(secret, dict)
        and secret.get("target") == "ai-hq-github-publisher-token"
        for secret in worker_secrets
    )
    assert web_secrets == []

    secret_config = compose["secrets"]["ai_hq_github_publisher_token"]
    assert "${AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE" in secret_config["file"]


def test_env_example_contains_only_token_file_paths_not_token_value():
    env_example = Path(".env.example").read_text()

    assert f"AI_HQ_GITHUB_PUBLISH_TOKEN_FILE={TOKEN_PATH}" in env_example
    assert "AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE=" in env_example
    assert "github_pat_" not in env_example
    assert "ghp_" not in env_example
