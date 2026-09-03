from dataclasses import dataclass
from enum import StrEnum

from ai_hq.config import OperatingMode
from ai_hq.missions.models import MissionRisk


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    SIMULATE_ONLY = "simulate_only"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class ActionIntent:
    action: str
    target: str
    risk: MissionRisk
    mutates_external_state: bool = False
    scoped_rule_allows: bool = False
    approved: bool = False
    authorization_available: bool = True


def evaluate_action(
    intent: ActionIntent,
    operating_mode: OperatingMode,
    *,
    simulation_mode: bool,
) -> Decision:
    if not intent.authorization_available or operating_mode is OperatingMode.FREEZE:
        return Decision.BLOCK

    if intent.risk is MissionRisk.RED:
        return Decision.BLOCK

    if operating_mode is OperatingMode.SAFE and intent.mutates_external_state:
        return Decision.BLOCK

    if intent.risk is MissionRisk.BLUE and not intent.scoped_rule_allows:
        return Decision.REQUIRE_APPROVAL

    if intent.risk is MissionRisk.AMBER and not intent.approved:
        return Decision.REQUIRE_APPROVAL

    if intent.risk is MissionRisk.GREEN and intent.mutates_external_state and not intent.approved:
        return Decision.REQUIRE_APPROVAL

    if intent.mutates_external_state and simulation_mode:
        return Decision.SIMULATE_ONLY

    return Decision.ALLOW
