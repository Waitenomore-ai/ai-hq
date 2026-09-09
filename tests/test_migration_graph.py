from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()

    assert heads == ["0018_delivery_release"]


def test_recovery_status_migration_follows_mission_leases() -> None:
    migration = Path("migrations/versions/0016_recovery_status.py")

    assert migration.is_file()
    text = migration.read_text()
    assert 'revision = "0016_recovery_status"' in text
    assert 'down_revision = "0015_mission_leases"' in text


def test_delivery_publication_migration_follows_recovery_status() -> None:
    migration = Path("migrations/versions/0017_delivery_publication.py")

    assert migration.is_file()
    text = migration.read_text()
    assert 'revision = "0017_delivery_publication"' in text
    assert 'down_revision = "0016_recovery_status"' in text


def test_delivery_release_migration_follows_delivery_publication() -> None:
    migration = Path("migrations/versions/0018_delivery_release.py")

    assert migration.is_file()
    text = migration.read_text()
    assert 'revision = "0018_delivery_release"' in text
    assert 'down_revision = "0017_delivery_publication"' in text
    assert "deployment_release_id" in text
    assert "deployment_prior_release_id" in text
    assert "deployed_at" in text
