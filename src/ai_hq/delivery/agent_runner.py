from __future__ import annotations

from typing import Any, Protocol

from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.models import Delivery, QAResult
from ai_hq.delivery.runtime import DeliveryRuntime


class DeveloperAgent(Protocol):
    """
    Safe Developer execution boundary.

    Implementations produce an immutable candidate plus evidence.
    This interface grants no deployment or production authority.
    """

    def execute(
        self,
        *,
        mission_id: str,
    ) -> dict[str, Any]:
        ...


class QAAgent(Protocol):
    """
    Safe QA review boundary.

    QA receives the exact persisted Developer proposal.
    """

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
    Coordinates Developer -> persisted candidate -> QA.

    This runner does not deploy, invoke host helpers, execute shell
    commands, restart services, or mutate production.
    """

    def __init__(
        self,
        *,
        runtime: DeliveryRuntime,
        developer: DeveloperAgent,
        qa: QAAgent,
        candidate_verifier: CandidateVerifier | None = None,
    ) -> None:
        self.runtime = runtime
        self.developer = developer
        self.qa = qa
        self.candidate_verifier = candidate_verifier

    def run_developer(
        self,
        *,
        mission_id: str,
    ) -> bool:
        candidate = self.developer.execute(
            mission_id=mission_id,
        )

        if not isinstance(candidate, dict):
            raise ValueError(
                "developer candidate must be a mapping"
            )

        change_ref = candidate.get("change_ref")

        if not isinstance(change_ref, str) or not change_ref.strip():
            raise ValueError(
                "developer candidate requires immutable change_ref"
            )

        summary = candidate.get("summary")

        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(
                "developer candidate requires summary"
            )

        changed_files = candidate.get(
            "changed_files",
            [],
        )

        if not isinstance(changed_files, list):
            raise ValueError(
                "developer candidate changed_files must be a list"
            )

        evidence = candidate.get("evidence")

        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(
                "developer candidate requires evidence"
            )

        if self.candidate_verifier is None:
            raise ValueError(
                "candidate verifier is required"
            )

        verified = self.candidate_verifier.verify(
            mission_id=mission_id,
            proposal=candidate,
        )

        self.runtime.handoff_to_developer(
            mission_id=mission_id,
            change_ref=verified.change_ref,
            summary=verified.summary,
            changed_files=list(
                verified.changed_files
            ),
            evidence=dict(
                verified.evidence
            ),
        )

        return True

    def run_qa(
        self,
        delivery: Delivery,
    ) -> bool:
        result = self.qa.review(
            mission_id=delivery.mission_id,
            change_ref=delivery.change_ref,
            summary=delivery.summary,
            changed_files=list(
                delivery.changed_files or []
            ),
            developer_evidence=dict(
                delivery.developer_evidence or {}
            ),
        )

        if not isinstance(result, dict):
            raise ValueError(
                "QA result must be a mapping"
            )

        qa_result = result.get("result")

        try:
            qa_result = QAResult(qa_result)
        except (TypeError, ValueError):
            raise ValueError(
                "QA result must be PASSED or FAILED"
            ) from None

        evidence = result.get("evidence")

        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(
                "QA result requires evidence"
            )

        self.runtime.handoff_to_qa(
            mission_id=delivery.mission_id,
            change_ref=delivery.change_ref,
            result=qa_result,
            evidence=dict(evidence),
        )

        return True
