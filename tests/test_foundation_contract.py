from ai_hq.app import create_app
from ai_hq.config import OperatingMode, Settings
from ai_hq.worker import execution_allowed


def test_foundation_defaults_and_routes_are_safe():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/hq",
        redis_url="redis://redis:6379/0",
    )
    assert settings.operating_mode is OperatingMode.SAFE
    assert settings.simulation_mode is True
    assert execution_allowed(OperatingMode.FREEZE) is False

    routes = {route.path for route in create_app().routes}
    assert "/health/live" in routes
    assert "/health/ready" in routes
