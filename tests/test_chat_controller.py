from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_hq.chat.controller import ChatController
from ai_hq.chat.service import ChatService
from ai_hq.db import Base
from ai_hq.missions.models import (
    MissionRisk,
    MissionStatus,
    MissionStepStatus,
)
from ai_hq.missions.service import MissionService


@pytest.fixture
def session_factory(tmp_path: Path):
    database_path = tmp_path / "chat-controller.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    import ai_hq.models  # noqa: F401

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


class FakeRegistry:
    def resolve(self, capability: str):
        allowed = {
            "system.health.read",
            "service.status.read",
            "service.logs.read",
        }
        if capability not in allowed:
            raise KeyError(capability)
        return object()


class RecordingModel:
    def __init__(self, reply_text: str = "Model reply") -> None:
        self.reply_text = reply_text
        self.calls = []

    def reply(self, system_prompt, messages):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
            }
        )
        return self.reply_text


@dataclass
class NoModel:
    pass


def build_controller(
    session_factory,
    *,
    model=None,
):
    return ChatController(
        chat_service=ChatService(session_factory),
        mission_service=MissionService(session_factory),
        tool_registry=FakeRegistry(),
        model_client=model,
    )


def test_conversation_uses_model_without_creating_mission(session_factory):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("I can inspect AI HQ health, status and logs.")
    controller = build_controller(session_factory, model=model)

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Hello SysAdmin, what can you help me with?",
    )

    assert result.state == "complete"
    assert result.mission_id is None
    assert result.message.content == (
        "I can inspect AI HQ health, status and logs."
    )

    assert MissionService(session_factory).list_missions() == []

    messages = chat.messages(
        conversation_id=conversation.id,
        owner_session_id="session-1",
    )
    assert [message.role for message in messages] == [
        "user",
        "assistant",
    ]

    assert len(model.calls) == 1
    assert model.calls[0]["messages"][-1] == {
        "role": "user",
        "content": "Hello SysAdmin, what can you help me with?",
    }


def test_conversation_fails_clearly_when_no_model_is_configured(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    controller = build_controller(session_factory, model=None)

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Hello SysAdmin",
    )

    assert result.state == "unavailable"
    assert result.mission_id is None
    assert "model" in result.message.content.lower()
    assert "not configured" in result.message.content.lower()

    assert MissionService(session_factory).list_missions() == []


def test_mutation_request_is_refused_without_model_or_mission(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("THIS MUST NOT BE USED")
    controller = build_controller(session_factory, model=model)

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Restart AI HQ",
    )

    assert result.state == "refused"
    assert result.mission_id is None
    assert "read-only" in result.message.content.lower()

    assert MissionService(session_factory).list_missions() == []
    assert model.calls == []


def test_operational_request_creates_read_only_mission_and_plan(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("THIS MUST NOT RUN YET")
    controller = build_controller(session_factory, model=model)

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="How is my server doing?",
    )

    assert result.state == "pending"
    assert result.mission_id
    assert result.message.mission_id == result.mission_id
    assert model.calls == []

    missions = MissionService(session_factory)
    mission = missions.get_mission(result.mission_id)

    assert mission.owner_agent == "sysadmin"
    assert mission.source == "sysadmin_chat"
    assert mission.risk is MissionRisk.GREEN
    assert mission.status is MissionStatus.QUEUED

    steps = missions.list_plan_steps(mission.id)

    assert [step.tool_name for step in steps] == [
        "system.health.read",
        "service.status.read",
        "service.logs.read",
    ]

    assert all(
        step.tool_arguments == {"target": "ai-hq"}
        for step in steps
    )

    assert all(
        step.status is MissionStepStatus.PENDING
        for step in steps
    )


def test_operational_reply_does_not_claim_results_before_completion(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("Everything is healthy.")
    controller = build_controller(session_factory, model=model)

    submitted = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Check system health",
    )

    result = controller.refresh(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        mission_id=submitted.mission_id,
    )

    assert result.state == "pending"
    assert result.mission_id == submitted.mission_id
    assert model.calls == []


def test_completed_operational_mission_grounds_model_in_step_results(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("AI HQ health check completed successfully.")
    controller = build_controller(session_factory, model=model)

    submitted = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Check system health",
    )

    missions = MissionService(session_factory)
    step = missions.list_plan_steps(submitted.mission_id)[0]

    claimed = missions.claim_next_pending_step(submitted.mission_id)
    assert claimed is not None
    assert claimed.id == step.id

    missions.transition_step(
        step.id,
        MissionStepStatus.SUCCEEDED,
        result={
            "outcome": "SIMULATED",
            "healthy": True,
            "summary": "simulation-only health result",
        },
    )

    # Mission lifecycle methods differ from step lifecycle, so use the
    # public transition method exposed by MissionService.
    missions.transition(
        submitted.mission_id,
        MissionStatus.RUNNING,
    )
    missions.transition(
        submitted.mission_id,
        MissionStatus.COMPLETED,
        result={"summary": "mission completed"},
    )

    result = controller.refresh(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        mission_id=submitted.mission_id,
    )

    assert result.state == "complete"
    assert result.message.mission_id == submitted.mission_id
    assert result.message.content == (
        "AI HQ health check completed successfully."
    )

    assert len(model.calls) == 1

    call_text = repr(model.calls[0])
    assert "SIMULATED" in call_text
    assert "simulation-only health result" in call_text

    # Grounding prompt must prevent the model from upgrading simulated
    # evidence into a claim of real host execution.
    assert "simulation" in model.calls[0]["system_prompt"].lower()
    assert "evidence" in model.calls[0]["system_prompt"].lower()


def test_failed_mission_returns_grounded_failure_without_inventing_success(
    session_factory,
):
    chat = ChatService(session_factory)
    conversation = chat.create_conversation("session-1")
    model = RecordingModel("THIS MUST NOT CLAIM SUCCESS")
    controller = build_controller(session_factory, model=model)

    submitted = controller.submit(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        text="Check system health",
    )

    missions = MissionService(session_factory)

    missions.transition(
        submitted.mission_id,
        MissionStatus.RUNNING,
    )
    missions.transition(
        submitted.mission_id,
        MissionStatus.FAILED,
        error_state={"reason": "helper unavailable"},
    )

    result = controller.refresh(
        owner_session_id="session-1",
        conversation_id=conversation.id,
        mission_id=submitted.mission_id,
    )

    assert result.state == "failed"
    assert result.message.mission_id == submitted.mission_id
    assert "failed" in result.message.content.lower()
    assert "helper unavailable" in result.message.content.lower()

    # Failure reporting is deterministic. The model is not allowed to
    # turn missing operational evidence into a success claim.
    assert model.calls == []


def test_cannot_refresh_another_conversations_mission(session_factory):
    chat = ChatService(session_factory)

    first = chat.create_conversation("session-1")
    second = chat.create_conversation("session-2")

    controller = build_controller(
        session_factory,
        model=RecordingModel(),
    )

    submitted = controller.submit(
        owner_session_id="session-1",
        conversation_id=first.id,
        text="Check system health",
    )

    with pytest.raises(Exception):
        controller.refresh(
            owner_session_id="session-2",
            conversation_id=second.id,
            mission_id=submitted.mission_id,
        )


def test_sysadmin_v2_current_status_outranks_historical_log_failures():
    from ai_hq.chat.controller import GROUNDED_SYSTEM_PROMPT
    prompt = GROUNDED_SYSTEM_PROMPT.lower()
    assert "current" in prompt
    assert "historical" in prompt
    assert "service status" in prompt
    assert any(x in prompt for x in ("outrank", "takes precedence", "prefer"))
    assert any(x in prompt for x in ("still occurring", "currently occurring", "current failure"))
