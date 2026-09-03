import hmac
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from ai_hq.auth.dependencies import resolve_request_session
from ai_hq.config import Settings
from ai_hq.knowledge.models import KnowledgeMemory
from ai_hq.knowledge.service import KnowledgeService


class KnowledgeCreate(BaseModel):
    category: str
    content: str = Field(min_length=1)
    owner_scope: str = Field(min_length=1, max_length=128)
    provenance: dict
    confidence: float = Field(ge=0, le=1)
    verification_state: str | None = None
    sensitivity: str = "normal"
    visibility: str = "private"
    allowed_agents: list[str] = Field(default_factory=list)
    pinned: bool = False
    locked: bool = False
    temporary: bool = False
    expires_at: datetime | None = None


class KnowledgeUpdate(BaseModel):
    content: str | None = None
    provenance: dict | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_state: str | None = None
    sensitivity: str | None = None
    visibility: str | None = None
    allowed_agents: list[str] | None = None
    pinned: bool | None = None
    temporary: bool | None = None
    expires_at: datetime | None = None


class KnowledgeLock(BaseModel):
    locked: bool


class KnowledgeContradiction(BaseModel):
    content: str = Field(min_length=1)
    provenance: dict
    confidence: float = Field(ge=0, le=1)


def _memory_payload(memory: KnowledgeMemory) -> dict:
    return {
        "id": memory.id,
        "category": memory.category.value,
        "content": memory.content,
        "owner_scope": memory.owner_scope,
        "provenance": memory.provenance,
        "confidence": memory.confidence,
        "verification_state": memory.verification_state.value,
        "sensitivity": memory.sensitivity.value,
        "visibility": memory.visibility.value,
        "allowed_agents": memory.allowed_agents,
        "pinned": memory.pinned,
        "locked": memory.locked,
        "temporary": memory.temporary,
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
        "contradicts_memory_id": memory.contradicts_memory_id,
        "revision": memory.revision,
        "verified_at": memory.verified_at.isoformat() if memory.verified_at else None,
        "deleted_at": memory.deleted_at.isoformat() if memory.deleted_at else None,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
    }


def install_knowledge_routes(app: FastAPI, *, settings: Settings, session_factory) -> None:
    knowledge = KnowledgeService(session_factory)

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

    @app.get("/api/knowledge")
    def list_knowledge(request: Request, q: str = "", category: str | None = None):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        try:
            items = knowledge.search(q, category=category)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return [_memory_payload(item) for item in items]

    @app.get("/api/knowledge/{memory_id}")
    def knowledge_detail(memory_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, _record = authenticated
        db.close()
        try:
            memory = knowledge.get_memory(memory_id)
        except KeyError:
            return JSONResponse({"error": "Knowledge memory not found"}, status_code=404)
        return _memory_payload(memory)

    @app.post("/api/knowledge", status_code=201)
    async def create_knowledge(request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            payload = KnowledgeCreate.model_validate(await request.json())
            memory = knowledge.create_memory(**payload.model_dump())
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return _memory_payload(memory)

    @app.patch("/api/knowledge/{memory_id}")
    async def update_knowledge(memory_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            payload = KnowledgeUpdate.model_validate(await request.json())
            memory = knowledge.update_memory(
                memory_id,
                **payload.model_dump(exclude_unset=True),
            )
        except KeyError:
            return JSONResponse({"error": "Knowledge memory not found"}, status_code=404)
        except (ValidationError, ValueError) as exc:
            status = 409 if "locked" in str(exc).lower() else 422
            return JSONResponse({"error": str(exc)}, status_code=status)
        return _memory_payload(memory)

    @app.post("/api/knowledge/{memory_id}/lock")
    async def set_knowledge_lock(memory_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            payload = KnowledgeLock.model_validate(await request.json())
            memory = knowledge.set_lock(memory_id, payload.locked)
        except KeyError:
            return JSONResponse({"error": "Knowledge memory not found"}, status_code=404)
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return _memory_payload(memory)

    @app.post("/api/knowledge/{memory_id}/contradictions", status_code=201)
    async def create_contradiction(memory_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            payload = KnowledgeContradiction.model_validate(await request.json())
            memory = knowledge.record_contradiction(memory_id, **payload.model_dump())
        except KeyError:
            return JSONResponse({"error": "Knowledge memory not found"}, status_code=404)
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return _memory_payload(memory)

    @app.delete("/api/knowledge/{memory_id}", status_code=204)
    def delete_knowledge(memory_id: str, request: Request):
        authenticated = authenticated_session(request)
        if authenticated is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        db, record = authenticated
        denied = require_csrf(request, db, record)
        if denied is not None:
            return denied
        try:
            knowledge.delete_memory(memory_id)
        except KeyError:
            return JSONResponse({"error": "Knowledge memory not found"}, status_code=404)
        except ValueError as exc:
            status = 409 if "locked" in str(exc).lower() else 422
            return JSONResponse({"error": str(exc)}, status_code=status)
        return Response(status_code=204)
