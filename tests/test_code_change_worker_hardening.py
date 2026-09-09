from datetime import UTC, datetime, timedelta
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_hq.code_changes.service import CodeChangeService
from ai_hq.db import Base
from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_dripvid_repository_profile,
)
from ai_hq.delivery.repository_sandbox import (
    IsolatedRepositorySandbox,
)
from ai_hq.missions.models import (
    MissionPriority,
    MissionRisk,
    MissionStatus,
)
from ai_hq.missions.service import MissionService
from ai_hq.delivery.service import DeliveryService


def make_services(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.sqlite'}"
    )
    Base.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return (
        factory,
        MissionService(factory),
        DeliveryService(factory),
    )


def make_code_change(
    missions: MissionService,
):
    return missions.create_mission(
        title="Code change: ai-hq",
        description="Make a safe UI change.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority=MissionPriority.NORMAL,
        risk=MissionRisk.AMBER,
        objectives=[
            "ai-hq",
            "Make a safe UI change.",
        ],
        dependencies=[],
    )


def test_code_change_claim_is_atomic(
    tmp_path: Path,
):
    _, missions, _ = make_services(tmp_path)

    mission = make_code_change(missions)

    first = missions.claim_oldest_code_change(
        worker_id="worker-one",
        lease_seconds=600,
    )

    second = missions.claim_oldest_code_change(
        worker_id="worker-two",
        lease_seconds=600,
    )

    assert first is not None
    assert first.id == mission.id
    assert first.status is MissionStatus.RUNNING
    assert first.lease_owner == "worker-one"
    assert first.lease_expires_at is not None
    assert first.attempt_count == 1

    assert second is None


def test_expired_code_change_can_be_reclaimed(
    tmp_path: Path,
):
    factory, missions, _ = make_services(tmp_path)

    mission = make_code_change(missions)

    with factory() as db:
        stored = db.get(
            type(mission),
            mission.id,
        )

        stored.status = MissionStatus.RUNNING
        stored.lease_owner = "dead-worker"
        stored.lease_expires_at = (
            datetime.now(UTC)
            - timedelta(minutes=5)
        )
        stored.attempt_count = 1

        db.commit()

    reclaimed = (
        missions.claim_oldest_code_change(
            worker_id="replacement-worker",
            lease_seconds=600,
        )
    )

    assert reclaimed is not None
    assert reclaimed.id == mission.id
    assert (
        reclaimed.lease_owner
        == "replacement-worker"
    )
    assert reclaimed.attempt_count == 2


class ExplodingRunner:
    def run_developer(
        self,
        *,
        mission_id: str,
    ):
        raise RuntimeError(
            "provider error "
            "sk-or-v1-THIS-MUST-NOT-BE-PERSISTED"
        )

    def run_qa(self, delivery):
        raise AssertionError(
            "QA must not run"
        )


def test_worker_failure_message_is_sanitized(
    tmp_path: Path,
):
    _, missions, deliveries = (
        make_services(tmp_path)
    )

    service = CodeChangeService(
        mission_service=missions,
        delivery_service=deliveries,
        runner_factory=(
            lambda repository: ExplodingRunner()
        ),
    )

    queued = service.queue_candidate(
        repository="ai-hq",
        instruction="Make a safe UI change.",
    )

    with pytest.raises(RuntimeError):
        service.process_queued_candidate(
            mission_id=queued.mission_id,
        )

    mission = missions.get_mission(
        queued.mission_id
    )

    assert mission.status is MissionStatus.FAILED

    assert mission.error_state == {
        "code": "code_change_preparation_failed",
        "message": (
            "Code-change candidate preparation failed."
        ),
    }

    assert "sk-or" not in str(
        mission.error_state
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation requires elevated privileges on Windows",
)
def test_dripvid_reuses_shared_node_modules(
    tmp_path: Path,
):
    source = tmp_path / "dripvid"
    source.mkdir()

    package = (
        source
        / "node_modules"
        / "example"
    )
    package.mkdir(parents=True)

    (
        package / "index.js"
    ).write_text(
        "module.exports = true;\n",
        encoding="utf-8",
    )

    profile = (
        build_dripvid_repository_profile(
            source_path=source,
        )
    )

    registry = (
        RepositoryProfileRegistry(
            (profile,)
        )
    )

    sandbox = (
        IsolatedRepositorySandbox(
            profile_registry=registry,
            repository_key="dripvid",
            sandbox_root=(
                tmp_path / "sandboxes"
            ),
        )
    )

    workspace = sandbox.prepare(
        mission_id="mission-1"
    )

    state = sandbox._workspaces[
        workspace.workspace_id
    ]

    node_modules = (
        state.path / "node_modules"
    )

    assert node_modules.is_symlink()

    assert node_modules.resolve() == (
        source / "node_modules"
    ).resolve()
