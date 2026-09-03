from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.db import Base


class AIUsageRecord(Base):
    __tablename__ = "ai_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mission_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    daily_limit: float | None = None
    monthly_limit: float | None = None


class AIUsageService:
    def __init__(self, session_factory, *, budget: BudgetPolicy | None = None) -> None:
        self.session_factory = session_factory
        self.budget = budget or BudgetPolicy()

    def record(
        self,
        *,
        provider: str,
        model: str,
        agent: str,
        mission_id: str | None,
        input_tokens: int,
        output_tokens: int,
        input_cost_per_million: float,
        output_cost_per_million: float,
        occurred_at: datetime | None = None,
    ) -> AIUsageRecord:
        cost = (
            input_tokens / 1_000_000 * input_cost_per_million
            + output_tokens / 1_000_000 * output_cost_per_million
        )
        record = AIUsageRecord(
            provider=provider,
            model=model,
            agent=agent,
            mission_id=mission_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        with self.session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        return record

    def can_spend(self, estimated_cost: float, *, at: datetime | None = None) -> tuple[bool, str]:
        if estimated_cost <= 0:
            return True, "within_budget"

        now = at or datetime.now(UTC)
        with self.session_factory() as session:
            records = list(session.scalars(select(AIUsageRecord)).all())

        daily_total = sum(
            item.estimated_cost
            for item in records
            if self._same_day(item.occurred_at, now)
        )
        monthly_total = sum(
            item.estimated_cost
            for item in records
            if self._same_month(item.occurred_at, now)
        )

        if (
            self.budget.daily_limit is not None
            and daily_total + estimated_cost > self.budget.daily_limit
        ):
            return False, "daily_budget_exhausted"
        if (
            self.budget.monthly_limit is not None
            and monthly_total + estimated_cost > self.budget.monthly_limit
        ):
            return False, "monthly_budget_exhausted"
        return True, "within_budget"

    def summary(self) -> dict[str, int | float]:
        with self.session_factory() as session:
            records = list(session.scalars(select(AIUsageRecord)).all())
        return {
            "requests": len(records),
            "input_tokens": sum(item.input_tokens for item in records),
            "output_tokens": sum(item.output_tokens for item in records),
            "estimated_cost": sum(item.estimated_cost for item in records),
        }

    @staticmethod
    def _normalise(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _same_day(cls, left: datetime, right: datetime) -> bool:
        left = cls._normalise(left)
        right = cls._normalise(right)
        return left.date() == right.date()

    @classmethod
    def _same_month(cls, left: datetime, right: datetime) -> bool:
        left = cls._normalise(left)
        right = cls._normalise(right)
        return (left.year, left.month) == (right.year, right.month)
