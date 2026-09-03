from ai_hq.config import OperatingMode
from ai_hq.models.system_state import SystemState


def test_system_state_defaults_to_safe_simulation():
    state = SystemState()
    assert state.operating_mode == OperatingMode.SAFE.value
    assert state.simulation_mode is True
