from sqlalchemy.exc import IntegrityError

from ai_hq.config import OperatingMode
from ai_hq.models.system_state import SystemState


def ensure_system_state(session_factory) -> SystemState:
    """Ensure the singleton runtime safety state exists without overwriting it."""
    with session_factory() as db:
        state = db.get(SystemState, 1)
        if state is not None:
            return state

        state = SystemState(
            id=1,
            operating_mode=OperatingMode.FREEZE.value,
            simulation_mode=True,
        )
        db.add(state)
        try:
            db.commit()
        except IntegrityError:
            # Web and worker may race during startup. If another process
            # created the singleton first, preserve that durable state.
            db.rollback()
            state = db.get(SystemState, 1)
            if state is None:
                raise
        return state
