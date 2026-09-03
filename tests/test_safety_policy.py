from ai_hq.config import OperatingMode
from ai_hq.missions.models import MissionRisk
from ai_hq.safety.policy import ActionIntent, Decision, evaluate_action


def intent(
    risk=MissionRisk.GREEN,
    *,
    mutates_external_state=False,
    scoped_rule_allows=False,
    approved=False,
    authorization_available=True,
):
    return ActionIntent(
        action="system.health",
        target="ai-hq",
        risk=risk,
        mutates_external_state=mutates_external_state,
        scoped_rule_allows=scoped_rule_allows,
        approved=approved,
        authorization_available=authorization_available,
    )


def test_freeze_and_missing_authorization_fail_closed():
    assert evaluate_action(intent(), OperatingMode.FREEZE, simulation_mode=False) is Decision.BLOCK
    assert (
        evaluate_action(
            intent(authorization_available=False), OperatingMode.NORMAL, simulation_mode=False
        )
        is Decision.BLOCK
    )


def test_green_read_only_is_allowed_but_green_external_mutation_requires_approval():
    assert evaluate_action(intent(), OperatingMode.NORMAL, simulation_mode=False) is Decision.ALLOW
    assert (
        evaluate_action(
            intent(mutates_external_state=True), OperatingMode.NORMAL, simulation_mode=False
        )
        is Decision.REQUIRE_APPROVAL
    )


def test_blue_requires_matching_scoped_rule():
    blue = intent(MissionRisk.BLUE, mutates_external_state=True)
    assert evaluate_action(blue, OperatingMode.NORMAL, simulation_mode=False) is Decision.REQUIRE_APPROVAL
    allowed = intent(MissionRisk.BLUE, mutates_external_state=True, scoped_rule_allows=True)
    assert evaluate_action(allowed, OperatingMode.NORMAL, simulation_mode=False) is Decision.ALLOW


def test_amber_requires_action_bound_approval():
    amber = intent(MissionRisk.AMBER, mutates_external_state=True)
    assert evaluate_action(amber, OperatingMode.NORMAL, simulation_mode=False) is Decision.REQUIRE_APPROVAL
    approved = intent(MissionRisk.AMBER, mutates_external_state=True, approved=True)
    assert evaluate_action(approved, OperatingMode.NORMAL, simulation_mode=False) is Decision.ALLOW


def test_red_is_blocked_even_when_marked_approved():
    red = intent(MissionRisk.RED, mutates_external_state=True, approved=True, scoped_rule_allows=True)
    assert evaluate_action(red, OperatingMode.NORMAL, simulation_mode=False) is Decision.BLOCK


def test_safe_mode_blocks_external_mutation_but_allows_read_only_investigation():
    assert evaluate_action(intent(), OperatingMode.SAFE, simulation_mode=False) is Decision.ALLOW
    external = intent(MissionRisk.BLUE, mutates_external_state=True, scoped_rule_allows=True)
    assert evaluate_action(external, OperatingMode.SAFE, simulation_mode=False) is Decision.BLOCK


def test_simulation_never_allows_real_external_mutation():
    external = intent(MissionRisk.BLUE, mutates_external_state=True, scoped_rule_allows=True)
    assert (
        evaluate_action(external, OperatingMode.NORMAL, simulation_mode=True)
        is Decision.SIMULATE_ONLY
    )
    read_only = intent()
    assert evaluate_action(read_only, OperatingMode.NORMAL, simulation_mode=True) is Decision.ALLOW
