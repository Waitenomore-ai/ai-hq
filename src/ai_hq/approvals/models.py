from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("missions.id"), nullable=False, index=True
    )
    requester_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    risk: Mapped[MissionRisk] = mapped_column(Enum(MissionRisk, native_enum=False), nullable=False)
    action_plan: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    action_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[ApprovalState] = mapped_column(
        Enum(ApprovalState, native_enum=False), default=ApprovalState.PENDING, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScopedApprovalRule(Base):
    __tablename__ = "scoped_approval_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    risk: Mapped[MissionRisk] = mapped_column(Enum(MissionRisk, native_enum=False), nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_execution_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
