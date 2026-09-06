from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_hq.config import OperatingMode, Settings


def test_settings_defaults_are_safe():
    settings = Settings(database_url="postgresql+psycopg://u:p@db/hq", redis_url="redis://redis:6379/0")
    assert settings.operating_mode is OperatingMode.SAFE
    assert settings.simulation_mode is True
    assert settings.environment == "development"
    assert settings.root_path == "/ai-hq"
    assert settings.session_lifetime_hours == 12


def test_freeze_mode_is_accepted():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
        operating_mode="freeze",
    )
    assert settings.operating_mode is OperatingMode.FREEZE


def test_production_rejects_missing_admin_password_hash():
    with pytest.raises(ValidationError, match="admin password hash"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@db/hq",
            redis_url="redis://redis:6379/0",
            session_secret="x" * 32,
        )


def test_production_rejects_short_session_secret():
    with pytest.raises(ValidationError, match="session secret"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@db/hq",
            redis_url="redis://redis:6379/0",
            admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$example$example",
            session_secret="too-short",
        )


def test_production_accepts_separate_admin_auth_secrets():
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
        admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$example$example",
        session_secret="s" * 32,
    )
    assert settings.is_production is True
    assert settings.root_path == "/ai-hq"


def test_repository_sandbox_paths_are_resolved(tmp_path):
    source = tmp_path / "source"
    sandbox = tmp_path / "sandbox"

    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
        ai_hq_repository_source=str(source),
        repository_sandbox_root=str(sandbox),
    )

    assert settings.ai_hq_repository_source_path == Path(source).resolve()
    assert settings.repository_sandbox_root_path == Path(sandbox).resolve()


@pytest.mark.parametrize(
    ("source_name", "sandbox_name"),
    [
        ("repo", "repo"),
        ("repo", "repo/sandbox"),
        ("sandbox/repo", "sandbox"),
    ],
)
def test_repository_sandbox_rejects_overlapping_paths(
    tmp_path,
    source_name,
    sandbox_name,
):
    with pytest.raises(ValidationError, match="sandbox"):
        Settings(
            database_url="postgresql+psycopg://u:p@db/hq",
            redis_url="redis://redis:6379/0",
            ai_hq_repository_source=str(tmp_path / source_name),
            repository_sandbox_root=str(tmp_path / sandbox_name),
        )
