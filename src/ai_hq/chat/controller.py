from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ai_hq.chat.intents import plan_sysadmin_intent
from ai_hq.chat.model_client import ChatModelClient, ChatModelError
from ai_hq.chat.models import ChatMessage
from ai_hq.chat.service import ChatService
from ai_hq.missions.models import (
    MissionPriority,
    MissionRisk,
    MissionStatus,
)
from ai_hq.missions.service import MissionService
from ai_hq.tool_gateway.registry import ToolRegistry


GENERAL_SYSTEM_PROMPT = """You are SysAdmin inside AI HQ.

You are a conversational systems-administration assistant.

For SysAdmin Chat v1 your operational authority is strictly read-only.
Operational execution is handled by AI HQ's persisted mission pipeline,
not by the language model.

Do not claim that you executed a command, changed a service, deployed,
restarted, rolled back, or modified infrastructure.

Keep responses concise and useful.
"""


GROUNDED_SYSTEM_PROMPT = """You are SysAdmin inside AI HQ.

Answer the user's operational question using ONLY the supplied persisted
mission evidence.

Do not invent observations, commands, host state, service state, logs,
tool output, or execution results that are absent from the evidence.

Treat the evidence as authoritative for this answer.

If evidence says an operation or result was SIMULATED, explicitly preserve
that simulation distinction. Never describe simulated evidence as real host
execution.

SysAdmin Chat v1 is read-only. Do not claim that you changed, restarted,
deployed, rolled back, stopped, started, or otherwise mutated infrastructure.

If the evidence is incomplete, say that it is incomplete.
"""


@dataclass(frozen=True)
class ChatControllerResult:
    state: str
    message: ChatMessage
    mission_id: str | None = None


class ChatController:
    """
    Coordinates persisted chat with persisted missions.

    This class never executes operational tools directly. Operational
    requests are converted into mission plans for the existing autonomous
    worker to execute through MissionExecutor -> ToolGateway.
    """

    def __init__(
        self,
        *,
        chat_service: ChatService,
        mission_service: MissionService,
        tool_registry: ToolRegistry,
        model_client: ChatModelClient | None,
    ) -> None:
        self.chat_service = chat_service
        self.mission_service = mission_service
        self.tool_registry = tool_registry
        self.model_client = model_client

    def submit(
        self,
        *,
        owner_session_id: str,
        conversation_id: str,
        text: str,
    ) -> ChatControllerResult:
        text = text.strip()
        if not text:
            raise ValueError("chat message cannot be empty")

        # Ownership is enforced by ChatService before anything operational
        # can be created.
        self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
            role="user",
            content=text,
        )

        intent = plan_sysadmin_intent(text)

        if intent.kind == "refused":
            message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
                role="assistant",
                content=(
                    intent.refusal_reason
                    if (
                        intent.refusal_reason
                        and "read-only" in intent.refusal_reason.lower()
                    )
                    else (
                        "SysAdmin Chat v1 is read-only. "
                        + (intent.refusal_reason or "")
                    ).strip()
                ),
            )
            return ChatControllerResult(
                state="refused",
                message=message,
            )

        if intent.kind == "conversation":
            return self._conversation_reply(
                owner_session_id=owner_session_id,
                conversation_id=conversation_id,
            )

        if intent.kind != "operational":
            raise ValueError(f"unsupported chat intent: {intent.kind}")

        mission = self.mission_service.create_mission(
            title=self._mission_title(text),
            description=text,
            owner_agent="sysadmin",
            source="sysadmin_chat",
            priority=MissionPriority.NORMAL,
            risk=MissionRisk.GREEN,
            objectives=[text],
            dependencies=[],
        )

        self.mission_service.create_plan(
            mission.id,
            list(intent.steps),
            tool_registry=self.tool_registry,
        )

        message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
            role="assistant",
            content=(
                "I've queued a read-only AI HQ inspection. "
                "I'll report from the persisted mission evidence "
                "when it completes."
            ),
            mission_id=mission.id,
        )

        return ChatControllerResult(
            state="pending",
            message=message,
            mission_id=mission.id,
        )

    def refresh(
        self,
        *,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> ChatControllerResult:
        messages = self.chat_service.messages(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
        )

        linked = [
            message
            for message in messages
            if message.mission_id == mission_id
        ]

        if not linked:
            raise PermissionError(
                "mission is not linked to this conversation"
            )

        mission = self.mission_service.get_mission(mission_id)

        if mission.owner_agent != "sysadmin":
            raise PermissionError(
                "mission is not owned by SysAdmin"
            )

        if mission.source != "sysadmin_chat":
            raise PermissionError(
                "mission was not created by SysAdmin Chat"
            )

        if mission.status is MissionStatus.COMPLETED:
            return self._completed_operational_reply(
                owner_session_id=owner_session_id,
                conversation_id=conversation_id,
                mission_id=mission_id,
            )

        if mission.status in {
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            return self._failed_operational_reply(
                owner_session_id=owner_session_id,
                conversation_id=conversation_id,
                mission_id=mission_id,
            )

        return ChatControllerResult(
            state="pending",
            message=linked[-1],
            mission_id=mission_id,
        )

    def _conversation_reply(
        self,
        *,
        owner_session_id: str,
        conversation_id: str,
    ) -> ChatControllerResult:
        if self.model_client is None:
            message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
                role="assistant",
                content=(
                    "SysAdmin's chat model is not configured. "
                    "Read-only operational planning remains available."
                ),
            )
            return ChatControllerResult(
                state="unavailable",
                message=message,
            )

        history = self._model_history(
            owner_session_id,
            conversation_id,
        )

        try:
            content = self.model_client.reply(
                GENERAL_SYSTEM_PROMPT,
                history,
            )
        except ChatModelError:
            content = (
                "SysAdmin's chat model is currently unavailable. "
                "No operational action was taken."
            )

        message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
            role="assistant",
            content=content,
        )

        return ChatControllerResult(
            state="complete",
            message=message,
        )

    def _completed_operational_reply(
        self,
        *,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> ChatControllerResult:
        existing = self._completed_reply_if_present(
            owner_session_id,
            conversation_id,
            mission_id,
        )
        if existing is not None:
            return existing

        steps = self.mission_service.list_plan_steps(mission_id)

        evidence = [
            {
                "position": step.position,
                "tool_name": step.tool_name,
                "tool_arguments": step.tool_arguments,
                "status": step.status.value,
                "result": step.result,
                "error_state": step.error_state,
            }
            for step in steps
        ]

        if self.model_client is None:
            content = (
                "The read-only inspection completed, but SysAdmin's "
                "chat model is not configured to summarize the persisted "
                "mission evidence."
            )
            state = "unavailable"
        else:
            user_question = self._mission_question(
                owner_session_id,
                conversation_id,
                mission_id,
            )

            model_messages = [
                {
                    "role": "user",
                    "content": (
                        f"Original question:\n{user_question}\n\n"
                        "Persisted mission evidence:\n"
                        f"{json.dumps(evidence, sort_keys=True)}"
                    ),
                }
            ]

            try:
                content = self.model_client.reply(
                    GROUNDED_SYSTEM_PROMPT,
                    model_messages,
                )
                state = "complete"
            except ChatModelError:
                content = (
                    "The read-only inspection completed, but SysAdmin "
                    "could not summarize the persisted evidence because "
                    "the chat model is unavailable."
                )
                state = "unavailable"

        message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
            role="assistant",
            content=content,
            mission_id=mission_id,
        )

        return ChatControllerResult(
            state=state,
            message=message,
            mission_id=mission_id,
        )

    def _failed_operational_reply(
        self,
        *,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> ChatControllerResult:
        existing = self._terminal_reply_if_present(
            owner_session_id,
            conversation_id,
            mission_id,
        )
        if existing is not None:
            return existing

        mission = self.mission_service.get_mission(mission_id)

        detail = self._safe_failure_detail(
            mission.error_state
        )

        content = "The read-only AI HQ inspection failed."
        if detail:
            content += f" {detail}"

        message = self.chat_service.add_message(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
            role="assistant",
            content=content,
            mission_id=mission_id,
        )

        return ChatControllerResult(
            state="failed",
            message=message,
            mission_id=mission_id,
        )

    def _model_history(
        self,
        owner_session_id: str,
        conversation_id: str,
    ) -> list[dict[str, str]]:
        messages = self.chat_service.messages(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
        )

        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in messages
            if message.role in {"user", "assistant"}
        ]

    def _mission_question(
        self,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> str:
        messages = self.chat_service.messages(
            conversation_id=conversation_id,
            owner_session_id=owner_session_id,
        )

        for index, message in enumerate(messages):
            if (
                message.mission_id == mission_id
                and message.role == "assistant"
            ):
                for earlier in reversed(messages[:index]):
                    if earlier.role == "user":
                        return earlier.content

        return "Report the persisted operational evidence."

    def _completed_reply_if_present(
        self,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> ChatControllerResult | None:
        linked = [
            message
            for message in self.chat_service.messages(
                conversation_id=conversation_id,
                owner_session_id=owner_session_id,
            )
            if message.mission_id == mission_id
        ]

        # First linked assistant message is the queued/pending notice.
        # A second linked assistant message is the terminal response.
        if len(linked) >= 2:
            return ChatControllerResult(
                state="complete",
                message=linked[-1],
                mission_id=mission_id,
            )

        return None

    def _terminal_reply_if_present(
        self,
        owner_session_id: str,
        conversation_id: str,
        mission_id: str,
    ) -> ChatControllerResult | None:
        linked = [
            message
            for message in self.chat_service.messages(
                conversation_id=conversation_id,
                owner_session_id=owner_session_id,
            )
            if message.mission_id == mission_id
        ]

        if len(linked) >= 2:
            return ChatControllerResult(
                state="failed",
                message=linked[-1],
                mission_id=mission_id,
            )

        return None

    @staticmethod
    def _safe_failure_detail(
        error_state: Any,
    ) -> str:
        if not error_state:
            return ""

        if isinstance(error_state, dict):
            reason = error_state.get("reason")
            if isinstance(reason, str):
                return reason

            message = error_state.get("message")
            if isinstance(message, str):
                return message

        return str(error_state)

    @staticmethod
    def _mission_title(text: str) -> str:
        clean = " ".join(text.split())
        if len(clean) <= 180:
            return f"SysAdmin Chat: {clean}"
        return f"SysAdmin Chat: {clean[:177]}..."
