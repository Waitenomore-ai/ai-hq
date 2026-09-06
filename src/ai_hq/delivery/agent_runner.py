from __future__ import annotations

from typing import Any, Protocol

from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.models import Delivery, QAResult
from ai_hq.delivery.repository_workspace import (
    RepositoryWorkspace,
    RepositoryWorkspaceService,
)
from ai_hq.delivery.runtime import DeliveryRuntime


class DeveloperAgent(Protocol):
    """
    Safe Developer reasoning boundary.

    Implementations may describe intended repository work, but trusted
    candidate identity and evidence are obtained from the workspace service.
    This interface grants no deployment or production authority.
    """

    def execute(
        self,
        *,
        mission_id: str,
    ) -> dict[str, Any]:
        ...


class QAAgent(Protocol):
    """Safe QA review boundary for the exact persisted candidate."""

    def review(
        self,
        *,
        mission_id: str,
        change_ref: str,
        summary: str,
        changed_files: list[str],
        developer_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class DeliveryAgentRunner:
    """
    Coordinates Developer -> workspace evidence -> persisted candidate -> QA.

    This runner does not deploy, invoke host helpers, execute shell commands,
    restart services, operate production Docker, or mutate production.
    """

    def __init__(
        self,
        *,
        runtime: DeliveryRuntime,
        developer: DeveloperAgent,
        qa: QAAgent,
        candidate_verifier: CandidateVerifier | None = None,
        workspace_service: RepositoryWorkspaceService | None = None,
    ) -> None:
        self.runtime = runtime
        self.developer = developer
        self.qa = qa
        self.candidate_verifier = candidate_verifier
        self.workspace_service = workspace_service

    def run_developer(
        self,
        *,
        mission_id: str,
    ) -> bool:
        workspace = self._prepare_workspace(mission_id=mission_id)
        candidate = self.developer.execute(mission_id=mission_id)
        self._verify_and_persist(
            mission_id=mission_id,
            candidate=candidate,
            workspace=workspace,
        )
        return True

    def persist_candidate(
        self,
        *,
        mission_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        """Verify an externally produced candidate through the same boundary."""
        workspace = self._prepare_workspace(mission_id=mission_id)
        self._verify_and_persist(
            mission_id=mission_id,
            candidate=candidate,
            workspace=workspace,
        )
        return True

    def _prepare_workspace(self, *, mission_id: str) -> RepositoryWorkspace:
        if self.workspace_service is None:
            raise ValueError("repository workspace service is required")
        if self.candidate_verifier is None:
            raise ValueError("candidate verifier is required")
        return self.workspace_service.prepare(mission_id=mission_id)

    def _verify_and_persist(
        self,
        *,
        mission_id: str,
        candidate: dict[str, Any],
        workspace: RepositoryWorkspace,
    ) -> None:
        if not isinstance(candidate, dict):
            raise TypeError("developer candidate must be a mapping")

        summary = candidate.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("developer candidate requires summary")

        if self.workspace_service is None or self.candidate_verifier is None:
            raise ValueError("verified candidate dependencies are required")

        snapshot = self.workspace_service.snapshot(workspace=workspace)
        test_evidence = self.workspace_service.run_tests(workspace=workspace)

        verified = self.candidate_verifier.verify(
            mission_id=mission_id,
            proposal=candidate,
            snapshot=snapshot,
            test_evidence=test_evidence,
        )

        self.runtime.handoff_to_developer(
            mission_id=mission_id,
            change_ref=verified.change_ref,
            summary=verified.summary,
            changed_files=list(verified.changed_files),
            evidence=dict(verified.evidence),
        )

    def run_qa(
        self,
        delivery: Delivery,
    ) -> bool:
        result = self.qa.review(
            mission_id=delivery.mission_id,
            change_ref=delivery.change_ref,
            summary=delivery.summary,
            changed_files=list(delivery.changed_files or []),
            developer_evidence=dict(delivery.developer_evidence or {}),
        )

        if not isinstance(result, dict):
            raise TypeError("QA result must be a mapping")

        qa_result = result.get("result")
        try:
            qa_result = QAResult(qa_result)
        except (TypeError, ValueError):
            raise ValueError("QA result must be PASSED or FAILED") from None

        evidence = result.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("QA result requires evidence")

        self.runtime.handoff_to_qa(
            mission_id=delivery.mission_id,
            change_ref=delivery.change_ref,
            result=qa_result,
            evidence=dict(evidence),
        )

        return True
