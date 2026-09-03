from ai_hq.notifications.models import NotificationSeverity
from ai_hq.notifications.service import NotificationService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return NotificationService(sessionmaker(bind=engine, expire_on_commit=False))


def test_related_active_notifications_consolidate_and_preserve_count():
    service = build_service()
    first = service.notify(
        severity=NotificationSeverity.ATTENTION,
        title="Worker health degraded",
        message="Worker health check failed.",
        source_type="worker",
        source_id="worker-1",
        group_key="worker-health:worker-1",
    )
    second = service.notify(
        severity=NotificationSeverity.ATTENTION,
        title="Worker health degraded",
        message="Worker health check failed again.",
        source_type="worker",
        source_id="worker-1",
        group_key="worker-health:worker-1",
    )
    assert second.id == first.id
    assert second.occurrence_count == 2
    assert second.message.endswith("again.")
    assert second.last_occurred_at >= second.first_occurred_at
    assert len(service.list_notifications()) == 1


def test_read_notification_stops_future_alert_from_being_folded_into_old_record():
    service = build_service()
    first = service.notify(
        severity="information",
        title="Backup complete",
        message="Nightly backup completed.",
        group_key="backup:nightly",
    )
    service.mark_read(first.id)
    second = service.notify(
        severity="information",
        title="Backup complete",
        message="Next nightly backup completed.",
        group_key="backup:nightly",
    )
    assert second.id != first.id
    assert service.unread_count() == 1
    assert len(service.list_notifications()) == 2


def test_mark_all_read_and_dismiss_preserve_records_but_hide_dismissed_by_default():
    service = build_service()
    first = service.notify(
        severity="attention",
        title="Storage warning",
        message="Storage passed warning threshold.",
        group_key="storage:warning",
    )
    service.notify(
        severity="approval_required",
        title="Approval needed",
        message="A proposed action requires approval.",
        group_key="approval:mission-1",
    )
    assert service.unread_count() == 2
    assert service.mark_all_read() == 2
    assert service.unread_count() == 0
    service.dismiss(first.id)
    assert first.id not in {item.id for item in service.list_notifications()}
    assert first.id in {item.id for item in service.list_notifications(include_dismissed=True)}


def test_critical_notifications_sort_newest_first():
    service = build_service()
    older = service.notify(
        severity="information",
        title="Info",
        message="First event.",
        group_key="event:first",
    )
    newer = service.notify(
        severity=NotificationSeverity.CRITICAL,
        title="Critical",
        message="Second event.",
        group_key="event:second",
    )
    items = service.list_notifications()
    assert items[0].id == newer.id
    assert items[1].id == older.id


def test_notification_payload_rejects_obvious_secret_material():
    service = build_service()
    for value in (
        "password=super-secret",
        "api_key=abc123",
        "token: bearer-secret",
        "session_secret=something",
    ):
        try:
            service.notify(
                severity="critical",
                title="Secret leak",
                message=value,
                group_key=f"secret:{value[:3]}",
            )
        except ValueError as exc:
            assert "secret" in str(exc).lower()
        else:
            raise AssertionError("secret-like notification content must be rejected")


def test_severity_values_match_phase_one_contract():
    assert {item.value for item in NotificationSeverity} == {
        "information",
        "attention",
        "approval_required",
        "critical",
    }
