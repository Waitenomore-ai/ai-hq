import hmac
from datetime import UTC, datetime

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.approvals.service import ApprovalService
from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings


def _approval_is_expired(request: ApprovalRequest) -> bool:
    expires_at = request.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _approval_payload(request: ApprovalRequest) -> dict:
    return {
        "id": request.id,
        "mission_id": request.mission_id,
        "requester_agent": request.requester_agent,
        "action": request.action,
        "target": request.target,
        "risk": request.risk.value,
        "action_plan": request.action_plan,
        "action_fingerprint": request.action_fingerprint,
        "state": request.state.value,
        "expires_at": request.expires_at.isoformat(),
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "created_at": request.created_at.isoformat(),
    }


def install_approval_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    approvals = ApprovalService(session_factory)

    def authenticated(request: Request) -> bool:
        with session_factory() as db:
            return resolve_request_session(request, db, settings) is not None

    @app.get("/api/approvals")
    def list_approvals(request: Request, mission_id: str | None = None):
        if not authenticated(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return [_approval_payload(item) for item in approvals.list_requests(mission_id=mission_id)]

    @app.get("/api/approvals/{approval_id}")
    def approval_detail(approval_id: str, request: Request):
        if not authenticated(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        try:
            item = approvals.get_request(approval_id)
        except KeyError:
            return JSONResponse({"error": "Approval not found"}, status_code=404)
        return _approval_payload(item)

    @app.post("/api/approvals/{approval_id}/decide")
    def decide_approval(
        approval_id: str,
        request: Request,
        decision: str = Body(..., embed=True),
    ):
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
        if resolved is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        _raw_token, session = resolved

        if settings.is_production:
            origin = request.headers.get("origin")
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get(
                "x-forwarded-host",
                request.headers.get("host", ""),
            )
            expected_origin = f"{scheme}://{host}".rstrip("/")
            if (
                not origin
                or not hmac.compare_digest(origin.rstrip("/"), expected_origin)
            ):
                return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        supplied = request.headers.get("x-csrf-token") or request.headers.get("x-csrf")
        expected_csrf = getattr(session, "csrf_token", None)
        if (
            not expected_csrf
            or not supplied
            or not hmac.compare_digest(expected_csrf, supplied)
        ):
            return JSONResponse({"error": "Invalid CSRF token"}, status_code=403)

        mapped = {
            "approved": ApprovalState.APPROVED,
            "denied": ApprovalState.DENIED,
        }.get(decision)
        if mapped is None:
            return JSONResponse(
                {"error": "decision must be 'approved' or 'denied'"},
                status_code=422,
            )

        try:
            existing = approvals.get_request(approval_id)
        except KeyError:
            return JSONResponse({"error": "Approval not found"}, status_code=404)

        if _approval_is_expired(existing):
            return JSONResponse(
                {"error": "Approval request has expired"},
                status_code=410,
            )

        try:
            item = approvals.decide(approval_id, mapped)
        except KeyError:
            return JSONResponse({"error": "Approval not found"}, status_code=404)
        except ValueError:
            return JSONResponse(
                {"error": "Approval request already decided"},
                status_code=409,
            )
        return _approval_payload(item)
