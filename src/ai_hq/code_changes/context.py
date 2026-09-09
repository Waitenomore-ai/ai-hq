from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from ai_hq.delivery.repository_profiles import TRUSTED_REPOSITORY_KEYS


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

_SECRET_NAME_PARTS = frozenset(
    {
        "credentials",
        "credential",
        "secrets",
        "secret",
    }
)

_PRIVATE_KEY_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
)

_KNOWN_SECRET_PATTERNS = (
    re.compile(
        r"sk-or-v1-[A-Za-z0-9_-]{16,}"
    ),
    re.compile(
        r"github_pat_[A-Za-z0-9_]{20,}"
    ),
    re.compile(
        r"gh[pousr]_[A-Za-z0-9]{20,}"
    ),
    re.compile(
        r"AKIA[0-9A-Z]{16}"
    ),
)

_SECRET_ASSIGNMENT_RE = re.compile(
    r"""
    (?ix)
    (?:
        ^|[,{\s]
    )
    ["']?
    (
        [A-Za-z0-9_-]*
        (?:
            api[_-]?key
            |
            access[_-]?token
            |
            auth[_-]?token
            |
            bearer[_-]?token
            |
            client[_-]?secret
            |
            session[_-]?secret
            |
            secret[_-]?key
            |
            private[_-]?key
            |
            password
            |
            passwd
            |
            credential
        )
        [A-Za-z0-9_-]*
    )
    ["']?
    \s*
    (?:
        =|:
    )
    \s*
    ["']?
    ([^"'\s,;}]{8,})
    """,
    re.MULTILINE | re.VERBOSE,
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "example",
        "example-value",
        "placeholder",
        "replace-me",
        "changeme",
        "change-me",
        "your-key",
        "your-api-key",
        "your-api-key-here",
        "your-token",
        "your-token-here",
        "your-password",
        "your-password-here",
        "dummy",
        "test-value",
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

_RELEVANCE_ALIASES = {
    "phone": ("mobile",),
    "phones": ("mobile",),
    "menu": ("nav", "sidebar"),
    "spacing": ("gap",),
}


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
        max_chars_per_file: int = 12000,
        max_total_chars: int = 48000,
    ) -> None:
        if repository not in TRUSTED_REPOSITORY_KEYS:
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

            if self._contains_sensitive_content(
                content
            ):
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

            # Developer changes are whole-file replacements.
            # Never expose a partial file as writable source context.
            #
            # If the complete file cannot fit within both the trusted
            # per-file and total context limits, skip it instead of
            # truncating it.
            if len(content) > self.max_chars_per_file:
                continue

            if len(content) > remaining:
                continue

            files.append(
                {
                    "path": relative,
                    "content": content,
                    "complete": True,
                }
            )

            total += len(content)

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

        name = path.name.casefold()

        if (
            name in _BLOCKED_NAMES
            or name.startswith(".env.")
        ):
            return False

        stem_parts = {
            part
            for part in re.split(
                r"[^a-z0-9]+",
                path.stem.casefold(),
            )
            if part
        }

        if stem_parts & _SECRET_NAME_PARTS:
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
    def _contains_sensitive_content(
        content: str,
    ) -> bool:
        upper_content = content.upper()

        if any(
            marker in upper_content
            for marker in _PRIVATE_KEY_MARKERS
        ):
            return True

        if any(
            pattern.search(content)
            for pattern in _KNOWN_SECRET_PATTERNS
        ):
            return True

        for match in _SECRET_ASSIGNMENT_RE.finditer(
            content
        ):
            value = (
                match.group(2)
                .strip()
                .strip("\"'")
                .casefold()
            )

            normalized = value.strip(
                "<>{}[]()"
            )

            if normalized in _PLACEHOLDER_VALUES:
                continue

            if (
                normalized.startswith("your-")
                or normalized.startswith("example-")
                or normalized.startswith("dummy-")
            ):
                continue

            return True

        return False

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

            for alias in _RELEVANCE_ALIASES.get(token, ()):
                if alias in haystack_content:
                    score += 2

        return score
