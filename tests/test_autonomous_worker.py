from types import SimpleNamespace

from ai_hq.missions.models import MissionStatus
from ai_hq.missions.worker import AutonomousMissionRunner


class FakeMissionService:
    def __init__(self, missions, plans):
        self._missions = missions
        self._plans = plans

    def list_missions(self):
        return list(self._missions)

    def list_plan_steps(self, mission_id):
        return list(self._plans.get(mission_id, []))


class FakeExecutor:
    def __init__(self):
        self.run_calls = []
        self.resume_calls = []

    def run_next(self, mission_id):
        self.run_calls.append(mission_id)
        return SimpleNamespace(mission_id=mission_id)

    def resume_approved(self, mission_id):
        self.resume_calls.append(mission_id)
        return SimpleNamespace(mission_id=mission_id)


def mission(mission_id, status):
    return SimpleNamespace(id=mission_id, status=status)


def test_worker_advances_persisted_autonomous_plan():
    missions = FakeMissionService(
        [mission("m1", MissionStatus.QUEUED)],
        {"m1": [SimpleNamespace(id="s1")]},
    )
    executor = FakeExecutor()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
    )

    result = runner.run_once()

    assert result.mission_id == "m1"
    assert executor.run_calls == ["m1"]


def test_worker_does_not_claim_legacy_unplanned_mission():
    missions = FakeMissionService(
        [mission("legacy", MissionStatus.QUEUED)],
        {"legacy": []},
    )
    executor = FakeExecutor()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
    )

    assert runner.run_once() is None
    assert executor.run_calls == []


def test_worker_skips_terminal_and_waiting_missions():
    missions = FakeMissionService(
        [
            mission("waiting", MissionStatus.WAITING_APPROVAL),
            mission("done", MissionStatus.COMPLETED),
            mission("failed", MissionStatus.FAILED),
        ],
        {
            "waiting": [SimpleNamespace(id="s1")],
            "done": [SimpleNamespace(id="s2")],
            "failed": [SimpleNamespace(id="s3")],
        },
    )
    executor = FakeExecutor()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
    )

    assert runner.run_once() is None
    assert executor.run_calls == []


def test_worker_resume_routes_through_mission_executor():
    missions = FakeMissionService([], {})
    executor = FakeExecutor()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
    )

    result = runner.resume_approved("m1")

    assert result.mission_id == "m1"
    assert executor.resume_calls == ["m1"]
