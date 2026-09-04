from __future__ import annotations

import hmac
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel

from ai_hq.chat.controller import ChatController
from ai_hq.chat.model_client import build_chat_model_client
from ai_hq.chat.service import ChatAccessDenied, ChatService
from ai_hq.missions.service import MissionService
from ai_hq.web import _origin_is_allowed, resolve_request_session


class ChatSubmitRequest(BaseModel):
    """The only client-controlled operational input is natural language."""

    # JSON input contract: {"text": "natural-language request"}
    text: str


def _session_identifier(session: Any) -> str:
    for name in ("id", "session_id", "owner_session_id"):
        if isinstance(session, dict):
            value = session.get(name)
        else:
            value = getattr(session, name, None)

        if value:
            return str(value)

    raise HTTPException(
        status_code=401,
        detail="Authentication required",
    )


def _session_csrf(session: Any) -> str | None:
    if isinstance(session, dict):
        value = session.get("csrf_token")
    else:
        value = getattr(session, "csrf_token", None)

    return str(value) if value else None


def _require_session(
    request: Request,
    settings: Any,
) -> tuple[Any, str]:
    try:
        session = resolve_request_session(request, settings)
    except TypeError:
        # Compatibility with the existing one-argument helper contract.
        session = resolve_request_session(request)

    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    return session, _session_identifier(session)


def _require_write_security(
    request: Request,
    settings: Any,
    session: Any,
) -> None:
    if not _origin_is_allowed(request, settings):
        raise HTTPException(
            status_code=403,
            detail="Origin not allowed",
        )

    expected = _session_csrf(session)

    supplied = (
        request.headers.get("x-csrf-token")
        or request.headers.get("x-csrf")
    )

    if (
        not expected
        or not supplied
        or not hmac.compare_digest(expected, supplied)
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF token",
        )


def _conversation_payload(conversation: Any) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "agent_key": conversation.agent_key,
        "created_at": (
            conversation.created_at.isoformat()
            if getattr(conversation, "created_at", None)
            else None
        ),
        "updated_at": (
            conversation.updated_at.isoformat()
            if getattr(conversation, "updated_at", None)
            else None
        ),
    }


def _message_payload(message: Any) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "position": message.position,
        "role": message.role,
        "content": message.content,
        "mission_id": (
            str(message.mission_id)
            if message.mission_id
            else None
        ),
        "created_at": (
            message.created_at.isoformat()
            if getattr(message, "created_at", None)
            else None
        ),
    }


def _controller_payload(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        data = asdict(result)
    else:
        data = {
            "state": getattr(result, "state"),
            "message": getattr(result, "message"),
            "mission_id": getattr(result, "mission_id", None),
        }

    message = data.get("message")

    if message is not None and not isinstance(message, str):
        message = _message_payload(message)

    mission_id = data.get("mission_id")

    return {
        "state": data.get("state"),
        "message": message,
        "mission_id": str(mission_id) if mission_id else None,
    }


def _translate_access_denied(exc: ChatAccessDenied) -> None:
    raise HTTPException(
        status_code=404,
        detail="Conversation not found",
    ) from exc



class ValidationToolRegistry:
    """Validation-only registry used while persisting chat mission plans."""

    _tools = frozenset({
        "system.health.read",
        "service.status.read",
        "service.logs.read",
    })

    def resolve(self, tool_name: str) -> str:
        if tool_name not in self._tools:
            raise KeyError(
                f"Tool is not available to SysAdmin Chat: {tool_name}"
            )
        return tool_name


def install_chat_routes(
    app: Any,
    *,
    settings: Any,
    session_factory: Any,
) -> None:
    """
    Install authenticated SysAdmin Chat routes using the same dependency
    pattern as the rest of AI HQ.

    HTTP boundary:
      session -> ownership -> Origin/CSRF -> ChatController

    Operational boundary:
      ChatController -> persisted MissionService plan

    This module never invokes Host Helper or infrastructure directly.
    """

    chat_service = ChatService(session_factory)
    mission_service = MissionService(session_factory)
    tool_registry = ValidationToolRegistry()
    model_client = build_chat_model_client(settings)

    chat_controller = ChatController(
        chat_service=chat_service,
        mission_service=mission_service,
        tool_registry=tool_registry,
        model_client=model_client,
    )

    @app.get("/api/chat/conversations")
    def list_chat_conversations(request: Request):
        _session, owner_session_id = _require_session(
            request,
            settings,
        )

        conversations = chat_service.list_conversations(
            owner_session_id=owner_session_id,
        )

        return {
            "conversations": [
                _conversation_payload(item)
                for item in conversations
            ],
        }

    @app.post("/api/chat/conversations")
    def create_chat_conversation(request: Request):
        session, owner_session_id = _require_session(
            request,
            settings,
        )

        _require_write_security(
            request,
            settings,
            session,
        )

        conversation = chat_service.create_conversation(
            owner_session_id=owner_session_id,
            agent_key="sysadmin",
        )

        return {
            "conversation": _conversation_payload(conversation),
        }

    @app.get(
        "/api/chat/conversations/{conversation_id}/messages"
    )
    def list_chat_messages(
        conversation_id: str,
        request: Request,
    ):
        _session, owner_session_id = _require_session(
            request,
            settings,
        )

        try:
            messages = chat_service.messages(
                conversation_id=conversation_id,
                owner_session_id=owner_session_id,
            )
        except ChatAccessDenied as exc:
            _translate_access_denied(exc)

        return {
            "messages": [
                _message_payload(item)
                for item in messages
            ],
        }

    @app.post(
        "/api/chat/conversations/{conversation_id}/messages"
    )
    def submit_chat_message(
        conversation_id: str,
        body: ChatSubmitRequest,
        request: Request,
    ):
        session, owner_session_id = _require_session(
            request,
            settings,
        )

        _require_write_security(
            request,
            settings,
            session,
        )

        text = body.text.strip()

        if not text:
            raise HTTPException(
                status_code=422,
                detail="Chat message cannot be empty",
            )

        try:
            result = chat_controller.submit(
                conversation_id=conversation_id,
                owner_session_id=owner_session_id,
                text=text,
            )
        except ChatAccessDenied as exc:
            _translate_access_denied(exc)

        return _controller_payload(result)

    @app.get(
        "/api/chat/conversations/"
        "{conversation_id}/missions/{mission_id}"
    )
    def refresh_chat_mission(
        conversation_id: str,
        mission_id: str,
        request: Request,
    ):
        _session, owner_session_id = _require_session(
            request,
            settings,
        )

        try:
            result = chat_controller.refresh(
                conversation_id=conversation_id,
                owner_session_id=owner_session_id,
                mission_id=mission_id,
            )
        except ChatAccessDenied as exc:
            _translate_access_denied(exc)

        return _controller_payload(result)
