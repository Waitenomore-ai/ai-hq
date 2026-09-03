from enum import StrEnum
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OperatingMode(StrEnum):
    NORMAL = "normal"
    SAFE = "safe"
    FREEZE = "freeze"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_HQ_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    redis_url: str
    operating_mode: OperatingMode = OperatingMode.SAFE
    simulation_mode: bool = True
    log_level: str = "INFO"
    root_path: str = "/ai-hq"
    admin_password_hash: str | None = None
    session_secret: str | None = None
    session_lifetime_hours: int = 12

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() == "production"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if not self.is_production:
            return self
        if not self.admin_password_hash:
            raise ValueError("AI HQ admin password hash is required in production")
        if not self.session_secret or len(self.session_secret) < 32:
            raise ValueError("AI HQ session secret must be at least 32 characters in production")
        if self.operating_mode is not OperatingMode.SAFE:
            raise ValueError("AI HQ production must start in safe operating mode")
        if self.simulation_mode is not True:
            raise ValueError("AI HQ production must start with simulation mode enabled")
        if not self.root_path.startswith("/") or self.root_path == "/":
            raise ValueError("AI HQ root path must be a non-root absolute path")
        if self.session_lifetime_hours < 1 or self.session_lifetime_hours > 24:
            raise ValueError("AI HQ session lifetime must be between 1 and 24 hours")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
