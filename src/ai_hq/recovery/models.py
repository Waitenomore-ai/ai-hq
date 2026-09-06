from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class RecoveryIncidentState(StrEnum):
    SUSPECT = "suspect"
    DIAGNOSING = "diagnosing"
    RECOVERY_PENDING = "recovery_pending"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


def recovery_state_type() -> Enum:
    return Enum(
        RecoveryIncidentState,
        values_callable=lambda states: [state.value for state in states],
        native_enum=False,
        length=32,
    )


class RecoveryIncident(Base):
    __tablename__ = "recovery_incidents"
    __table_args__ = (
        UniqueConstraint(
            "active_key",
            name="uq_recovery_incidents_active_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    active_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    target: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    component: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    state: Mapped[RecoveryIncidentState] = mapped_column(
        recovery_state_type(),
        nullable=False,
        index=True,
        default=RecoveryIncidentState.SUSPECT,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    first_failure_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_failure_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    diagnostics: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    verification: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    recovery_mission_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_recovery_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    incident_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recovery_incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    component: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    simulated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    result: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
