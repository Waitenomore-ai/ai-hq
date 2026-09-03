import re
from datetime import UTC, datetime

from sqlalchemy import select

from ai_hq.missions.service import SessionFactory
from ai_hq.notifications.models import Notification, NotificationSeverity

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"session[_-]?secret|client[_-]?secret|authorization)\s*[:=]"
)


def _contains_secret_like_material(*values: str) -> bool:
    return any(_SECRET_PATTERN.search(value or "") for value in values)


class NotificationService:
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def _validate_content(self, title: str, message: str, group_key: str) -> None:
        if not title.strip():
            raise ValueError("notification title cannot be empty")
        if not message.strip():
            raise ValueError("notification message cannot be empty")
        if not group_key.strip():
            raise ValueError("notification group key cannot be empty")
        if _contains_secret_like_material(title, message):
            raise ValueError("secret-like material cannot be stored in notifications")

    def notify(
        self,
        *,
        severity: NotificationSeverity | str,
        title: str,
        message: str,
        group_key: str,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Notification:
        self._validate_content(title, message, group_key)
        severity_value = NotificationSeverity(severity)
        now = datetime.now(UTC)
        with self.session_factory() as db:
            existing = db.scalar(
                select(Notification)
                .where(
                    Notification.group_key == group_key,
                    Notification.read_at.is_(None),
                    Notification.dismissed_at.is_(None),
                )
                .order_by(Notification.last_occurred_at.desc())
            )
            if existing is not None:
                existing.severity = severity_value
                existing.title = title.strip()
                existing.message = message.strip()
                existing.source_type = source_type
                existing.source_id = source_id
                existing.occurrence_count += 1
                existing.last_occurred_at = now
                db.commit()
                db.refresh(existing)
                return existing

            notification = Notification(
                severity=severity_value,
                title=title.strip(),
                message=message.strip(),
                source_type=source_type,
                source_id=source_id,
                group_key=group_key.strip(),
                occurrence_count=1,
                first_occurred_at=now,
                last_occurred_at=now,
            )
            db.add(notification)
            db.commit()
            db.refresh(notification)
            return notification

    def get_notification(self, notification_id: str) -> Notification:
        with self.session_factory() as db:
            notification = db.get(Notification, notification_id)
            if notification is None:
                raise KeyError(f"notification not found: {notification_id}")
            return notification

    def list_notifications(
        self,
        *,
        include_dismissed: bool = False,
        unread_only: bool = False,
        severity: NotificationSeverity | str | None = None,
    ) -> list[Notification]:
        requested_severity = NotificationSeverity(severity) if severity is not None else None
        with self.session_factory() as db:
            statement = select(Notification)
            if not include_dismissed:
                statement = statement.where(Notification.dismissed_at.is_(None))
            if unread_only:
                statement = statement.where(Notification.read_at.is_(None))
            if requested_severity is not None:
                statement = statement.where(Notification.severity == requested_severity)
            statement = statement.order_by(
                Notification.last_occurred_at.desc(),
                Notification.created_at.desc(),
            )
            return list(db.scalars(statement))

    def unread_count(self) -> int:
        return len(self.list_notifications(unread_only=True))

    def mark_read(self, notification_id: str) -> Notification:
        with self.session_factory() as db:
            notification = db.get(Notification, notification_id)
            if notification is None:
                raise KeyError(f"notification not found: {notification_id}")
            if notification.read_at is None:
                notification.read_at = datetime.now(UTC)
                db.commit()
                db.refresh(notification)
            return notification

    def mark_all_read(self) -> int:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            notifications = list(
                db.scalars(
                    select(Notification).where(
                        Notification.read_at.is_(None),
                        Notification.dismissed_at.is_(None),
                    )
                )
            )
            for notification in notifications:
                notification.read_at = now
            db.commit()
            return len(notifications)

    def dismiss(self, notification_id: str) -> Notification:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            notification = db.get(Notification, notification_id)
            if notification is None:
                raise KeyError(f"notification not found: {notification_id}")
            if notification.read_at is None:
                notification.read_at = now
            if notification.dismissed_at is None:
                notification.dismissed_at = now
            db.commit()
            db.refresh(notification)
            return notification
