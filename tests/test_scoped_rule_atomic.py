from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, BrokenBarrierError

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ai_hq.approvals.models import ScopedApprovalRule
from ai_hq.approvals.service import ApprovalService
from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk


def test_final_scoped_rule_use_cannot_be_consumed_twice_concurrently(tmp_path):
    database = tmp_path / "approvals.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    approvals = ApprovalService(factory)
    rule = approvals.create_scoped_rule(
        action="service.recover",
        target="dripvid",
        risk=MissionRisk.BLUE,
        conditions={"policy": "dripvid-2.90", "component": "app"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_execution_count=1,
    )

    # Force the pre-fix read-then-write implementation to let both workers
    # observe execution_count=0 before either writes. An atomic UPDATE-based
    # implementation does not perform these initial SELECTs.
    barrier = Barrier(2)
    synchronized_selects = 0

    @event.listens_for(engine, "after_cursor_execute")
    def synchronize_initial_rule_reads(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal synchronized_selects
        normalized = statement.strip().lower()
        if not normalized.startswith("select"):
            return
        if "scoped_approval_rules" not in normalized:
            return
        if synchronized_selects >= 2:
            return
        synchronized_selects += 1
        try:
            barrier.wait(timeout=0.5)
        except BrokenBarrierError:
            pass

    def consume_once():
        try:
            approvals.consume_rule(rule.id)
            return "consumed"
        except ValueError:
            return "blocked"
        except Exception as exc:  # exposes non-atomic lock/stale-write failures
            return f"error:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume_once(), range(2)))

    event.remove(engine, "after_cursor_execute", synchronize_initial_rule_reads)

    assert sorted(results) == ["blocked", "consumed"]

    with factory() as db:
        persisted = db.get(ScopedApprovalRule, rule.id)
        assert persisted.execution_count == 1
