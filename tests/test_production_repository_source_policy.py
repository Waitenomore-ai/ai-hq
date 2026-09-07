from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_hq.code_changes.runtime import (
    build_code_change_service,
)
from ai_hq.config import OperatingMode, Settings


def production_settings(
    *,
    mirror_root: Path | None,
    sandbox: Path | None,
    ai_hq_source: Path | None,
    dripvid_source: Path | None,
) -> Settings:
    values = {
        "database_url": "sqlite:///test.db",
        "redis_url": "redis://127.0.0.1:6379/15",
        "environment": "production",
        "admin_password_hash": "test-hash",
        "session_secret": "x" * 40,
        "operating_mode": OperatingMode.SAFE,
        "simulation_mode": True,
    }

    if mirror_root is not None:
        values["repository_mirror_root"] = str(
            mirror_root
        )

    if sandbox is not None:
        values["repository_sandbox_root"] = str(
            sandbox
        )

    if ai_hq_source is not None:
        values["ai_hq_repository_source"] = str(
            ai_hq_source
        )

    if dripvid_source is not None:
        values["dripvid_repository_source"] = str(
            dripvid_source
        )

    return Settings(**values)


def test_development_does_not_require_repository_mirror_root(
    tmp_path: Path,
):
    settings = Settings(
        database_url="sqlite:///test.db",
        redis_url="redis://127.0.0.1:6379/15",
        environment="development",
        repository_sandbox_root=str(
            tmp_path / "sandboxes"
        ),
        ai_hq_repository_source=str(
            tmp_path / "sources" / "ai-hq"
        ),
        dripvid_repository_source=str(
            tmp_path / "sources" / "dripvid"
        ),
    )

    assert settings.repository_mirror_root_path is None


def test_production_code_changes_require_trusted_mirror_root(
    tmp_path: Path,
):
    with pytest.raises(
        ValidationError,
        match="trusted repository mirror",
    ):
        production_settings(
            mirror_root=None,
            sandbox=tmp_path / "sandboxes",
            ai_hq_source=tmp_path / "ai-hq",
            dripvid_source=tmp_path / "dripvid",
        )


@pytest.mark.parametrize(
    "repository",
    ["ai-hq", "dripvid"],
)
def test_production_sources_must_be_inside_trusted_mirror(
    tmp_path: Path,
    repository: str,
):
    mirror = tmp_path / "mirrors"

    ai_hq_source = mirror / "ai-hq"
    dripvid_source = mirror / "dripvid"

    if repository == "ai-hq":
        ai_hq_source = tmp_path / "outside" / "ai-hq"
    else:
        dripvid_source = (
            tmp_path / "outside" / "dripvid"
        )

    with pytest.raises(
        ValidationError,
        match="must be beneath the trusted repository mirror",
    ):
        production_settings(
            mirror_root=mirror,
            sandbox=tmp_path / "sandboxes",
            ai_hq_source=ai_hq_source,
            dripvid_source=dripvid_source,
        )


@pytest.mark.parametrize(
    ("source", "repository_name"),
    [
        (
            Path("/opt/ai-hq/app"),
            "AI HQ",
        ),
        (
            Path(
                "/opt/ai-hq/releases/"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "AI HQ",
        ),
        (
            Path("/opt/dripvid/app"),
            "DripVid",
        ),
        (
            Path(
                "/opt/dripvid/releases/"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "DripVid",
        ),
    ],
)
def test_production_rejects_live_deployment_sources(
    source: Path,
    repository_name: str,
):
    mirror = Path("/opt")

    ai_hq_source = (
        source
        if repository_name == "AI HQ"
        else mirror / "trusted-mirrors" / "ai-hq"
    )

    dripvid_source = (
        source
        if repository_name == "DripVid"
        else mirror / "trusted-mirrors" / "dripvid"
    )

    with pytest.raises(
        ValidationError,
        match="live deployment path",
    ):
        production_settings(
            mirror_root=mirror,
            sandbox=Path("/srv/ai-hq-sandboxes"),
            ai_hq_source=ai_hq_source,
            dripvid_source=dripvid_source,
        )


@pytest.mark.parametrize(
    "live_name",
    ["app", "current", "releases"],
)
def test_ai_hq_live_tree_is_never_a_source(
    live_name: str,
):
    with pytest.raises(
        ValidationError,
        match="live deployment path",
    ):
        production_settings(
            mirror_root=Path("/opt"),
            sandbox=Path("/srv/ai-hq-sandboxes"),
            ai_hq_source=(
                Path("/opt/ai-hq")
                / live_name
            ),
            dripvid_source=(
                Path("/opt/trusted-mirrors/dripvid")
            ),
        )


@pytest.mark.parametrize(
    "live_name",
    ["app", "current", "releases"],
)
def test_dripvid_live_tree_is_never_a_source(
    live_name: str,
):
    with pytest.raises(
        ValidationError,
        match="live deployment path",
    ):
        production_settings(
            mirror_root=Path("/opt"),
            sandbox=Path("/srv/ai-hq-sandboxes"),
            ai_hq_source=(
                Path("/opt/trusted-mirrors/ai-hq")
            ),
            dripvid_source=(
                Path("/opt/dripvid")
                / live_name
            ),
        )


def test_repository_sandbox_must_not_overlap_mirror_root(
    tmp_path: Path,
):
    mirror = tmp_path / "repository-data"

    with pytest.raises(
        ValidationError,
        match=(
            "repository sandbox must not overlap "
            "the trusted repository mirror"
        ),
    ):
        production_settings(
            mirror_root=mirror,
            sandbox=mirror / "sandboxes",
            ai_hq_source=mirror / "ai-hq",
            dripvid_source=mirror / "dripvid",
        )


def test_valid_production_mirror_configuration_is_allowed(
    tmp_path: Path,
):
    mirror = tmp_path / "mirrors"

    settings = production_settings(
        mirror_root=mirror,
        sandbox=tmp_path / "sandboxes",
        ai_hq_source=mirror / "ai-hq",
        dripvid_source=mirror / "dripvid",
    )

    assert settings.repository_mirror_root_path == (
        mirror.resolve()
    )

    assert settings.ai_hq_repository_source_path == (
        mirror / "ai-hq"
    ).resolve()

    assert settings.dripvid_repository_source_path == (
        mirror / "dripvid"
    ).resolve()


def test_runtime_revalidates_production_source_policy():
    settings = SimpleNamespace(
        is_production=True,
        repository_mirror_root_path=Path("/opt"),
        repository_sandbox_root_path=Path(
            "/srv/ai-hq-sandboxes"
        ),
        ai_hq_repository_source_path=Path(
            "/opt/ai-hq/app"
        ),
        dripvid_repository_source_path=Path(
            "/opt/trusted-mirrors/dripvid"
        ),
    )

    with pytest.raises(
        ValueError,
        match="live deployment path",
    ):
        build_code_change_service(
            settings=settings,
            session_factory=object(),
            model_client=object(),
        )
