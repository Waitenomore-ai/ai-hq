from sqlalchemy import func, select

from ai_hq.chat.models import ChatConversation, ChatMessage


class ChatAccessDenied(LookupError):
    pass


class ChatService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def create_conversation(
        self,
        owner_session_id: str,
        agent_key: str = "sysadmin",
    ) -> ChatConversation:
        if agent_key != "sysadmin":
            raise ValueError("SysAdmin Chat v1 supports only the sysadmin agent")

        with self.session_factory() as db:
            conversation = ChatConversation(
                owner_session_id=owner_session_id,
                agent_key=agent_key,
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            db.expunge(conversation)
            return conversation

    def list_conversations(
        self,
        owner_session_id: str,
    ) -> list[ChatConversation]:
        with self.session_factory() as db:
            rows = db.scalars(
                select(ChatConversation)
                .where(ChatConversation.owner_session_id == owner_session_id)
                .order_by(ChatConversation.created_at, ChatConversation.id)
            ).all()
            for row in rows:
                db.expunge(row)
            return list(rows)

    def _owned_conversation(
        self,
        db,
        conversation_id: str,
        owner_session_id: str,
    ) -> ChatConversation:
        conversation = db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_session_id == owner_session_id,
            )
        )
        if conversation is None:
            raise ChatAccessDenied("Conversation not found")
        return conversation

    def add_message(
        self,
        conversation_id: str,
        owner_session_id: str,
        role: str,
        content: str,
        mission_id: str | None = None,
    ) -> ChatMessage:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Invalid chat role")

        with self.session_factory() as db:
            self._owned_conversation(
                db,
                conversation_id,
                owner_session_id,
            )
            current_position = db.scalar(
                select(func.max(ChatMessage.position)).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )

            message = ChatMessage(
                conversation_id=conversation_id,
                position=(current_position or 0) + 1,
                role=role,
                content=content,
                mission_id=mission_id,
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            db.expunge(message)
            return message

    def messages(
        self,
        conversation_id: str,
        owner_session_id: str,
    ) -> list[ChatMessage]:
        with self.session_factory() as db:
            self._owned_conversation(
                db,
                conversation_id,
                owner_session_id,
            )
            rows = db.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.position)
            ).all()
            for row in rows:
                db.expunge(row)
            return list(rows)
