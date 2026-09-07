from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


_ALLOWED_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".md",
        ".sh",
    }
)

_BLOCKED_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
    }
)

_BLOCKED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
    }
)


class RepositoryContextProvider:
    """
    Bounded read-only context over one trusted repository source.

    This does not expose arbitrary filesystem access to the model.
    """

    def __init__(
        self,
        *,
        repository: str,
        source_path: Path,
        max_files: int = 12,
        max_chars_per_file: int = 6000,
        max_total_chars: int = 30000,
    ) -> None:
        if repository not in {"ai-hq", "dripvid"}:
            raise ValueError("unknown trusted repository")

        source = Path(source_path).expanduser().resolve()

        if not source.is_dir():
            raise ValueError(
                "repository source must be an existing directory"
            )

        self.repository = repository
        self.source_path = source
        self.max_files = max_files
        self.max_chars_per_file = max_chars_per_file
        self.max_total_chars = max_total_chars

    def build(
        self,
        *,
        instruction: str,
    ) -> dict:
        instruction = instruction.strip()

        if not instruction:
            raise ValueError("instruction is required")

        tokens = self._tokens(instruction)
        ranked = []

        for path in self.source_path.rglob("*"):
            if not self._eligible(path):
                continue

            relative = path.relative_to(
                self.source_path
            ).as_posix()

            try:
                content = path.read_text(
                    encoding="utf-8"
                )
            except (UnicodeDecodeError, OSError):
                continue

            score = self._score(
                relative=relative,
                content=content,
                tokens=tokens,
            )

            if score <= 0:
                continue

            ranked.append(
                (
                    -score,
                    relative,
                    content,
                )
            )

        ranked.sort()

        files = []
        total = 0

        for _negative_score, relative, content in ranked:
            if len(files) >= self.max_files:
                break

            remaining = (
                self.max_total_chars - total
            )

            if remaining <= 0:
                break

            bounded = content[
                : min(
                    self.max_chars_per_file,
                    remaining,
                )
            ]

            files.append(
                {
                    "path": relative,
                    "content": bounded,
                }
            )

            total += len(bounded)

        return {
            "repository": self.repository,
            "instruction": instruction,
            "files": files,
        }

    def _eligible(
        self,
        path: Path,
    ) -> bool:
        if not path.is_file():
            return False

        relative = path.relative_to(
            self.source_path
        )

        pure = PurePosixPath(
            relative.as_posix()
        )

        if any(
            part in _BLOCKED_PARTS
            for part in pure.parts
        ):
            return False

        if path.name in _BLOCKED_NAMES:
            return False

        if path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            return False

        try:
            if path.stat().st_size > 512_000:
                return False
        except OSError:
            return False

        return True

    @staticmethod
    def _tokens(
        instruction: str,
    ) -> tuple[str, ...]:
        ignored = {
            "the",
            "and",
            "for",
            "with",
            "make",
            "change",
            "edit",
            "update",
            "fix",
            "dripvid",
            "ai",
            "hq",
        }

        words = re.findall(
            r"[a-z0-9_-]{3,}",
            instruction.casefold(),
        )

        return tuple(
            sorted(
                {
                    word
                    for word in words
                    if word not in ignored
                }
            )
        )

    @staticmethod
    def _score(
        *,
        relative: str,
        content: str,
        tokens: tuple[str, ...],
    ) -> int:
        if not tokens:
            return 1

        haystack_path = relative.casefold()
        haystack_content = content.casefold()

        score = 0

        for token in tokens:
            if token in haystack_path:
                score += 10

            if token in haystack_content:
                score += 2

        return score
