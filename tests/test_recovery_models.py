from datetime import datetime, timezone
import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base


def load_models():
    return importlib.import_module("ai_hq.recovery.models")


def build_session():
    # Register existing mission tables in case recovery records later
    # reference a mission identifier.
    importlib.import_module("ai_hq.missions.models")
    load_models()

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return factory()


def make_incident(models, component="app"):
    now = datetime.now(timezone.utc)

    return models.RecoveryIncident(
        active_key=f"dripvid:{component}",
        target="dripvid",
        component=component,
        state=models.RecoveryIncidentState.SUSPECT,
        consecutive_failures=1,
        first_failure_at=now,
        last_failure_at=now,
        last_observed_at=now,
        diagnostics={},
        verification={},
    )


def test_recovery_models_module_exists():
    assert Path("src/ai_hq/recovery/models.py").is_file()


def test_recovery_incident_states_are_explicit_and_stable():
    models = load_models()

    assert {
        state.value
        for state in models.RecoveryIncidentState
    } == {
        "suspect",
        "diagnosing",
        "recovery_pending",
        "recovering",
        "verifying",
        "resolved",
        "escalated",
    }


def test_only_one_active_incident_can_hold_component_key():
    models = load_models()
    session = build_session()

    first = make_incident(models)
    second = make_incident(models)

    session.add(first)
    session.commit()

    session.add(second)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_terminal_incident_can_release_key_for_future_incident():
    models = load_models()
    session = build_session()

    first = make_incident(models)

    session.add(first)
    session.commit()

    first.state = models.RecoveryIncidentState.RESOLVED
    first.active_key = None
    first.resolved_at = datetime.now(timezone.utc)

    session.commit()

    second = make_incident(models)

    session.add(second)
    session.commit()

    persisted = session.scalars(
        select(models.RecoveryIncident).order_by(
            models.RecoveryIncident.created_at
        )
    ).all()

    assert len(persisted) == 2
    assert persisted[0].active_key is None
    assert persisted[0].state is models.RecoveryIncidentState.RESOLVED
    assert persisted[1].active_key == "dripvid:app"


def test_recovery_attempts_distinguish_simulated_and_real_actions():
    models = load_models()
    session = build_session()

    incident = make_incident(models)

    session.add(incident)
    session.commit()

    now = datetime.now(timezone.utc)

    simulated = models.RecoveryAttempt(
        incident_id=incident.id,
        target="dripvid",
        component="app",
        mission_id=None,
        attempted_at=now,
        simulated=True,
        outcome="simulated",
        result={"simulated": True},
    )

    real = models.RecoveryAttempt(
        incident_id=incident.id,
        target="dripvid",
        component="app",
        mission_id="mission-123",
        attempted_at=now,
        simulated=False,
        outcome="succeeded",
        result={"healthy": True},
    )

    session.add_all([simulated, real])
    session.commit()

    attempts = session.scalars(
        select(models.RecoveryAttempt).order_by(
            models.RecoveryAttempt.simulated.desc()
        )
    ).all()

    assert len(attempts) == 2

    simulated_rows = [
        attempt
        for attempt in attempts
        if attempt.simulated
    ]

    real_rows = [
        attempt
        for attempt in attempts
        if not attempt.simulated
    ]

    assert len(simulated_rows) == 1
    assert len(real_rows) == 1

    assert simulated_rows[0].result == {"simulated": True}
    assert real_rows[0].mission_id == "mission-123"


def test_recovery_tables_have_required_persistence_fields():
    models = load_models()

    incident_columns = set(
        models.RecoveryIncident.__table__.columns.keys()
    )

    assert {
        "id",
        "active_key",
        "target",
        "component",
        "state",
        "consecutive_failures",
        "first_failure_at",
        "last_failure_at",
        "last_observed_at",
        "diagnostics",
        "verification",
        "recovery_mission_id",
        "last_recovery_attempt_at",
        "escalation_reason",
        "resolved_at",
        "created_at",
        "updated_at",
    }.issubset(incident_columns)

    attempt_columns = set(
        models.RecoveryAttempt.__table__.columns.keys()
    )

    assert {
        "id",
        "incident_id",
        "target",
        "component",
        "mission_id",
        "attempted_at",
        "simulated",
        "outcome",
        "result",
    }.issubset(attempt_columns)


def test_recovery_migration_has_expected_revision_chain():
    migration = Path(
        "migrations/versions/0012_recovery_incidents.py"
    )

    assert migration.is_file()

    text = migration.read_text()

    assert 'revision = "0012_recovery_incidents"' in text
    assert 'down_revision = "0011_sysadmin_chat"' in text
    assert '"recovery_incidents"' in text
    assert '"recovery_attempts"' in text
