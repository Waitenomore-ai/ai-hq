from pathlib import Path
import tomllib

from packaging.requirements import Requirement


def test_httpx_is_a_runtime_dependency():
    """ChatModelClient imports httpx, so production must install it."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]

    names = {
        Requirement(dependency).name.lower()
        for dependency in dependencies
    }

    assert "httpx" in names
