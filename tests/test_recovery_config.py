import pytest
from pydantic import ValidationError

from ai_hq.config import OperatingMode, Settings


def make_settings(**overrides):
    values = {
        "database_url": "postgresql://test:test@127.0.0.1/test",
        "redis_url": "redis://127.0.0.1:6379/0",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def production_settings(**overrides):
    values = {
        "environment": "production",
        "admin_password_hash": "test-password-hash",
        "session_secret": "s" * 32,
        "operating_mode": OperatingMode.SAFE,
        "simulation_mode": True,
    }
    values.update(overrides)
    return make_settings(**values)


def test_recovery_defaults_are_safe_and_disabled():
    settings = make_settings()

    assert settings.recovery_enabled is False
    assert settings.recovery_observe_only is True
    assert settings.recovery_observation_seconds == 30
    assert settings.recovery_failure_threshold == 3
    assert settings.recovery_cooldown_seconds == 300
    assert settings.recovery_attempt_budget == 2
    assert settings.recovery_budget_window_seconds == 3600
    assert settings.recovery_verify_seconds == 60
    assert (
        settings.recovery_dripvid_ready_url
        == "http://127.0.0.1:3000/health/ready"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recovery_observation_seconds", 9),
        ("recovery_observation_seconds", 301),
        ("recovery_failure_threshold", 1),
        ("recovery_failure_threshold", 11),
        ("recovery_cooldown_seconds", 59),
        ("recovery_attempt_budget", 0),
        ("recovery_attempt_budget", 6),
        ("recovery_verify_seconds", 9),
        ("recovery_verify_seconds", 301),
    ],
)
def test_recovery_rejects_out_of_bounds_policy_values(field, value):
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_recovery_budget_window_cannot_be_shorter_than_cooldown():
    with pytest.raises(ValidationError):
        make_settings(
            recovery_cooldown_seconds=300,
            recovery_budget_window_seconds=299,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:3000/health/ready",
        "http://192.168.0.24:3000/health/ready",
        "http://dripvid:3000/health/ready",
        "https://localhost:3000/health/ready",
    ],
)
def test_production_recovery_readiness_url_must_be_loopback_http(url):
    with pytest.raises(ValidationError):
        production_settings(
            recovery_dripvid_ready_url=url,
        )


def test_production_accepts_default_loopback_recovery_url():
    settings = production_settings()

    assert (
        settings.recovery_dripvid_ready_url
        == "http://127.0.0.1:3000/health/ready"
    )


def test_existing_production_safe_mode_requirement_is_preserved():
    with pytest.raises(
        ValidationError,
        match="production must start in safe operating mode",
    ):
        production_settings(
            operating_mode=OperatingMode.NORMAL,
        )


def test_existing_production_simulation_requirement_is_preserved():
    with pytest.raises(
        ValidationError,
        match="production must start with simulation mode enabled",
    ):
        production_settings(
            simulation_mode=False,
        )
