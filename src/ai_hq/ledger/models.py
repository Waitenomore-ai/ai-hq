from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class LedgerEventType(StrEnum):
    MISSION_CREATED = "mission.created"
    MISSION_STATUS_CHANGED = "mission.status_changed"
    ACTION_PROPOSED = "action.proposed"
    PERMISSION_CHECKED = "permission.checked"
    RISK_CHECKED = "risk.checked"
    APPROVAL_RECORDED = "approval.recorded"
    TOOL_EXECUTED = "tool.executed"
    RESULT_RECORDED = "result.recorded"


class LedgerEvent(Base):
    __tablename__ = "operations_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("missions.id"), nullable=False, index=True
    )
    agent_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[LedgerEventType] = mapped_column(
        Enum(LedgerEventType, native_enum=False), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_data: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
