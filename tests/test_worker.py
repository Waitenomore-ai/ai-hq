from ai_hq.config import OperatingMode
from ai_hq.worker import execution_allowed


def test_freeze_mode_blocks_worker_execution():
    assert execution_allowed(OperatingMode.FREEZE) is False


def test_safe_mode_allows_read_only_worker_loop():
    assert execution_allowed(OperatingMode.SAFE) is True
