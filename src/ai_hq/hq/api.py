from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings
from ai_hq.hq.state import HQStateService


def install_hq_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    state = HQStateService(session_factory)

    @app.get("/api/hq/state")
    def hq_state(request: Request):
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
            if resolved is None:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
        return state.snapshot()
