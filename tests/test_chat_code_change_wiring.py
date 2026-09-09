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
    rolled_back: bool = False
    deployment_release_id: str | None = None
    deployment_prior_release_id: str | None = None
    rollback_release_id: str | None = None

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


def test_completed_code_change_reply_surfaces_deployment_release():
    controller, chat, _changes = build_controller()

    class DeployedResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
        )
        ready_for_approval = True
        high_risk = False
        published = True
        deployed = True
        deployment_release_id = "dripvid-2026-09-09.rc1"
        deployment_prior_release_id = "dripvid-2026-09-08.prod"

    class DeployedChanges:
        def candidate_result(self, **kwargs):
            return DeployedResult()

    controller.code_change_service = DeployedChanges()

    mission_id = "mission-code-1"
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="deploy",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    assert "Deployed release" in result.message.content
    assert "dripvid-2026-09-09.rc1" in result.message.content
    assert "Rollback release" in result.message.content
    assert "dripvid-2026-09-08.prod" in result.message.content


def test_completed_code_change_reply_surfaces_rollback_release():
    controller, chat, _changes = build_controller()

    class RolledBackResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
        )
        ready_for_approval = True
        high_risk = False
        published = True
        deployed = True
        deployment_release_id = "dripvid-2026-09-09.rc1"
        deployment_prior_release_id = "dripvid-2026-09-08.prod"
        rolled_back = True
        rollback_release_id = "dripvid-2026-09-08.prod"

    class RolledBackChanges:
        def candidate_result(self, **kwargs):
            return RolledBackResult()

    controller.code_change_service = RolledBackChanges()

    mission_id = "mission-code-1"
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="rollback",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    assert "rolled back" in result.message.content.lower()
    assert "Restored release" in result.message.content
    assert "dripvid-2026-09-08.prod" in result.message.content
    assert "Deployed release" not in result.message.content


def test_completed_code_change_reply_keeps_bound_text_when_nothing_deployed():
    controller, _chat, _changes = build_controller()

    class PendingResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
        )
        ready_for_approval = True
        high_risk = False
        published = False
        deployed = False

    class PendingChanges:
        def candidate_result(self, **kwargs):
            return PendingResult()

    controller.code_change_service = PendingChanges()

    mission_id = "mission-code-1"
    chat = controller.chat_service
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="status",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    assert (
        "No code was published or deployed."
        in result.message.content
    )


def test_completed_code_change_reply_reports_file_count():
    controller, chat, _changes = build_controller()

    class MultiFileResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
            "src/components/toolbar.js",
        )
        ready_for_approval = True
        high_risk = False
        published = False
        deployed = False

    class MultiFileChanges:
        def candidate_result(self, **kwargs):
            return MultiFileResult()

    controller.code_change_service = MultiFileChanges()

    mission_id = "mission-code-1"
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="status",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    content = result.message.content

    assert "**Changed files:** 2 files" in content
    assert "- `public/css/app.css`" in content
    assert "- `src/components/toolbar.js`" in content


def test_completed_code_change_reply_surfaces_qa_badge_and_approval_prompt():
    controller, chat, _changes = build_controller()

    class QaResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
        )
        qa_result = "PASSED"
        ready_for_approval = True
        high_risk = False
        published = False
        deployed = False

    class QaChanges:
        def candidate_result(self, **kwargs):
            return QaResult()

    controller.code_change_service = QaChanges()

    mission_id = "mission-code-1"
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="status",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    content = result.message.content

    assert "**QA:** **PASSED**" in content
    assert "**Status:** READY FOR APPROVAL" in content
    assert "> **Reply with** `approve` **to deploy this" in content


def test_completed_code_change_reply_not_ready_has_no_approval_prompt():
    controller, chat, _changes = build_controller()

    class NotReadyResult:
        repository = "dripvid"
        summary = "Toolbar reduced"
        change_ref = "sha256:" + ("a" * 64)
        changed_files = (
            "public/css/app.css",
        )
        qa_result = None
        ready_for_approval = False
        high_risk = True
        published = False
        deployed = False

    class NotReadyChanges:
        def candidate_result(self, **kwargs):
            return NotReadyResult()

    controller.code_change_service = NotReadyChanges()

    mission_id = "mission-code-1"
    chat.add_message(
        conversation_id="conversation-1",
        owner_session_id="session-1",
        role="user",
        content="status",
        mission_id=mission_id,
    )

    result = controller._completed_code_change_reply(
        owner_session_id="session-1",
        conversation_id="conversation-1",
        mission_id=mission_id,
    )

    content = result.message.content

    assert "NOT READY FOR APPROVAL" in content
    assert "HIGH RISK" in content
    assert "Reply with `approve`" not in content
