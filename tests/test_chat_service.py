import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_hq.db import Base
from ai_hq.chat.service import ChatAccessDenied, ChatService


@pytest.fixture
def session_factory(tmp_path):
    database_path = tmp_path / "chat-test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    # Import models that own tables referenced by chat foreign keys
    # before creating metadata.
    import ai_hq.models  # noqa: F401

    Base.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_create_and_list_conversations(session_factory):
    service = ChatService(session_factory)

    created = service.create_conversation("session-a")

    assert created.owner_session_id == "session-a"
    assert created.agent_key == "sysadmin"

    conversations = service.list_conversations("session-a")
    assert [item.id for item in conversations] == [created.id]


def test_messages_are_returned_in_order(session_factory):
    service = ChatService(session_factory)
    conversation = service.create_conversation("session-a")

    first = service.add_message(
        conversation.id,
        "session-a",
        "user",
        "How is my server?",
    )
    second = service.add_message(
        conversation.id,
        "session-a",
        "assistant",
        "I am checking it now.",
    )

    messages = service.messages(conversation.id, "session-a")

    assert [item.id for item in messages] == [first.id, second.id]
    assert [item.position for item in messages] == [1, 2]
    assert [item.role for item in messages] == ["user", "assistant"]
    assert [item.content for item in messages] == [
        "How is my server?",
        "I am checking it now.",
    ]


def test_message_can_link_to_mission(session_factory):
    service = ChatService(session_factory)
    conversation = service.create_conversation("session-a")

    message = service.add_message(
        conversation.id,
        "session-a",
        "assistant",
        "Checking production health.",
        mission_id="mission-123",
    )

    assert message.mission_id == "mission-123"

    stored = service.messages(conversation.id, "session-a")
    assert stored[0].mission_id == "mission-123"


def test_other_session_cannot_read_conversation(session_factory):
    service = ChatService(session_factory)
    conversation = service.create_conversation("session-a")

    with pytest.raises(ChatAccessDenied):
        service.messages(conversation.id, "session-b")


def test_other_session_cannot_add_message(session_factory):
    service = ChatService(session_factory)
    conversation = service.create_conversation("session-a")

    with pytest.raises(ChatAccessDenied):
        service.add_message(
            conversation.id,
            "session-b",
            "user",
            "I should not be allowed in here.",
        )


def test_other_session_does_not_see_conversation_in_list(session_factory):
    service = ChatService(session_factory)
    service.create_conversation("session-a")

    assert service.list_conversations("session-b") == []
