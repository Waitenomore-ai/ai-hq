import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_hq.config import Settings


def base_settings(**overrides):
    values = {
        "database_url": "postgresql+psycopg://u:p@db/hq",
        "redis_url": "redis://redis:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_dripvid_mcp_defaults_use_fixed_unix_socket():
    settings = base_settings()
    assert settings.dripvid_mcp_socket_path == Path("/run/dripvid-mcp/mcp.sock")
    assert settings.dripvid_mcp_timeout_seconds == 5.0


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix absolute socket path semantics differ on Windows",
)
def test_production_rejects_relative_mcp_socket_path():
    with pytest.raises(ValidationError, match="DripVid MCP socket"):
        base_settings(
            environment="production",
            admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$example$example",
            session_secret="s" * 32,
            dripvid_mcp_socket="relative/mcp.sock",
        )


def test_production_rejects_network_url_in_socket_setting():
    with pytest.raises(ValidationError, match="DripVid MCP socket"):
        base_settings(
            environment="production",
            admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$example$example",
            session_secret="s" * 32,
            dripvid_mcp_socket="http://127.0.0.1:8788/mcp",
        )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix absolute token path semantics differ on Windows",
)
def test_production_rejects_relative_mcp_token_path():
    with pytest.raises(ValidationError, match="DripVid MCP token"):
        base_settings(
            environment="production",
            admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$example$example",
            session_secret="s" * 32,
            dripvid_mcp_token_file="relative/token",
        )


def test_dripvid_mcp_timeout_is_bounded():
    with pytest.raises(ValidationError):
        base_settings(dripvid_mcp_timeout_seconds=0.1)
    with pytest.raises(ValidationError):
        base_settings(dripvid_mcp_timeout_seconds=31)
