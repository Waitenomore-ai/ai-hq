from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings
from ai_hq.hq.state import HQStateService
from ai_hq.recovery.status import RecoveryStatusService


def install_hq_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    state = HQStateService(
        session_factory,
        recovery_status_service=RecoveryStatusService(session_factory),
        recovery_settings_provider=lambda: {
            "enabled": bool(getattr(settings, "recovery_enabled", False)),
            "observe_only": bool(getattr(settings, "recovery_observe_only", True)),
        },
    )

    @app.get("/api/hq/state")
    def hq_state(request: Request):
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
            if resolved is None:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
        return state.snapshot()
