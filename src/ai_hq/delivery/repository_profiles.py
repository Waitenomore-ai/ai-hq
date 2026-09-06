from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepositoryProfile:
    key: str
    source_path: Path
    base_ref: str
    test_commands: tuple[tuple[str, ...], ...]
    test_timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        key = self.key.strip() if isinstance(self.key, str) else ""
        if not key:
            raise ValueError("repository key is required")

        source = Path(self.source_path).expanduser().resolve()
        if not source.is_dir():
            raise ValueError("repository source must be an existing directory")

        base_ref = self.base_ref.strip() if isinstance(self.base_ref, str) else ""
        if not base_ref:
            raise ValueError("base_ref is required")

        if not isinstance(self.test_commands, tuple) or not self.test_commands:
            raise ValueError("test_commands must be a non-empty tuple")
        for command in self.test_commands:
            if not isinstance(command, tuple) or not command:
                raise ValueError("each test command must be a non-empty tuple")
            if not all(isinstance(part, str) and part for part in command):
                raise ValueError("test command parts must be non-empty strings")

        if not isinstance(self.test_timeout_seconds, (int, float)):
            raise TypeError("test_timeout_seconds must be numeric")
        if self.test_timeout_seconds <= 0:
            raise ValueError("test_timeout_seconds must be positive")

        object.__setattr__(self, "key", key)
        object.__setattr__(self, "source_path", source)
        object.__setattr__(self, "base_ref", base_ref)
        object.__setattr__(self, "test_timeout_seconds", float(self.test_timeout_seconds))


class RepositoryProfileRegistry:
    def __init__(self, profiles: tuple[RepositoryProfile, ...]) -> None:
        if not isinstance(profiles, tuple) or not profiles:
            raise ValueError("profiles must be a non-empty tuple")

        by_key: dict[str, RepositoryProfile] = {}
        for profile in profiles:
            if not isinstance(profile, RepositoryProfile):
                raise TypeError("profiles must contain RepositoryProfile values")
            if profile.key in by_key:
                raise ValueError(f"duplicate repository profile: {profile.key}")
            by_key[profile.key] = profile

        self._profiles = by_key

    def get(self, key: str) -> RepositoryProfile:
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise KeyError(f"unknown repository: {key}") from exc


def build_ai_hq_repository_profile(
    *,
    source_path: Path,
    base_ref: str = "HEAD",
) -> RepositoryProfile:
    return RepositoryProfile(
        key="ai-hq",
        source_path=source_path,
        base_ref=base_ref,
        test_commands=(
            (sys.executable, "-m", "ruff", "check", "src", "tests"),
            (sys.executable, "-m", "pytest", "-q"),
        ),
    )
