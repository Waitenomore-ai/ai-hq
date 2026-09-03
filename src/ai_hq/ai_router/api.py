from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.ai_router.usage import AIUsageService
from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings


def install_ai_router_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    usage = AIUsageService(session_factory)

    def require_authentication(request: Request):
        db = session_factory()
        resolved = resolve_request_session(request, db, settings)
        db.close()
        if resolved is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return None

    @app.get("/api/ai-router/status")
    def router_status(request: Request):
        denied = require_authentication(request)
        if denied is not None:
            return denied
        return {
            "paid_ai_enabled": False,
            "prefer_local": True,
            "external_execution_enabled": False,
        }

    @app.get("/api/ai-router/usage-summary")
    def usage_summary(request: Request):
        denied = require_authentication(request)
        if denied is not None:
            return denied
        return usage.summary()
