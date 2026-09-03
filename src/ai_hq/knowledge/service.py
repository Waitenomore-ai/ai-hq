from datetime import UTC, datetime

from sqlalchemy import select

from ai_hq.knowledge.models import (
    KnowledgeMemory,
    MemoryCategory,
    MemorySensitivity,
    MemoryVisibility,
    VerificationState,
)
from ai_hq.missions.service import SessionFactory


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _provenance_kind(provenance: dict) -> str:
    return str(provenance.get("kind", "")).strip().lower()


def _is_inference(provenance: dict) -> bool:
    return _provenance_kind(provenance) in {"agent_inference", "inference", "model_inference"}


def _default_verification(provenance: dict) -> VerificationState:
    kind = _provenance_kind(provenance)
    if kind in {"agent_inference", "inference", "model_inference"}:
        return VerificationState.INFERRED
    if kind in {"user_confirmed", "explicit_user_confirmation"}:
        return VerificationState.CONFIRMED
    return VerificationState.UNVERIFIED


class KnowledgeService:
    def __init__(self, session_factory: SessionFactory):
        self.session_factory = session_factory

    def _validate_values(
        self,
        *,
        content: str,
        provenance: dict,
        confidence: float,
        verification_state: VerificationState,
        sensitivity: MemorySensitivity,
        temporary: bool,
        expires_at: datetime | None,
    ) -> None:
        if not content.strip():
            raise ValueError("memory content cannot be empty")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if temporary and expires_at is None:
            raise ValueError("temporary memory requires expiry")
        if sensitivity is MemorySensitivity.SECRET:
            raise ValueError("raw secrets belong in the Secrets Vault, not Knowledge Core")
        if _is_inference(provenance) and verification_state is VerificationState.CONFIRMED:
            raise ValueError("inference cannot be created as confirmed")

    def create_memory(
        self,
        *,
        category: MemoryCategory | str,
        content: str,
        owner_scope: str,
        provenance: dict,
        confidence: float,
        verification_state: VerificationState | str | None = None,
        sensitivity: MemorySensitivity | str = MemorySensitivity.NORMAL,
        visibility: MemoryVisibility | str = MemoryVisibility.PRIVATE,
        allowed_agents: list[str] | None = None,
        pinned: bool = False,
        locked: bool = False,
        temporary: bool = False,
        expires_at: datetime | None = None,
        contradicts_memory_id: str | None = None,
    ) -> KnowledgeMemory:
        category_value = MemoryCategory(category)
        sensitivity_value = MemorySensitivity(sensitivity)
        visibility_value = MemoryVisibility(visibility)
        verification_value = (
            VerificationState(verification_state)
            if verification_state is not None
            else _default_verification(provenance)
        )
        self._validate_values(
            content=content,
            provenance=provenance,
            confidence=confidence,
            verification_state=verification_value,
            sensitivity=sensitivity_value,
            temporary=temporary,
            expires_at=expires_at,
        )
        memory = KnowledgeMemory(
            category=category_value,
            content=content.strip(),
            owner_scope=owner_scope,
            provenance=provenance,
            confidence=confidence,
            verification_state=verification_value,
            sensitivity=sensitivity_value,
            visibility=visibility_value,
            allowed_agents=sorted(set(allowed_agents or [])),
            pinned=pinned,
            locked=locked,
            temporary=temporary,
            expires_at=expires_at,
            contradicts_memory_id=contradicts_memory_id,
            verified_at=datetime.now(UTC)
            if verification_value is VerificationState.CONFIRMED
            else None,
        )
        with self.session_factory() as db:
            if contradicts_memory_id is not None and db.get(KnowledgeMemory, contradicts_memory_id) is None:
                raise KeyError(f"memory not found: {contradicts_memory_id}")
            db.add(memory)
            db.commit()
            db.refresh(memory)
            return memory

    def get_memory(self, memory_id: str, *, include_deleted: bool = False) -> KnowledgeMemory:
        with self.session_factory() as db:
            memory = db.get(KnowledgeMemory, memory_id)
            if memory is None or (memory.deleted_at is not None and not include_deleted):
                raise KeyError(f"memory not found: {memory_id}")
            return memory

    def _is_active(self, memory: KnowledgeMemory, now: datetime) -> bool:
        if memory.deleted_at is not None:
            return False
        if memory.expires_at is not None and _utc(memory.expires_at) <= now:
            return False
        return True

    def _visible_to_agent(self, memory: KnowledgeMemory, agent_key: str | None) -> bool:
        if agent_key is None:
            return True
        if memory.visibility is MemoryVisibility.SHARED:
            return True
        if memory.visibility is MemoryVisibility.RESTRICTED:
            return agent_key in memory.allowed_agents
        return memory.owner_scope == f"agent:{agent_key}"

    def search(
        self,
        query: str,
        *,
        agent_key: str | None = None,
        category: MemoryCategory | str | None = None,
    ) -> list[KnowledgeMemory]:
        now = datetime.now(UTC)
        requested_category = MemoryCategory(category) if category is not None else None
        normalized_query = query.strip().casefold()
        with self.session_factory() as db:
            memories = list(
                db.scalars(select(KnowledgeMemory).order_by(KnowledgeMemory.created_at, KnowledgeMemory.id))
            )
            return [
                memory
                for memory in memories
                if self._is_active(memory, now)
                and self._visible_to_agent(memory, agent_key)
                and (requested_category is None or memory.category is requested_category)
                and (not normalized_query or normalized_query in memory.content.casefold())
            ]

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        provenance: dict | None = None,
        confidence: float | None = None,
        verification_state: VerificationState | str | None = None,
        sensitivity: MemorySensitivity | str | None = None,
        visibility: MemoryVisibility | str | None = None,
        allowed_agents: list[str] | None = None,
        pinned: bool | None = None,
        temporary: bool | None = None,
        expires_at: datetime | None = None,
    ) -> KnowledgeMemory:
        with self.session_factory() as db:
            memory = db.get(KnowledgeMemory, memory_id)
            if memory is None or memory.deleted_at is not None:
                raise KeyError(f"memory not found: {memory_id}")
            if memory.locked:
                raise ValueError("locked memory cannot be changed")

            next_content = content.strip() if content is not None else memory.content
            next_provenance = provenance if provenance is not None else memory.provenance
            next_confidence = confidence if confidence is not None else memory.confidence
            next_sensitivity = (
                MemorySensitivity(sensitivity) if sensitivity is not None else memory.sensitivity
            )
            next_temporary = temporary if temporary is not None else memory.temporary
            next_expiry = expires_at if expires_at is not None else memory.expires_at

            content_changed = content is not None and next_content != memory.content
            if verification_state is not None:
                next_verification = VerificationState(verification_state)
            elif content_changed and memory.verification_state is VerificationState.CONFIRMED:
                next_verification = VerificationState.NEEDS_REVIEW
            else:
                next_verification = memory.verification_state

            self._validate_values(
                content=next_content,
                provenance=next_provenance,
                confidence=next_confidence,
                verification_state=next_verification,
                sensitivity=next_sensitivity,
                temporary=next_temporary,
                expires_at=next_expiry,
            )

            memory.content = next_content
            memory.provenance = next_provenance
            memory.confidence = next_confidence
            memory.verification_state = next_verification
            memory.sensitivity = next_sensitivity
            if visibility is not None:
                memory.visibility = MemoryVisibility(visibility)
            if allowed_agents is not None:
                memory.allowed_agents = sorted(set(allowed_agents))
            if pinned is not None:
                memory.pinned = pinned
            memory.temporary = next_temporary
            memory.expires_at = next_expiry
            memory.revision += 1
            memory.verified_at = (
                datetime.now(UTC) if next_verification is VerificationState.CONFIRMED else None
            )
            db.commit()
            db.refresh(memory)
            return memory

    def set_lock(self, memory_id: str, locked: bool) -> KnowledgeMemory:
        with self.session_factory() as db:
            memory = db.get(KnowledgeMemory, memory_id)
            if memory is None or memory.deleted_at is not None:
                raise KeyError(f"memory not found: {memory_id}")
            memory.locked = locked
            db.commit()
            db.refresh(memory)
            return memory

    def set_verification(
        self, memory_id: str, state: VerificationState | str
    ) -> KnowledgeMemory:
        verification = VerificationState(state)
        with self.session_factory() as db:
            memory = db.get(KnowledgeMemory, memory_id)
            if memory is None or memory.deleted_at is not None:
                raise KeyError(f"memory not found: {memory_id}")
            if memory.locked:
                raise ValueError("locked memory cannot be changed")
            if _is_inference(memory.provenance) and verification is VerificationState.CONFIRMED:
                raise ValueError("inference requires explicit provenance change before confirmation")
            memory.verification_state = verification
            memory.verified_at = (
                datetime.now(UTC) if verification is VerificationState.CONFIRMED else None
            )
            memory.revision += 1
            db.commit()
            db.refresh(memory)
            return memory

    def delete_memory(self, memory_id: str) -> KnowledgeMemory:
        with self.session_factory() as db:
            memory = db.get(KnowledgeMemory, memory_id)
            if memory is None or memory.deleted_at is not None:
                raise KeyError(f"memory not found: {memory_id}")
            if memory.locked:
                raise ValueError("locked memory cannot be deleted")
            memory.deleted_at = datetime.now(UTC)
            db.commit()
            db.refresh(memory)
            return memory

    def record_contradiction(
        self,
        memory_id: str,
        *,
        content: str,
        provenance: dict,
        confidence: float,
    ) -> KnowledgeMemory:
        original = self.get_memory(memory_id)
        return self.create_memory(
            category=original.category,
            content=content,
            owner_scope=original.owner_scope,
            provenance=provenance,
            confidence=confidence,
            verification_state=VerificationState.NEEDS_REVIEW,
            sensitivity=original.sensitivity,
            visibility=original.visibility,
            allowed_agents=original.allowed_agents,
            contradicts_memory_id=original.id,
        )

    def list_contradictions(self, memory_id: str) -> list[KnowledgeMemory]:
        self.get_memory(memory_id, include_deleted=True)
        with self.session_factory() as db:
            return list(
                db.scalars(
                    select(KnowledgeMemory)
                    .where(
                        KnowledgeMemory.contradicts_memory_id == memory_id,
                        KnowledgeMemory.deleted_at.is_(None),
                    )
                    .order_by(KnowledgeMemory.created_at, KnowledgeMemory.id)
                )
            )
