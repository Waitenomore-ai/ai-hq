from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_hq.db import Base
from ai_hq.recovery.models import RecoveryIncidentState
from ai_hq.recovery.service import RecoveryPersistenceError, RecoveryService


class Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def build_service(tmp_path, *, clock=None):
    import ai_hq.missions.models  # noqa: F401
    import ai_hq.recovery.models  # noqa: F401

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    clock = clock or Clock(datetime(2026, 9, 5, 18, 0, tzinfo=UTC))
    return RecoveryService(factory, clock=clock), factory, clock


def test_failure_threshold_advances_suspect_to_diagnosing(tmp_path):
    service, _factory, clock = build_service(tmp_path)

    first = service.observe_failure("app", diagnostics={"source": "readiness"})
    assert first.state is RecoveryIncidentState.SUSPECT
    assert first.consecutive_failures == 1

    clock.advance(30)
    second = service.observe_failure("app")
    assert second.id == first.id
    assert second.state is RecoveryIncidentState.SUSPECT
    assert second.consecutive_failures == 2

    clock.advance(30)
    third = service.observe_failure("app")
    assert third.id == first.id
    assert third.state is RecoveryIncidentState.DIAGNOSING
    assert third.consecutive_failures == 3


def test_healthy_observation_resolves_and_releases_active_key(tmp_path):
    service, _factory, clock = build_service(tmp_path)

    incident = service.observe_failure("app")
    clock.advance(30)

    resolved = service.resolve_if_healthy(
        "app",
        verification={"readiness": True},
    )

    assert resolved is not None
    assert resolved.id == incident.id
    assert resolved.state is RecoveryIncidentState.RESOLVED
    assert resolved.active_key is None
    assert resolved.consecutive_failures == 0
    assert resolved.verification == {"readiness": True}

    clock.advance(30)
    later = service.observe_failure("app")
    assert later.id != incident.id


def test_too_fast_observation_does_not_increment_threshold(tmp_path):
    service, _factory, clock = build_service(tmp_path)

    first = service.observe_failure("app")
    clock.advance(5)
    duplicate = service.observe_failure("app")

    assert duplicate.id == first.id
    assert duplicate.consecutive_failures == 1

    clock.advance(25)
    second = service.observe_failure("app")
    assert second.consecutive_failures == 2


def test_one_component_reuses_one_active_incident(tmp_path):
    service, _factory, clock = build_service(tmp_path)

    first = service.observe_failure("proxy")
    clock.advance(30)
    second = service.observe_failure("proxy")

    assert second.id == first.id
    assert service.active_incident("proxy").id == first.id


def test_cooldown_blocks_second_real_recovery(tmp_path):
    service, _factory, clock = build_service(tmp_path)
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)

    service.record_attempt(
        incident.id,
        mission_id="mission-1",
        simulated=False,
        outcome="succeeded",
        result={"healthy": True},
    )

    blocked = service.can_recover(incident.id)
    assert blocked.allowed is False
    assert blocked.reason == "cooldown"

    clock.advance(300)
    allowed = service.can_recover(incident.id)
    assert allowed.allowed is True


def test_two_real_attempts_exhaust_rolling_budget(tmp_path):
    service, _factory, clock = build_service(tmp_path)
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)

    for index in range(2):
        service.record_attempt(
            incident.id,
            mission_id=f"mission-{index}",
            simulated=False,
            outcome="failed",
            result={},
        )
        clock.advance(300)

    decision = service.can_recover(incident.id)
    assert decision.allowed is False
    assert decision.reason == "budget_exhausted"
    assert decision.real_attempts == 2


def test_simulated_attempts_do_not_consume_real_budget(tmp_path):
    service, _factory, _clock = build_service(tmp_path)
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)

    for index in range(5):
        service.record_attempt(
            incident.id,
            mission_id=f"sim-{index}",
            simulated=True,
            outcome="simulated",
            result={"simulated": True},
        )

    decision = service.can_recover(incident.id)
    assert decision.allowed is True
    assert decision.real_attempts == 0


def test_old_real_attempts_fall_out_of_rolling_window(tmp_path):
    service, _factory, clock = build_service(tmp_path)
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)

    service.record_attempt(
        incident.id,
        mission_id="old-1",
        simulated=False,
        outcome="failed",
        result={},
    )
    clock.advance(300)
    service.record_attempt(
        incident.id,
        mission_id="old-2",
        simulated=False,
        outcome="failed",
        result={},
    )

    clock.advance(3601)
    decision = service.can_recover(incident.id)

    assert decision.allowed is True
    assert decision.real_attempts == 0


def test_claim_recovery_is_atomic_across_workers(tmp_path):
    service, factory, clock = build_service(tmp_path)
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)

    worker_a = RecoveryService(factory, clock=clock)
    worker_b = RecoveryService(factory, clock=clock)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda worker: worker.claim_recovery(incident.id),
                [worker_a, worker_b],
            )
        )

    assert sorted(results) == [False, True]
    assert service.get_incident(incident.id).state is RecoveryIncidentState.RECOVERING


def test_unknown_component_fails_closed(tmp_path):
    service, _factory, _clock = build_service(tmp_path)

    with pytest.raises(ValueError, match="unknown recovery component"):
        service.observe_failure("nginx.service")


def test_persistence_failure_raises_without_in_memory_fallback():
    def broken_factory():
        raise RuntimeError("database unavailable")

    service = RecoveryService(
        broken_factory,
        clock=lambda: datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    )

    with pytest.raises(RecoveryPersistenceError):
        service.observe_failure("app")
