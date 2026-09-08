from pathlib import Path

import pytest

from ai_hq.dripvid_mcp.runtime import load_dripvid_mcp_token


def test_load_dripvid_mcp_token_reads_owner_only_regular_file(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("abc123", encoding="utf-8")
    token_file.chmod(0o600)
    assert load_dripvid_mcp_token(token_file) == "abc123"


def test_load_dripvid_mcp_token_rejects_symlink(tmp_path):
    real = tmp_path / "real"
    real.write_text("abc123", encoding="utf-8")
    real.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="non-symlink"):
        load_dripvid_mcp_token(link)


def test_load_dripvid_mcp_token_rejects_broad_permissions(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("abc123", encoding="utf-8")
    token_file.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        load_dripvid_mcp_token(token_file)


def test_load_dripvid_mcp_token_rejects_whitespace_without_echoing_secret(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("secret value", encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(ValueError) as excinfo:
        load_dripvid_mcp_token(token_file)
    assert "secret value" not in str(excinfo.value)


def test_load_dripvid_mcp_token_rejects_oversize_file(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("x" * 5000, encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(ValueError, match="too large"):
        load_dripvid_mcp_token(token_file)
