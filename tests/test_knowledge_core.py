from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.knowledge.models import (
    MemoryCategory,
    MemorySensitivity,
    MemoryVisibility,
    VerificationState,
)
from ai_hq.knowledge.service import KnowledgeService


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return KnowledgeService(sessionmaker(bind=engine, expire_on_commit=False))


def provenance(kind="user_statement", ref="conversation:test"):
    return {"kind": kind, "reference": ref}


def test_inference_cannot_silently_become_confirmed_fact():
    service = build_service()
    with pytest.raises(ValueError, match="inference cannot be created as confirmed"):
        service.create_memory(
            category=MemoryCategory.CONFIRMED_FACT,
            content="The server always has 10 TB free.",
            owner_scope="user:primary",
            provenance=provenance("agent_inference"),
            confidence=0.7,
            verification_state=VerificationState.CONFIRMED,
        )

    memory = service.create_memory(
        category=MemoryCategory.CONFIRMED_FACT,
        content="The server may have 10 TB free.",
        owner_scope="user:primary",
        provenance=provenance("agent_inference"),
        confidence=0.7,
    )
    assert memory.verification_state is VerificationState.INFERRED


def test_confirmed_memory_tracks_provenance_and_verification_time():
    service = build_service()
    memory = service.create_memory(
        category=MemoryCategory.CONFIRMED_FACT,
        content="AI HQ is deployed separately from DripVid.",
        owner_scope="shared",
        provenance=provenance("user_confirmed", "design:phase-1"),
        confidence=1.0,
        verification_state=VerificationState.CONFIRMED,
    )
    assert memory.provenance["reference"] == "design:phase-1"
    assert memory.verified_at is not None


def test_working_memory_expiry_and_soft_delete_remove_from_active_retrieval():
    service = build_service()
    active = service.create_memory(
        category=MemoryCategory.WORKING_MEMORY,
        content="Investigate current worker latency.",
        owner_scope="agent:sysadmin",
        provenance=provenance(),
        confidence=0.8,
        temporary=True,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    service.create_memory(
        category=MemoryCategory.WORKING_MEMORY,
        content="Expired temporary investigation.",
        owner_scope="agent:sysadmin",
        provenance=provenance(),
        confidence=0.8,
        temporary=True,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert [item.id for item in service.search("worker")] == [active.id]
    service.delete_memory(active.id)
    assert service.search("latency") == []
    assert service.get_memory(active.id, include_deleted=True).deleted_at is not None


def test_locked_memory_cannot_be_changed_or_deleted_until_unlocked():
    service = build_service()
    memory = service.create_memory(
        category=MemoryCategory.PROCEDURE,
        content="Never expose production secrets to agents.",
        owner_scope="shared",
        provenance=provenance("user_confirmed"),
        confidence=1.0,
        verification_state=VerificationState.CONFIRMED,
        pinned=True,
        locked=True,
    )
    with pytest.raises(ValueError, match="locked"):
        service.update_memory(memory.id, content="Changed")
    with pytest.raises(ValueError, match="locked"):
        service.delete_memory(memory.id)
    service.set_lock(memory.id, False)
    updated = service.update_memory(memory.id, content="Never expose raw production secrets to agents.")
    assert "raw production" in updated.content


def test_contradictions_are_linked_and_original_is_not_overwritten():
    service = build_service()
    original = service.create_memory(
        category=MemoryCategory.CONFIRMED_FACT,
        content="Service A listens on port 8000.",
        owner_scope="shared",
        provenance=provenance("document", "runbook:v1"),
        confidence=0.9,
        verification_state=VerificationState.CONFIRMED,
    )
    contradiction = service.record_contradiction(
        original.id,
        content="Service A listens on port 8090.",
        provenance=provenance("system_observation", "probe:2026-09-03"),
        confidence=1.0,
    )
    assert service.get_memory(original.id).content.endswith("8000.")
    assert contradiction.contradicts_memory_id == original.id
    assert contradiction.verification_state is VerificationState.NEEDS_REVIEW
    assert service.list_contradictions(original.id)[0].id == contradiction.id


def test_agent_scoped_retrieval_respects_visibility_and_allowed_agents():
    service = build_service()
    shared = service.create_memory(
        category=MemoryCategory.PROCEDURE,
        content="Shared health check procedure.",
        owner_scope="shared",
        provenance=provenance("user_confirmed"),
        confidence=1.0,
        visibility=MemoryVisibility.SHARED,
    )
    restricted = service.create_memory(
        category=MemoryCategory.AGENT_MEMORY,
        content="SysAdmin-only maintenance note.",
        owner_scope="shared",
        provenance=provenance(),
        confidence=0.8,
        visibility=MemoryVisibility.RESTRICTED,
        allowed_agents=["sysadmin"],
        sensitivity=MemorySensitivity.SENSITIVE,
    )
    private = service.create_memory(
        category=MemoryCategory.AGENT_MEMORY,
        content="Communications private context.",
        owner_scope="agent:communications",
        provenance=provenance(),
        confidence=0.8,
        visibility=MemoryVisibility.PRIVATE,
    )

    sysadmin_ids = {item.id for item in service.search("", agent_key="sysadmin")}
    assert shared.id in sysadmin_ids
    assert restricted.id in sysadmin_ids
    assert private.id not in sysadmin_ids

    communications_ids = {item.id for item in service.search("", agent_key="communications")}
    assert shared.id in communications_ids
    assert restricted.id not in communications_ids
    assert private.id in communications_ids


def test_temporary_memory_requires_expiry_and_confidence_is_bounded():
    service = build_service()
    with pytest.raises(ValueError, match="temporary memory requires expiry"):
        service.create_memory(
            category=MemoryCategory.WORKING_MEMORY,
            content="Temporary note",
            owner_scope="shared",
            provenance=provenance(),
            confidence=0.5,
            temporary=True,
        )
    with pytest.raises(ValueError, match="confidence"):
        service.create_memory(
            category=MemoryCategory.PREFERENCE,
            content="Preference",
            owner_scope="user:primary",
            provenance=provenance(),
            confidence=1.5,
        )
