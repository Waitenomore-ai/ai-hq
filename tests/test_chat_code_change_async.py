from dataclasses import dataclass
from types import SimpleNamespace

from ai_hq.chat.controller import ChatController
from ai_hq.missions.models import MissionStatus


@dataclass
class Message:
    role: str
    content: str
    mission_id: str | None = None
    position: int = 1


class Chat:
    def __init__(self):
        self.items = []

    def add_message(self, **kwargs):
        msg = Message(
            role=kwargs["role"],
            content=kwargs["content"],
            mission_id=kwargs.get("mission_id"),
            position=len(self.items) + 1,
        )
        self.items.append(msg)
        return msg

    def messages(self, **_kwargs):
        return list(self.items)


class Changes:
    def __init__(self):
        self.queue_calls = []
        self.result_calls = []

    def queue_candidate(
        self,
        *,
        repository,
        instruction,
    ):
        self.queue_calls.append(
            (repository, instruction)
        )
        return SimpleNamespace(
            mission_id="code-1",
            repository=repository,
        )

    def candidate_result(
        self,
        *,
        mission_id,
    ):
        self.result_calls.append(mission_id)

        return SimpleNamespace(
            mission_id=mission_id,
            repository="dripvid",
            summary="Toolbar reduced",
            change_ref="sha256:" + ("a" * 64),
            changed_files=(
                "public/css/mobile-member.css",
            ),
            ready_for_approval=True,
            high_risk=False,
        )


class Missions:
    def __init__(self):
        self.mission = SimpleNamespace(
            id="code-1",
            status=MissionStatus.QUEUED,
            owner_agent="developer",
            source="hq_chat_code_change",
        )

    def get_mission(self, mission_id):
        assert mission_id == "code-1"
        return self.mission


class Registry:
    pass


def test_chat_queues_code_change_without_running_candidate():
    chat = Chat()
    changes = Changes()
    missions = Missions()

    controller = ChatController(
        chat_service=chat,
        mission_service=missions,
        tool_registry=Registry(),
        model_client=None,
        code_change_service=changes,
    )

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        text="Make the DripVid toolbar smaller",
    )

    assert result.state == "pending"
    assert result.mission_id == "code-1"

    assert changes.queue_calls == [
        (
            "dripvid",
            "Make the DripVid toolbar smaller",
        )
    ]

    assert changes.result_calls == []
    assert "queued" in result.message.content.lower()


def test_chat_refresh_reads_finished_candidate():
    chat = Chat()
    changes = Changes()
    missions = Missions()

    controller = ChatController(
        chat_service=chat,
        mission_service=missions,
        tool_registry=Registry(),
        model_client=None,
        code_change_service=changes,
    )

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        text="Make the DripVid toolbar smaller",
    )

    missions.mission.status = (
        MissionStatus.WAITING_APPROVAL
    )

    refreshed = controller.refresh(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=result.mission_id,
    )

    assert refreshed.state == "waiting_approval"
    assert changes.result_calls == ["code-1"]
    assert "READY FOR APPROVAL" in refreshed.message.content
    assert "No code was published or deployed" in refreshed.message.content
