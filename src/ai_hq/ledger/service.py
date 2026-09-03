from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_hq.ledger.models import LedgerEvent, LedgerEventType

SessionFactory = Callable[[], Session]


class OperationsLedger:
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def record(
        self,
        *,
        mission_id: str,
        event_type: LedgerEventType | str,
        summary: str,
        agent_key: str | None = None,
        metadata: dict | None = None,
    ) -> LedgerEvent:
        event = LedgerEvent(
            mission_id=mission_id,
            agent_key=agent_key,
            event_type=LedgerEventType(event_type),
            summary=summary,
            event_data=metadata or {},
        )
        with self.session_factory() as db:
            db.add(event)
            db.commit()
            db.refresh(event)
            return event

    def for_mission(self, mission_id: str) -> list[LedgerEvent]:
        with self.session_factory() as db:
            return list(
                db.scalars(
                    select(LedgerEvent)
                    .where(LedgerEvent.mission_id == mission_id)
                    .order_by(LedgerEvent.sequence)
                )
            )
