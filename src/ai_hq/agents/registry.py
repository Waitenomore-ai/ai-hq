from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_hq.agents.models import Agent

SessionFactory = Callable[[], Session]

_PHASE1_AGENTS = (
    {
        "key": "commander",
        "display_name": "Commander",
        "role": "Primary coordinator and mission orchestrator",
        "capabilities": [
            "mission.create",
            "mission.delegate",
            "mission.prioritize",
            "mission.retry",
            "knowledge.read_shared",
            "agents.view_status",
        ],
    },
    {
        "key": "communications",
        "display_name": "Communications",
        "role": "Email and contact intelligence specialist",
        "capabilities": [
            "email.read",
            "email.search",
            "email.summarize",
            "email.draft",
            "contacts.read",
        ],
    },
    {
        "key": "calendar",
        "display_name": "Calendar",
        "role": "Schedule and planning specialist",
        "capabilities": [
            "calendar.read",
            "calendar.free_busy",
            "calendar.summarize",
            "calendar.create_private_reminder",
        ],
    },
    {
        "key": "sysadmin",
        "display_name": "SysAdmin",
        "role": "Restricted infrastructure observation specialist",
        "capabilities": [
            "system.health",
            "container.inspect",
            "container.health",
            "logs.read",
            "disk.inspect",
        ],
    },
)


class AgentRegistry:
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def ensure_phase1_agents(self) -> list[Agent]:
        with self.session_factory() as db:
            existing = {
                agent.key: agent
                for agent in db.scalars(select(Agent).where(Agent.key.in_([a["key"] for a in _PHASE1_AGENTS])))
            }
            for definition in _PHASE1_AGENTS:
                if definition["key"] not in existing:
                    agent = Agent(
                        key=definition["key"],
                        display_name=definition["display_name"],
                        role=definition["role"],
                        capabilities=list(definition["capabilities"]),
                        permissions=[],
                    )
                    db.add(agent)
            db.commit()
            agents = list(
                db.scalars(select(Agent).where(Agent.key.in_([a["key"] for a in _PHASE1_AGENTS])))
            )
            by_key = {agent.key: agent for agent in agents}
            return [by_key[definition["key"]] for definition in _PHASE1_AGENTS]

    def get_by_key(self, key: str) -> Agent:
        with self.session_factory() as db:
            agent = db.scalar(select(Agent).where(Agent.key == key))
            if agent is None:
                raise KeyError(f"agent not found: {key}")
            return agent
