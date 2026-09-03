import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import Mission
from ai_hq.missions.service import MissionService


class MissionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    owner_agent: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    priority: str = "normal"
    risk: str = "green"
    objectives: list = Field(default_factory=list)
    dependencies: list = Field(default_factory=list)
    xp_reward: int = Field(default=0, ge=0)


def _mission_payload(mission: Mission) -> dict:
    return {
        "id": mission.id,
        "title": mission.title,
        "description": mission.description,
        "owner_agent": mission.owner_agent,
        "source": mission.source,
        "priority": mission.priority.value,
        "risk": mission.risk.value,
        "status": mission.status.value,
        "objectives": mission.objectives,
        "dependencies": mission.dependencies,
        "result": mission.result,
        "error_state": mission.error_state,
        "xp_reward": mission.xp_reward,
        "created_at": mission.created_at.isoformat(),
        "updated_at": mission.updated_at.isoformat(),
    }


def install_mission_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    ledger = OperationsLedger(session_factory)
    missions = MissionService(session_factory, ledger=ledger)

    def authenticated_session(request: Request):
        db = session_factory()
        resolved = resolve_request_session(request, db, settings)
        if resolved is None:
            db.close()
            return None
        return db, resolved[1]

    @app.get("/api/missions")
    def list_missions(request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        return [_mission_payload(mission) for mission in missions.list_missions()]

    @app.get("/api/missions/{mission_id}")
    def mission_detail(mission_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        try:
            mission = missions.get_mission(mission_id)
        except KeyError:
            return JSONResponse({"error": "Mission not found"}, status_code=404)
        return _mission_payload(mission)

    @app.post("/api/missions", status_code=201)
    async def create_mission(request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        csrf_token = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(csrf_token, record.csrf_token):
            db.close()
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        db.close()

        try:
            payload = MissionCreate.model_validate(await request.json())
        except (ValidationError, ValueError):
            return JSONResponse({"error": "Invalid mission payload"}, status_code=422)

        try:
            mission = missions.create_mission(**payload.model_dump())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return _mission_payload(mission)
