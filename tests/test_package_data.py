import tomllib
from pathlib import Path


def test_ai_hq_package_includes_static_ui_assets():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]["ai_hq"]

    assert "static/*.css" in package_data
    assert "static/*.js" in package_data
