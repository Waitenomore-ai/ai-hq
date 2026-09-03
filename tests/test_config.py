from ai_hq.config import OperatingMode, Settings


def test_settings_defaults_are_safe():
    settings = Settings(database_url="postgresql+psycopg://u:p@db/hq", redis_url="redis://redis:6379/0")
    assert settings.operating_mode is OperatingMode.SAFE
    assert settings.simulation_mode is True
    assert settings.environment == "development"


def test_freeze_mode_is_accepted():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
        operating_mode="freeze",
    )
    assert settings.operating_mode is OperatingMode.FREEZE
