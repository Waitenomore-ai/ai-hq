import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings
from ai_hq.notifications.models import Notification
from ai_hq.notifications.service import NotificationService


def _notification_payload(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "severity": notification.severity.value,
        "title": notification.title,
        "message": notification.message,
        "source_type": notification.source_type,
        "source_id": notification.source_id,
        "group_key": notification.group_key,
        "occurrence_count": notification.occurrence_count,
        "first_occurred_at": notification.first_occurred_at.isoformat(),
        "last_occurred_at": notification.last_occurred_at.isoformat(),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "dismissed_at": (
            notification.dismissed_at.isoformat() if notification.dismissed_at else None
        ),
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


def install_notification_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    notifications = NotificationService(session_factory)

    def authenticated_session(request: Request):
        db = session_factory()
        resolved = resolve_request_session(request, db, settings)
        if resolved is None:
            db.close()
            return None
        return db, resolved[1]

    def require_csrf(request: Request, db, record):
        csrf_token = request.headers.get("x-csrf-token", "")
        allowed = hmac.compare_digest(csrf_token, record.csrf_token)
        db.close()
        if not allowed:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return None

    @app.get("/api/notifications")
    def list_notifications(
        request: Request,
        unread: bool = False,
        severity: str | None = None,
        include_dismissed: bool = False,
    ):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        try:
            items = notifications.list_notifications(
                unread_only=unread,
                severity=severity,
                include_dismissed=include_dismissed,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return [_notification_payload(item) for item in items]

    @app.get("/api/notifications/unread-count")
    def unread_count(request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        return {"unread": notifications.unread_count()}

    @app.post("/api/notifications/read-all")
    def mark_all_read(request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        return {"marked_read": notifications.mark_all_read()}

    @app.get("/api/notifications/{notification_id}")
    def notification_detail(notification_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        try:
            notification = notifications.get_notification(notification_id)
        except KeyError:
            return JSONResponse({"error": "Notification not found"}, status_code=404)
        return _notification_payload(notification)

    @app.post("/api/notifications/{notification_id}/read")
    def mark_read(notification_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            notification = notifications.mark_read(notification_id)
        except KeyError:
            return JSONResponse({"error": "Notification not found"}, status_code=404)
        return _notification_payload(notification)

    @app.post("/api/notifications/{notification_id}/dismiss")
    def dismiss_notification(notification_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            notification = notifications.dismiss(notification_id)
        except KeyError:
            return JSONResponse({"error": "Notification not found"}, status_code=404)
        return _notification_payload(notification)
