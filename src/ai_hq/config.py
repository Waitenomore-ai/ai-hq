from enum import StrEnum
from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
