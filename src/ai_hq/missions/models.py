from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class MissionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MissionPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class MissionRisk(StrEnum):
    GREEN = "green"
    BLUE = "blue"
    AMBER = "amber"
    RED = "red"


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    priority: Mapped[MissionPriority] = mapped_column(
        Enum(MissionPriority, native_enum=False), default=MissionPriority.NORMAL, nullable=False
    )
    risk: Mapped[MissionRisk] = mapped_column(
        Enum(MissionRisk, native_enum=False), default=MissionRisk.GREEN, nullable=False
    )
    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus, native_enum=False), default=MissionStatus.QUEUED, nullable=False, index=True
    )
    objectives: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approval_references: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tool_execution_references: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
