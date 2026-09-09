from __future__ import annotations

import stat
import sys
from pathlib import Path

_MAX_MCP_TOKEN_BYTES = 4096


def load_dripvid_mcp_token(path: Path) -> str:
    token_path = Path(path).expanduser()
    try:
        metadata = token_path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("DripVid MCP token must be a regular file") from exc

    if token_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("DripVid MCP token must be a regular non-symlink file")

    # Unix-style owner-only permission checks do not apply to Windows dev hosts;
    # the production deployment target is Linux where these remain enforced.
    if sys.platform != "win32":
        if metadata.st_mode & 0o077:
            raise ValueError("DripVid MCP token file permissions are too broad")
        if not metadata.st_mode & stat.S_IRUSR:
            raise ValueError("DripVid MCP token file must be owner-readable")

    if metadata.st_size > _MAX_MCP_TOKEN_BYTES:
        raise ValueError("DripVid MCP token file is too large")

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("DripVid MCP token file is empty")
    if any(character.isspace() for character in token):
        raise ValueError("DripVid MCP token contains invalid whitespace")
    return token
