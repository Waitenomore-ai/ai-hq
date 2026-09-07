from types import SimpleNamespace

from ai_hq.code_changes.worker import CodeChangeQueueRunner
from ai_hq.missions.models import MissionStatus


class FakeMissionService:
    def __init__(self, missions):
        self._missions = missions

    def list_missions(self):
        return list(self._missions)


class FakeCodeChangeService:
    def __init__(self, missions):
        self.mission_service = FakeMissionService(missions)
        self.calls = []

    def process_queued_candidate(self, *, mission_id):
        self.calls.append(mission_id)
        return SimpleNamespace(mission_id=mission_id)


def mission(
    mission_id,
    status=MissionStatus.QUEUED,
    source="hq_chat_code_change",
    owner_agent="developer",
):
    return SimpleNamespace(
        id=mission_id,
        status=status,
        source=source,
        owner_agent=owner_agent,
    )


def test_worker_runs_queued_code_change():
    service = FakeCodeChangeService(
        [mission("code-1")]
    )

    runner = CodeChangeQueueRunner(
        code_change_service=service
    )

    result = runner.run_once()

    assert result.mission_id == "code-1"
    assert service.calls == ["code-1"]


def test_worker_ignores_other_missions():
    service = FakeCodeChangeService(
        [
            mission(
                "sysadmin",
                source="sysadmin_chat",
                owner_agent="sysadmin",
            ),
            mission(
                "done",
                status=MissionStatus.COMPLETED,
            ),
        ]
    )

    runner = CodeChangeQueueRunner(
        code_change_service=service
    )

    assert runner.run_once() is None
    assert service.calls == []
