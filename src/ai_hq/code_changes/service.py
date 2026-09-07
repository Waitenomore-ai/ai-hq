from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.models import QAResult
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.models import (
    MissionPriority,
    MissionRisk,
)
from ai_hq.missions.service import MissionService


TRUSTED_REPOSITORIES = frozenset(
    {
        "ai-hq",
        "dripvid",
    }
)


HIGH_RISK_AI_HQ_PREFIXES = (
    "src/ai_hq/auth/",
    "src/ai_hq/approvals/",
    "src/ai_hq/tool_gateway/",
    "src/ai_hq/host_helper/",
    "deploy/",
)

HIGH_RISK_AI_HQ_EXACT_FILES = frozenset(
    {
        "src/ai_hq/delivery/repository_sandbox.py",
        "src/ai_hq/delivery/repository_profiles.py",
        "src/ai_hq/delivery/candidate_verifier.py",
    }
)


class DeliveryRunnerFactory(Protocol):
    def __call__(
        self,
        repository: str,
    ) -> DeliveryAgentRunner:
        ...


@dataclass(frozen=True)
class CodeChangeResult:
    mission_id: str
    repository: str
    summary: str
    change_ref: str
    changed_files: tuple[str, ...]
    developer_evidence: dict[str, Any]
    qa_result: QAResult | None
    qa_evidence: dict[str, Any]
    approval_reference: str | None
    ready_for_approval: bool
    high_risk: bool
    published: bool = False
    deployed: bool = False


class CodeChangeService:
    """
    Trusted Phase A orchestration boundary.

    Natural-language intent resolution happens before this service.

    This service selects only a configured logical repository and
    coordinates the existing Developer -> repository sandbox ->
    machine verification -> QA -> human approval pipeline.

    It does not publish, push, merge, deploy, restart services,
    invoke Host Helper, execute arbitrary shell commands, or mutate
    production.
    """

    def __init__(
        self,
        *,
        mission_service: MissionService,
        delivery_service: DeliveryService,
        runner_factory: DeliveryRunnerFactory,
    ) -> None:
        self.mission_service = mission_service
        self.delivery_service = delivery_service
        self.runner_factory = runner_factory

    def prepare_candidate(
        self,
        *,
        repository: str,
        instruction: str,
    ) -> CodeChangeResult:
        repository = self._trusted_repository(repository)
        instruction = self._instruction(instruction)

        mission = self.mission_service.create_mission(
            title=f"Code change: {repository}",
            description=instruction,
            owner_agent="developer",
            source="hq_chat_code_change",
            priority=MissionPriority.NORMAL,
            risk=MissionRisk.AMBER,
            objectives=[
                repository,
                instruction,
            ],
            dependencies=[],
        )

        runner = self.runner_factory(repository)

        runner.run_developer(
            mission_id=mission.id,
        )

        developer_delivery = self.delivery_service.get_delivery(
            mission.id
        )

        runner.run_qa(
            developer_delivery
        )

        final_delivery = self.delivery_service.get_delivery(
            mission.id
        )

        changed_files = tuple(
            final_delivery.changed_files or []
        )

        qa_evidence = dict(
            final_delivery.qa_evidence or {}
        )

        ready_for_approval = (
            final_delivery.qa_result is QAResult.PASSED
            and bool(final_delivery.approval_reference)
        )

        return CodeChangeResult(
            mission_id=mission.id,
            repository=repository,
            summary=final_delivery.summary,
            change_ref=final_delivery.change_ref,
            changed_files=changed_files,
            developer_evidence=dict(
                final_delivery.developer_evidence or {}
            ),
            qa_result=final_delivery.qa_result,
            qa_evidence=qa_evidence,
            approval_reference=(
                final_delivery.approval_reference
            ),
            ready_for_approval=ready_for_approval,
            high_risk=self._high_risk(
                repository=repository,
                changed_files=changed_files,
            ),
        )

    @staticmethod
    def _trusted_repository(repository: str) -> str:
        if not isinstance(repository, str):
            raise ValueError(
                "code change requires a trusted repository"
            )

        repository = repository.strip()

        if repository not in TRUSTED_REPOSITORIES:
            raise ValueError(
                "code change requires a trusted repository: "
                "ai-hq or dripvid"
            )

        return repository

    @staticmethod
    def _instruction(instruction: str) -> str:
        if not isinstance(instruction, str):
            raise ValueError(
                "code change instruction is required"
            )

        instruction = instruction.strip()

        if not instruction:
            raise ValueError(
                "code change instruction is required"
            )

        return instruction

    @staticmethod
    def _high_risk(
        *,
        repository: str,
        changed_files: tuple[str, ...],
    ) -> bool:
        if repository != "ai-hq":
            return False

        for path in changed_files:
            if path in HIGH_RISK_AI_HQ_EXACT_FILES:
                return True

            if path.startswith(
                HIGH_RISK_AI_HQ_PREFIXES
            ):
                return True

        return False
