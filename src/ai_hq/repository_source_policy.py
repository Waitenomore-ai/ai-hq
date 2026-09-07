from __future__ import annotations

from pathlib import Path


_LIVE_DEPLOYMENT_ROOTS = (
    Path("/opt/ai-hq/app"),
    Path("/opt/ai-hq/current"),
    Path("/opt/ai-hq/releases"),
    Path("/opt/dripvid/app"),
    Path("/opt/dripvid/current"),
    Path("/opt/dripvid/releases"),
)


def _resolved(
    value: Path | str | None,
) -> Path | None:
    if value is None:
        return None

    return Path(value).expanduser().resolve()


def _contains(
    root: Path,
    candidate: Path,
) -> bool:
    return (
        candidate == root
        or root in candidate.parents
    )


def _overlaps(
    first: Path,
    second: Path,
) -> bool:
    return (
        first == second
        or first in second.parents
        or second in first.parents
    )


def validate_production_repository_paths(
    *,
    is_production: bool,
    mirror_root: Path | str | None,
    sandbox_root: Path | str | None,
    ai_hq_source: Path | str | None,
    dripvid_source: Path | str | None,
) -> None:
    """
    Validate the trusted production source boundary.

    This function does not grant write, publish, deploy, shell,
    or host authority. It only validates operator-configured paths.

    Development remains unaffected. Production code-change support
    stays disabled unless every trusted path is configured.
    """

    if not is_production:
        return

    mirror = _resolved(mirror_root)
    sandbox = _resolved(sandbox_root)
    ai_hq = _resolved(ai_hq_source)
    dripvid = _resolved(dripvid_source)

    configured = (
        mirror,
        sandbox,
        ai_hq,
        dripvid,
    )

    if all(value is None for value in configured):
        return

    if any(value is None for value in configured):
        raise ValueError(
            "production code changes require a trusted "
            "repository mirror, repository sandbox, "
            "AI HQ source, and DripVid source"
        )

    assert mirror is not None
    assert sandbox is not None
    assert ai_hq is not None
    assert dripvid is not None

    if _overlaps(mirror, sandbox):
        raise ValueError(
            "repository sandbox must not overlap "
            "the trusted repository mirror"
        )

    for repository_name, source in (
        ("AI HQ", ai_hq),
        ("DripVid", dripvid),
    ):
        if source == mirror or not _contains(
            mirror,
            source,
        ):
            raise ValueError(
                f"{repository_name} repository source "
                "must be beneath the trusted repository mirror"
            )

        for live_root in _LIVE_DEPLOYMENT_ROOTS:
            live = live_root.resolve()

            if _contains(live, source):
                raise ValueError(
                    f"{repository_name} repository source "
                    "must not use a live deployment path"
                )
