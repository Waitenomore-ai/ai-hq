from datetime import UTC, datetime, timedelta

from ai_hq.ai_router.usage import AIUsageService, BudgetPolicy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base


def build_service(*, daily_limit=None, monthly_limit=None):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return AIUsageService(
        sessionmaker(bind=engine, expire_on_commit=False),
        budget=BudgetPolicy(
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
        ),
    )


def test_usage_records_provider_model_agent_mission_tokens_and_estimated_cost():
    service = build_service()
    record = service.record(
        provider="local",
        model="small-model",
        agent="commander",
        mission_id="mission-1",
        input_tokens=1200,
        output_tokens=300,
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
    )
    assert record.provider == "local"
    assert record.model == "small-model"
    assert record.agent == "commander"
    assert record.mission_id == "mission-1"
    assert record.input_tokens == 1200
    assert record.output_tokens == 300
    assert record.estimated_cost == 0.0


def test_cost_estimate_uses_configured_rates():
    service = build_service()
    record = service.record(
        provider="cloud",
        model="reasoner",
        agent="commander",
        mission_id=None,
        input_tokens=1_000_000,
        output_tokens=500_000,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
    )
    assert record.estimated_cost == 2.0


def test_daily_budget_exhaustion_blocks_additional_estimated_cost():
    service = build_service(daily_limit=1.0)
    now = datetime.now(UTC)
    service.record(
        provider="cloud",
        model="free-until-quota",
        agent="commander",
        mission_id=None,
        input_tokens=500_000,
        output_tokens=0,
        input_cost_per_million=1.0,
        output_cost_per_million=0.0,
        occurred_at=now,
    )
    allowed, reason = service.can_spend(0.6, at=now)
    assert allowed is False
    assert reason == "daily_budget_exhausted"


def test_monthly_budget_exhaustion_blocks_additional_estimated_cost():
    service = build_service(monthly_limit=2.0)
    now = datetime.now(UTC)
    service.record(
        provider="cloud",
        model="model",
        agent="calendar",
        mission_id="mission-2",
        input_tokens=1_500_000,
        output_tokens=0,
        input_cost_per_million=1.0,
        output_cost_per_million=0.0,
        occurred_at=now - timedelta(days=1),
    )
    service.record(
        provider="cloud",
        model="model",
        agent="calendar",
        mission_id="mission-3",
        input_tokens=400_000,
        output_tokens=0,
        input_cost_per_million=1.0,
        output_cost_per_million=0.0,
        occurred_at=now,
    )
    allowed, reason = service.can_spend(0.2, at=now)
    assert allowed is False
    assert reason == "monthly_budget_exhausted"


def test_zero_cost_usage_is_allowed_even_when_paid_budget_is_zero():
    service = build_service(daily_limit=0.0, monthly_limit=0.0)
    allowed, reason = service.can_spend(0.0)
    assert allowed is True
    assert reason == "within_budget"
