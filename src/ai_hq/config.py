import os
from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_hq.repository_source_policy import (
    validate_production_repository_paths,
)


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
    host_helper_socket: str = "/run/ai-hq/host-helper.sock"
    host_helper_credential: str | None = None
    repository_mirror_root: str | None = None
    repository_sandbox_root: str | None = None
    ai_hq_repository_source: str | None = None
    dripvid_repository_source: str | None = None
    github_publish_token_file: str | None = None
    dripvid_mcp_socket: str = "/run/dripvid-mcp/mcp.sock"
    dripvid_mcp_token_file: str | None = None
    dripvid_mcp_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)

    recovery_enabled: bool = False
    recovery_observe_only: bool = True
    recovery_observation_seconds: int = Field(default=30, ge=10, le=300)
    recovery_failure_threshold: int = Field(default=3, ge=2, le=10)
    recovery_cooldown_seconds: int = Field(default=300, ge=60)
    recovery_attempt_budget: int = Field(default=2, ge=1, le=5)
    recovery_budget_window_seconds: int = Field(default=3600, ge=60)
    recovery_verify_seconds: int = Field(default=60, ge=10, le=300)
    recovery_dripvid_ready_url: str = "http://127.0.0.1:3000/health/ready"

    chat_model_base_url: str | None = None
    chat_model_name: str | None = None
    chat_model_api_key: str | None = None
    chat_model_timeout_seconds: float = 15.0

    free_ai_local_base_url: str | None = None
    free_ai_local_model: str | None = None
    free_ai_local_api_key: str | None = None

    free_ai_groq_api_key: str | None = None
    free_ai_groq_model: str | None = None

    free_ai_openrouter_api_key: str | None = None

    free_ai_hf_token: str | None = None
    free_ai_hf_model: str | None = None

    free_ai_timeout_seconds: float = 15.0

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() == "production"

    @property
    def repository_mirror_root_path(self) -> Path | None:
        if self.repository_mirror_root is None:
            return None
        return Path(self.repository_mirror_root).expanduser().resolve()

    @property
    def repository_sandbox_root_path(self) -> Path | None:
        if self.repository_sandbox_root is None:
            return None
        return Path(self.repository_sandbox_root).expanduser().resolve()

    @property
    def ai_hq_repository_source_path(self) -> Path | None:
        if self.ai_hq_repository_source is None:
            return None
        return Path(self.ai_hq_repository_source).expanduser().resolve()

    @property
    def dripvid_repository_source_path(self) -> Path | None:
        if self.dripvid_repository_source is None:
            return None
        return Path(self.dripvid_repository_source).expanduser().resolve()

    @property
    def github_publish_token_file_path(self) -> Path | None:
        if self.github_publish_token_file is None:
            return None
        return Path(self.github_publish_token_file).expanduser()

    @property
    def dripvid_mcp_socket_path(self) -> Path:
        return Path(self.dripvid_mcp_socket).expanduser()

    @property
    def dripvid_mcp_token_file_path(self) -> Path | None:
        if self.dripvid_mcp_token_file is None:
            return None
        return Path(self.dripvid_mcp_token_file).expanduser()

    @model_validator(mode="after")
    def validate_repository_sandbox_paths(self) -> "Settings":
        sandbox = self.repository_sandbox_root_path
        if sandbox is None:
            return self

        sources = (
            ("AI HQ", self.ai_hq_repository_source_path),
            ("DripVid", self.dripvid_repository_source_path),
        )

        for repository_name, source in sources:
            if source is None:
                continue

            if source == sandbox or source in sandbox.parents or sandbox in source.parents:
                raise ValueError(
                    "repository sandbox must not overlap "
                    f"the {repository_name} repository source"
                )

        return self

    @model_validator(mode="after")
    def validate_production_repository_sources(self) -> "Settings":
        validate_production_repository_paths(
            is_production=self.is_production,
            mirror_root=self.repository_mirror_root_path,
            sandbox_root=self.repository_sandbox_root_path,
            ai_hq_source=self.ai_hq_repository_source_path,
            dripvid_source=self.dripvid_repository_source_path,
        )
        return self

    @model_validator(mode="after")
    def validate_dripvid_mcp_paths(self) -> "Settings":
        if not self.is_production:
            return self

        socket_value = self.dripvid_mcp_socket.strip()
        if "://" in socket_value:
            raise ValueError("AI HQ production DripVid MCP socket must be an absolute Unix path")

        # Unix absolute-path semantics do not apply to Windows dev/test hosts;
        # production deployment target is Linux where this remains enforced.
        if os.name != "nt" and not self.dripvid_mcp_socket_path.is_absolute():
            raise ValueError("AI HQ production DripVid MCP socket must be an absolute Unix path")

        token_path = self.dripvid_mcp_token_file_path
        if token_path is not None and token_path.is_absolute() is False and os.name != "nt":
            raise ValueError("AI HQ production DripVid MCP token path must be absolute")
        return self

    @model_validator(mode="after")
    def validate_recovery_policy(self) -> "Settings":
        if self.recovery_budget_window_seconds < self.recovery_cooldown_seconds:
            raise ValueError(
                "AI HQ recovery budget window must be at least as long as the recovery cooldown"
            )

        if self.is_production:
            parsed = urlsplit(self.recovery_dripvid_ready_url)
            if parsed.scheme.casefold() != "http":
                raise ValueError(
                    "AI HQ production recovery readiness URL must use loopback HTTP"
                )

            host = parsed.hostname
            if not host:
                raise ValueError(
                    "AI HQ production recovery readiness URL must use loopback HTTP"
                )

            if host.casefold() == "localhost":
                loopback = True
            else:
                try:
                    loopback = ip_address(host).is_loopback
                except ValueError:
                    loopback = False

            if not loopback:
                raise ValueError(
                    "AI HQ production recovery readiness URL must use loopback HTTP"
                )
        return self

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
