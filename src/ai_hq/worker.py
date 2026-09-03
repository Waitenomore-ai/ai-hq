import time

from ai_hq.config import OperatingMode, get_settings
from ai_hq.queue import redis_ping


def execution_allowed(mode: OperatingMode) -> bool:
    return mode is not OperatingMode.FREEZE


def run_worker() -> int:
    settings = get_settings()
    if not redis_ping():
        return 1
    if not execution_allowed(settings.operating_mode):
        return 0

    # Mission consumption is introduced in the Mission Engine slice.
    # For now the worker proves connectivity and respects the global safety gate.
    while execution_allowed(settings.operating_mode):
        time.sleep(5)
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(run_worker())
