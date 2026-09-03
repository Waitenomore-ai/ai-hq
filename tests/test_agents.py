from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import AgentStatus
from ai_hq.agents.registry import AgentRegistry
from ai_hq.db import Base


def build_registry():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return AgentRegistry(factory)


def test_phase1_registry_seeds_exactly_four_stable_agents_idempotently():
    registry = build_registry()
    first = registry.ensure_phase1_agents()
    second = registry.ensure_phase1_agents()
    assert {agent.key for agent in first} == {"commander", "communications", "calendar", "sysadmin"}
    assert {agent.key for agent in second} == {"commander", "communications", "calendar", "sysadmin"}
    assert len(second) == 4


def test_phase1_agents_start_idle_without_sensitive_permissions():
    registry = build_registry()
    agents = registry.ensure_phase1_agents()
    assert all(agent.status is AgentStatus.IDLE for agent in agents)
    assert all(agent.permissions == [] for agent in agents)
    sysadmin = registry.get_by_key("sysadmin")
    assert "arbitrary_root_shell" not in sysadmin.capabilities
    assert "docker_socket" not in sysadmin.capabilities


def test_reset_working_clears_only_stale_requested_agents():
    registry = build_registry()
    registry.ensure_phase1_agents()
    registry.set_state(
        "commander", AgentStatus.WORKING, current_mission_id="mission-1"
    )
    registry.set_state(
        "sysadmin", AgentStatus.IDLE, current_mission_id=None
    )

    reset = registry.reset_working(("commander", "sysadmin"))

    assert [agent.key for agent in reset] == ["commander"]
    commander = registry.get_by_key("commander")
    sysadmin = registry.get_by_key("sysadmin")
    assert commander.status is AgentStatus.IDLE
    assert commander.current_mission_id is None
    assert sysadmin.status is AgentStatus.IDLE
