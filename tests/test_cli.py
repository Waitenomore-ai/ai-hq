import pytest
from argon2 import PasswordHasher

from ai_hq.cli import main


def test_hash_admin_password_prints_only_verifiable_hash(monkeypatch, capsys):
    answers = iter(["different-ai-hq-password", "different-ai-hq-password"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    main(["hash-admin-password"])

    output = capsys.readouterr().out.strip()
    assert output.startswith("$argon2")
    assert "different-ai-hq-password" not in output
    assert PasswordHasher().verify(output, "different-ai-hq-password") is True


def test_hash_admin_password_rejects_mismatch(monkeypatch):
    answers = iter(["different-ai-hq-password", "not-the-same-password"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    with pytest.raises(SystemExit):
        main(["hash-admin-password"])


def test_hash_admin_password_rejects_short_password(monkeypatch):
    answers = iter(["short", "short"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    with pytest.raises(SystemExit):
        main(["hash-admin-password"])
