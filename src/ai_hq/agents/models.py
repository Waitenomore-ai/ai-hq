from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class AgentStatus(StrEnum):
    IDLE = "IDLE"
    WORKING = "WORKING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False), default=AgentStatus.IDLE, nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_mission_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("missions.id"), nullable=True, index=True
    )
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    performance_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
