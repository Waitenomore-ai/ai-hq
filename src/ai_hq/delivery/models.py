from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class DeliveryStage(StrEnum):
    DEVELOPER = "DEVELOPER"
    QA = "QA"
    WAITING_APPROVAL = "WAITING_APPROVAL"


class QAResult(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class Delivery(Base):
    __tablename__ = "mission_deliveries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    stage: Mapped[DeliveryStage] = mapped_column(
        Enum(DeliveryStage, native_enum=False),
        default=DeliveryStage.DEVELOPER,
        nullable=False,
        index=True,
    )

    change_ref: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    changed_files: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    developer_evidence: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    qa_result: Mapped[QAResult | None] = mapped_column(
        Enum(QAResult, native_enum=False),
        nullable=True,
    )

    qa_evidence: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    approval_reference: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
