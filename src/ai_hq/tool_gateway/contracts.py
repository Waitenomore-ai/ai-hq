from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from ai_hq.missions.models import MissionRisk


class ToolOutcomeState(StrEnum):
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    SIMULATED = "simulated"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolRequest:
    mission_id: str
    agent_key: str
    capability: str
    target: str
    risk: MissionRisk
    params: dict[str, object] = field(default_factory=dict)
    conditions: dict[str, object] = field(default_factory=dict)
    mutates_external_state: bool = False


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    state: ToolOutcomeState
    capability: str
    result: dict[str, object] | None = None
    reason: str | None = None
    approval_request_id: str | None = None


class ToolAdapter(Protocol):
    capability: str

    def execute(self, request: ToolRequest) -> dict[str, object]: ...
