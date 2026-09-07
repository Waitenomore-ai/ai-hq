from dataclasses import dataclass

from ai_hq.chat.controller import ChatController


@dataclass
class FakeMessage:
    id: str = "msg-1"
    position: int = 1
    role: str = "assistant"
    content: str = ""
    mission_id: str | None = None
    created_at: object | None = None


@dataclass
class FakeCodeChangeResult:
    mission_id: str = "mission-code-1"
    repository: str = "dripvid"
    summary: str = "Toolbar reduced"
    change_ref: str = "sha256:" + ("a" * 64)
    changed_files: tuple[str, ...] = (
        "public/css/app.css",
    )
    developer_evidence: dict = None
    qa_result: object = None
    qa_evidence: dict = None
    approval_reference: str | None = "approval-1"
    ready_for_approval: bool = True
    high_risk: bool = False
    published: bool = False
    deployed: bool = False

    def __post_init__(self):
        if self.developer_evidence is None:
            self.developer_evidence = {
                "tests": {
                    "passed": True,
                    "exit_code": 0,
                }
            }

        if self.qa_evidence is None:
            self.qa_evidence = {
                "review": "passed"
            }


class FakeChatService:
    def __init__(self):
        self.messages_added = []

    def add_message(self, **kwargs):
        self.messages_added.append(kwargs)

        return FakeMessage(
            position=len(self.messages_added),
            role=kwargs["role"],
            content=kwargs["content"],
            mission_id=kwargs.get("mission_id"),
        )

    def messages(
        self,
        *,
        conversation_id,
        owner_session_id,
    ):
        del conversation_id
        del owner_session_id

        return [
            FakeMessage(
                position=index,
                role=item["role"],
                content=item["content"],
                mission_id=item.get("mission_id"),
            )
            for index, item in enumerate(
                self.messages_added,
                start=1,
            )
        ]


class FakeCodeChangeService:
    def __init__(self):
        self.calls = []
        self.result_calls = []

    def queue_candidate(
        self,
        *,
        repository,
        instruction,
    ):
        self.calls.append(
            (repository, instruction)
        )

        return type(
            "QueuedCodeChange",
            (),
            {
                "mission_id": "mission-code-1",
                "repository": repository,
            },
        )()

    def candidate_result(
        self,
        *,
        mission_id,
    ):
        self.result_calls.append(
            mission_id
        )

        return FakeCodeChangeResult(
            mission_id=mission_id,
        )


class DummyMissionService:
    pass


class DummyToolRegistry:
    pass


def build_controller():
    chat = FakeChatService()
    changes = FakeCodeChangeService()

    controller = ChatController(
        chat_service=chat,
        mission_service=DummyMissionService(),
        tool_registry=DummyToolRegistry(),
        model_client=None,
        code_change_service=changes,
    )

    return controller, chat, changes


def test_chat_code_change_calls_code_change_service():
    controller, _chat, changes = build_controller()

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        text="Make the DripVid toolbar smaller",
    )

    assert changes.calls == [
        (
            "dripvid",
            "Make the DripVid toolbar smaller",
        )
    ]

    assert result.state == "pending"
    assert result.mission_id == "mission-code-1"
    assert changes.result_calls == []


def test_chat_queue_summary_is_bounded_and_clear():
    controller, _chat, changes = build_controller()

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        text="Make the DripVid toolbar smaller",
    )

    content = result.message.content

    assert "dripvid" in content.lower()
    assert "queued" in content.lower()
    assert "worker" in content.lower()
    assert changes.result_calls == []
    assert (
        "no code was published or deployed"
        in content.lower()
    )


def test_existing_conversation_path_still_works_without_code_service():
    chat = FakeChatService()

    class FakeModel:
        def reply(self, *_args, **_kwargs):
            return "Hello"

    controller = ChatController(
        chat_service=chat,
        mission_service=DummyMissionService(),
        tool_registry=DummyToolRegistry(),
        model_client=FakeModel(),
    )

    result = controller.submit(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        text="Hello HQ",
    )

    assert result.state == "complete"
