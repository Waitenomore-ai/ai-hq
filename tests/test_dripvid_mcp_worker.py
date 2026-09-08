from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ai_hq.worker as worker
from ai_hq.db import Base


class FakeMcpClient:
    pass


class McpSettings:
    host_helper_credential = None
    host_helper_socket = "/unused"
    ai_hq_repository_source_path = None
    repository_sandbox_root_path = None
    dripvid_mcp_socket_path = Path("/run/dripvid-mcp/mcp.sock")
    dripvid_mcp_token_file_path = Path("/run/secrets/dripvid-mcp-token")
    dripvid_mcp_timeout_seconds = 5.0


def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_worker_registers_mcp_reads_when_trusted_token_is_configured(monkeypatch):
    monkeypatch.setattr(worker, "load_dripvid_mcp_token", lambda path: "secret", raising=False)
    monkeypatch.setattr(worker, "DripVidMcpClient", lambda **kwargs: FakeMcpClient(), raising=False)

    runner = worker.build_autonomous_mission_runner(
        McpSettings(),
        session_factory=session_factory(),
    )
    registry = runner.executor.gateway.registry

    for capability in (
        "dripvid.health.read",
        "dripvid.release.read",
        "dripvid.config.read",
        "dripvid.service.status.read",
    ):
        assert registry.resolve(capability) is not None

    assert registry.resolve("dripvid.logs.read") is None
    assert registry.resolve("dripvid.service.restart") is None
