from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class MemoryCategory(StrEnum):
    CONFIRMED_FACT = "confirmed_fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"
    WORKING_MEMORY = "working_memory"
    AGENT_MEMORY = "agent_memory"


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    INFERRED = "inferred"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"


class MemoryVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    RESTRICTED = "restricted"


class MemorySensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    CONSEQUENTIAL = "consequential"
    SECRET = "secret"


class KnowledgeMemory(Base):
    __tablename__ = "knowledge_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[MemoryCategory] = mapped_column(
        Enum(MemoryCategory, native_enum=False), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    verification_state: Mapped[VerificationState] = mapped_column(
        Enum(VerificationState, native_enum=False),
        default=VerificationState.UNVERIFIED,
        nullable=False,
        index=True,
    )
    sensitivity: Mapped[MemorySensitivity] = mapped_column(
        Enum(MemorySensitivity, native_enum=False),
        default=MemorySensitivity.NORMAL,
        nullable=False,
    )
    visibility: Mapped[MemoryVisibility] = mapped_column(
        Enum(MemoryVisibility, native_enum=False),
        default=MemoryVisibility.PRIVATE,
        nullable=False,
        index=True,
    )
    allowed_agents: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    temporary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    contradicts_memory_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_memories.id"), nullable=True, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
