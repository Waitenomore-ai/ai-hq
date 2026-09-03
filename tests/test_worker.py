from types import SimpleNamespace

import pytest

from ai_hq import worker
from ai_hq.config import OperatingMode
from ai_hq.worker import execution_allowed


def test_freeze_mode_blocks_worker_execution():
    assert execution_allowed(OperatingMode.FREEZE) is False


def test_safe_mode_allows_read_only_worker_loop():
    assert execution_allowed(OperatingMode.SAFE) is True


def test_worker_stays_alive_in_safe_mode(monkeypatch):
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(operating_mode=OperatingMode.SAFE),
    )
    monkeypatch.setattr(worker, "redis_ping", lambda: True)

    sleeps = 0

    class StopProbe(RuntimeError):
        pass

    def probe_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise StopProbe

    monkeypatch.setattr(worker.time, "sleep", probe_sleep)

    with pytest.raises(StopProbe):
        worker.run_worker()

    assert sleeps == 2
