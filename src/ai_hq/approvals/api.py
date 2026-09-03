from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.approvals.models import ApprovalRequest
from ai_hq.approvals.service import ApprovalService
from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings


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
