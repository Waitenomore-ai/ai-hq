from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()

    assert heads == ["0016_recovery_status"]


def test_recovery_status_migration_follows_mission_leases() -> None:
    migration = Path("migrations/versions/0016_recovery_status.py")

    assert migration.is_file()
    text = migration.read_text()
    assert 'revision = "0016_recovery_status"' in text
    assert 'down_revision = "0015_mission_leases"' in text
