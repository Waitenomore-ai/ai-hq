from types import SimpleNamespace

import pytest

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


class FakeDeliveryRuntime:
    def __init__(self):
        self.handoffs = []

    def handoff_to_developer(
        self,
        *,
        mission_id,
        change_ref,
        summary,
        changed_files=None,
        evidence=None,
    ):
        self.handoffs.append(
            {
                "mission_id": mission_id,
                "change_ref": change_ref,
                "summary": summary,
                "changed_files": list(changed_files or []),
                "evidence": dict(evidence or {}),
            }
        )


class DeliveryCandidateExecutor(FakeExecutor):
    def run_next(self, mission_id):
        self.run_calls.append(mission_id)

        return SimpleNamespace(
            mission_id=mission_id,
            delivery_candidate={
                "change_ref": "abc123immutable",
                "summary": "Developer implementation candidate",
                "changed_files": [
                    "src/ai_hq/example.py",
                    "tests/test_example.py",
                ],
                "evidence": {
                    "tests": "42 passed",
                    "source": "developer",
                },
            },
        )


def test_autonomous_worker_hands_exact_execution_candidate_to_delivery_runtime():
    missions = FakeMissionService(
        [mission("delivery-m1", MissionStatus.QUEUED)],
        {"delivery-m1": [SimpleNamespace(id="s1")]},
    )
    executor = DeliveryCandidateExecutor()
    delivery = FakeDeliveryRuntime()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runtime=delivery,
    )

    result = runner.run_once()

    assert result.mission_id == "delivery-m1"

    assert delivery.handoffs == [
        {
            "mission_id": "delivery-m1",
            "change_ref": "abc123immutable",
            "summary": "Developer implementation candidate",
            "changed_files": [
                "src/ai_hq/example.py",
                "tests/test_example.py",
            ],
            "evidence": {
                "tests": "42 passed",
                "source": "developer",
            },
        }
    ]


def test_autonomous_worker_does_not_create_delivery_without_candidate():
    missions = FakeMissionService(
        [mission("ordinary-m1", MissionStatus.QUEUED)],
        {"ordinary-m1": [SimpleNamespace(id="s1")]},
    )
    executor = FakeExecutor()
    delivery = FakeDeliveryRuntime()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runtime=delivery,
    )

    result = runner.run_once()

    assert result.mission_id == "ordinary-m1"
    assert delivery.handoffs == []


def test_autonomous_worker_delivery_bridge_preserves_exact_change_ref():
    missions = FakeMissionService(
        [mission("immutable-m1", MissionStatus.QUEUED)],
        {"immutable-m1": [SimpleNamespace(id="s1")]},
    )
    executor = DeliveryCandidateExecutor()
    delivery = FakeDeliveryRuntime()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runtime=delivery,
    )

    runner.run_once()

    assert len(delivery.handoffs) == 1
    assert (
        delivery.handoffs[0]["change_ref"]
        == "abc123immutable"
    )


def test_autonomous_worker_delivery_bridge_fails_closed_on_incomplete_candidate():
    class IncompleteCandidateExecutor(FakeExecutor):
        def run_next(self, mission_id):
            self.run_calls.append(mission_id)

            return SimpleNamespace(
                mission_id=mission_id,
                delivery_candidate={
                    # Deliberately no immutable change_ref.
                    "summary": "Unsafe incomplete candidate",
                    "changed_files": ["src/ai_hq/example.py"],
                    "evidence": {"tests": "passed"},
                },
            )

    missions = FakeMissionService(
        [mission("incomplete-m1", MissionStatus.QUEUED)],
        {"incomplete-m1": [SimpleNamespace(id="s1")]},
    )
    executor = IncompleteCandidateExecutor()
    delivery = FakeDeliveryRuntime()

    runner = AutonomousMissionRunner(
        missions=missions,
        executor=executor,
        delivery_runtime=delivery,
    )

    with pytest.raises(ValueError, match="change_ref"):
        runner.run_once()

    assert delivery.handoffs == []
