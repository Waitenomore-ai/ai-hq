from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.agents.registry import AgentRegistry
from ai_hq.db import Base

MCP_READ_PERMISSIONS = {
    "dripvid.health.read",
    "dripvid.release.read",
    "dripvid.config.read",
    "dripvid.service.status.read",
}


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


def test_phase1_agents_start_idle_with_only_approved_mcp_read_permissions():
    registry = build_registry()
    agents = registry.ensure_phase1_agents()
    assert all(agent.status is AgentStatus.IDLE for agent in agents)
    for agent in agents:
        if agent.key == "sysadmin":
            assert set(agent.permissions) == MCP_READ_PERMISSIONS
        else:
            assert agent.permissions == []
    sysadmin = registry.get_by_key("sysadmin")
    assert "arbitrary_root_shell" not in sysadmin.capabilities
    assert "docker_socket" not in sysadmin.capabilities
    assert "service.restart" not in sysadmin.permissions
    assert "deployment.deploy" not in sysadmin.permissions


def test_phase1_registry_adds_mcp_reads_without_removing_existing_permissions():
    registry = build_registry()
    registry.ensure_phase1_agents()
    with registry.session_factory() as db:
        sysadmin = db.query(Agent).filter_by(key="sysadmin").one()
        sysadmin.permissions = ["existing.read"]
        db.commit()

    registry.ensure_phase1_agents()
    sysadmin = registry.get_by_key("sysadmin")
    assert set(sysadmin.permissions) == MCP_READ_PERMISSIONS | {"existing.read"}
