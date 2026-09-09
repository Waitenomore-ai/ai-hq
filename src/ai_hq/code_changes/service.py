from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_hq.code_changes.candidate_store import CandidateStore
from ai_hq.code_changes.deployer import CandidateDeployer, DeployedRelease
from ai_hq.code_changes.publisher import CandidatePublisher, PublishedCandidate
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.models import (
    MissionPriority,
    MissionRisk,
    MissionStatus,
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
class QueuedCodeChange:
    mission_id: str
    repository: str


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
    deployment_release_id: str | None = None
    deployment_prior_release_id: str | None = None


class CodeChangeService:
    """
    Trusted code-change orchestration boundary.

    Natural-language intent resolution happens before this service.
    Candidate preparation remains isolated from publication. Publication
    is available only through the injected narrow publisher and only after
    the exact persisted human approval is confirmed. Deployment is available
    only through the injected narrow deployer after the same approval and an
    already-published candidate identity.

    It does not merge, restart services, invoke Host Helper, execute
    arbitrary shell commands, or mutate production on its own.
    """

    def __init__(
        self,
        *,
        mission_service: MissionService,
        delivery_service: DeliveryService,
        runner_factory: DeliveryRunnerFactory,
        candidate_store: CandidateStore | None = None,
        publisher: CandidatePublisher | None = None,
        deployer: CandidateDeployer | None = None,
    ) -> None:
        self.mission_service = mission_service
        self.delivery_service = delivery_service
        self.runner_factory = runner_factory
        self.candidate_store = candidate_store
        self.publisher = publisher
        self.deployer = deployer

    def queue_candidate(
        self,
        *,
        repository: str,
        instruction: str,
    ) -> QueuedCodeChange:
        repository = self._trusted_repository(
            repository
        )
        instruction = self._instruction(
            instruction
        )

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

        return QueuedCodeChange(
            mission_id=mission.id,
            repository=repository,
        )

    def process_queued_candidate(
        self,
        *,
        mission_id: str,
        lease_owner: str | None = None,
        lease_seconds: int = 900,
    ) -> CodeChangeResult:
        mission = self.mission_service.get_mission(
            mission_id
        )

        if (
            mission.owner_agent != "developer"
            or mission.source
            != "hq_chat_code_change"
        ):
            raise ValueError(
                "mission is not a queued "
                "HQ code change"
            )

        objectives = mission.objectives or []

        if not objectives:
            raise ValueError(
                "queued code change has "
                "no repository"
            )

        repository = self._trusted_repository(
            objectives[0]
        )

        if mission.status in {
            MissionStatus.WAITING_APPROVAL,
            MissionStatus.COMPLETED,
        }:
            return self._result_for_mission(
                mission_id=mission.id,
                repository=repository,
            )

        if mission.status is MissionStatus.QUEUED:
            if lease_owner is not None:
                raise ValueError(
                    "leased code change must "
                    "already be running"
                )

            self.mission_service.transition(
                mission.id,
                MissionStatus.RUNNING,
            )

        elif (
            mission.status
            is MissionStatus.RUNNING
        ):
            if lease_owner is not None:
                if (
                    mission.lease_owner
                    != lease_owner
                ):
                    raise ValueError(
                        "code-change lease "
                        "owner mismatch"
                    )

                renewed = (
                    self.mission_service
                    .renew_code_change_lease(
                        mission.id,
                        worker_id=lease_owner,
                        lease_seconds=(
                            lease_seconds
                        ),
                    )
                )

                if not renewed:
                    raise RuntimeError(
                        "code-change lease "
                        "was lost"
                    )

        else:
            raise ValueError(
                "queued code change is "
                "not runnable"
            )

        try:
            result = self._run_existing_mission(
                mission_id=mission.id,
                repository=repository,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                resume_existing=True,
            )

            target = (
                MissionStatus.WAITING_APPROVAL
                if result.ready_for_approval
                else MissionStatus.COMPLETED
            )

            payload = {
                "repository": repository,
                "change_ref": result.change_ref,
                "ready_for_approval": (
                    result.ready_for_approval
                ),
            }

            current = (
                self.mission_service
                .get_mission(mission.id)
            )

            if current.status is target:
                self.mission_service.record_result(
                    mission.id,
                    result=payload,
                )

            elif (
                current.status
                is MissionStatus.RUNNING
            ):
                self.mission_service.transition(
                    mission.id,
                    target,
                    result=payload,
                )

            else:
                raise RuntimeError(
                    "code-change mission changed "
                    "state during preparation"
                )

            if lease_owner is not None:
                (
                    self.mission_service
                    .release_code_change_lease(
                        mission.id,
                        worker_id=lease_owner,
                    )
                )

            return result

        except Exception:
            current = (
                self.mission_service
                .get_mission(mission.id)
            )

            if (
                current.status
                is MissionStatus.RUNNING
            ):
                self.mission_service.transition(
                    mission.id,
                    MissionStatus.FAILED,
                    error_state={
                        "code": (
                            "code_change_"
                            "preparation_failed"
                        ),
                        "message": (
                            "Code-change candidate "
                            "preparation failed."
                        ),
                    },
                )

            if lease_owner is not None:
                (
                    self.mission_service
                    .release_code_change_lease(
                        mission.id,
                        worker_id=lease_owner,
                    )
                )

            raise

    def candidate_result(
        self,
        *,
        mission_id: str,
    ) -> CodeChangeResult:
        mission = self.mission_service.get_mission(
            mission_id
        )

        if (
            mission.owner_agent != "developer"
            or mission.source != "hq_chat_code_change"
        ):
            raise ValueError(
                "mission is not an HQ code change"
            )

        objectives = mission.objectives or []

        if not objectives:
            raise ValueError(
                "code-change mission has no repository"
            )

        repository = self._trusted_repository(
            objectives[0]
        )

        return self._result_for_mission(
            mission_id=mission.id,
            repository=repository,
        )

    def publish_approved_candidate(
        self,
        *,
        mission_id: str,
        approval_reference: str,
        change_ref: str,
    ) -> CodeChangeResult:
        mission = self.mission_service.get_mission(mission_id)
        if (
            mission.owner_agent != "developer"
            or mission.source != "hq_chat_code_change"
        ):
            raise ValueError("mission is not an HQ code change")

        objectives = mission.objectives or []
        if not objectives:
            raise ValueError("code-change mission has no repository")
        repository = self._trusted_repository(objectives[0])

        delivery = self.delivery_service.get_delivery(mission_id)
        if delivery.qa_result is not QAResult.PASSED:
            raise ValueError("QA must pass before candidate publication")
        if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
            raise ValueError("candidate is not waiting for approved publication")
        if delivery.approval_reference != approval_reference:
            raise ValueError("approval reference does not match delivery")
        if delivery.change_ref != change_ref:
            raise ValueError("change_ref does not match approved proposal")

        decided = self.delivery_service.apply_human_decision(
            mission_id=mission_id,
            approval_reference=approval_reference,
            change_ref=change_ref,
        )
        if (
            decided.stage is not DeliveryStage.WAITING_APPROVAL
            or decided.qa_result is not QAResult.PASSED
            or decided.approval_reference != approval_reference
        ):
            raise ValueError("approved human approval is required for publication")

        publication = (
            getattr(decided, "published_branch", None),
            getattr(decided, "published_commit", None),
            getattr(decided, "published_tree", None),
        )
        if all(value is not None for value in publication):
            return self._result_for_mission(
                mission_id=mission_id,
                repository=repository,
            )
        if any(value is not None for value in publication):
            raise ValueError("persisted publication identity is incomplete")

        if self.candidate_store is None or self.publisher is None:
            raise RuntimeError("code-change publication is not configured")

        candidate = self.candidate_store.load_verified(
            mission_id=mission_id,
            change_ref=change_ref,
            changed_files=tuple(decided.changed_files or []),
            evidence=dict(decided.developer_evidence or {}),
        )
        if candidate.repository != repository:
            raise ValueError("candidate repository does not match mission repository")
        if candidate.change_ref != change_ref:
            raise ValueError("candidate change_ref does not match approved proposal")

        published = self.publisher.publish(candidate)
        if not isinstance(published, PublishedCandidate):
            raise TypeError("publisher must return PublishedCandidate")
        if published.repository != repository:
            raise ValueError("published repository does not match candidate")
        if published.change_ref != change_ref:
            raise ValueError("published change_ref does not match candidate")
        if published.base_commit != candidate.base_commit:
            raise ValueError("published base commit does not match candidate")

        self.delivery_service.record_publication(
            mission_id=mission_id,
            change_ref=change_ref,
            branch_name=published.branch_name,
            commit_sha=published.commit_sha,
            tree_sha=published.tree_sha,
        )

        return self._result_for_mission(
            mission_id=mission_id,
            repository=repository,
        )

    def deploy_approved_candidate(
        self,
        *,
        mission_id: str,
        approval_reference: str,
        change_ref: str,
    ) -> CodeChangeResult:
        mission = self.mission_service.get_mission(mission_id)
        if (
            mission.owner_agent != "developer"
            or mission.source != "hq_chat_code_change"
        ):
            raise ValueError("mission is not an HQ code change")

        objectives = mission.objectives or []
        if not objectives:
            raise ValueError("code-change mission has no repository")
        repository = self._trusted_repository(objectives[0])

        delivery = self.delivery_service.get_delivery(mission_id)
        if delivery.qa_result is not QAResult.PASSED:
            raise ValueError("QA must pass before candidate deployment")
        if delivery.stage is not DeliveryStage.WAITING_APPROVAL:
            raise ValueError("candidate is not waiting for approved deployment")
        if delivery.approval_reference != approval_reference:
            raise ValueError("approval reference does not match delivery")
        if delivery.change_ref != change_ref:
            raise ValueError("change_ref does not match approved proposal")

        decided = self.delivery_service.apply_human_decision(
            mission_id=mission_id,
            approval_reference=approval_reference,
            change_ref=change_ref,
        )
        if (
            decided.stage is not DeliveryStage.WAITING_APPROVAL
            or decided.qa_result is not QAResult.PASSED
            or decided.approval_reference != approval_reference
        ):
            raise ValueError("approved human approval is required for deployment")

        publication = (
            getattr(decided, "published_branch", None),
            getattr(decided, "published_commit", None),
            getattr(decided, "published_tree", None),
        )
        if not all(value is not None for value in publication):
            raise ValueError("candidate must be published before deployment")

        deployment = (
            getattr(decided, "deployment_release_id", None),
            getattr(decided, "deployment_prior_release_id", None),
        )
        if deployment[0] is not None or deployment[1] is not None:
            return self._result_for_mission(
                mission_id=mission_id,
                repository=repository,
            )

        if self.deployer is None or self.candidate_store is None:
            raise RuntimeError("code-change deployment is not configured")

        candidate = self.candidate_store.load_verified(
            mission_id=mission_id,
            change_ref=change_ref,
            changed_files=tuple(decided.changed_files or []),
            evidence=dict(decided.developer_evidence or {}),
        )
        if candidate.repository != repository:
            raise ValueError("candidate repository does not match mission repository")
        if candidate.change_ref != change_ref:
            raise ValueError("candidate change_ref does not match approved proposal")

        published = PublishedCandidate(
            repository=repository,
            change_ref=change_ref,
            branch_name=publication[0],
            commit_sha=publication[1],
            tree_sha=publication[2],
            base_commit=candidate.base_commit,
        )

        deployed = self.deployer.deploy(published)
        if not isinstance(deployed, DeployedRelease):
            raise TypeError("deployer must return DeployedRelease")
        if deployed.repository != repository:
            raise ValueError("deployed repository does not match candidate")
        if deployed.change_ref != change_ref:
            raise ValueError("deployed change_ref does not match candidate")

        self.delivery_service.record_deployment(
            mission_id=mission_id,
            change_ref=change_ref,
            release_id=deployed.release_id,
            prior_release_id=deployed.prior_release_id,
        )

        return self._result_for_mission(
            mission_id=mission_id,
            repository=repository,
        )

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

        return self._run_existing_mission(
            mission_id=mission.id,
            repository=repository,
        )

    def _run_existing_mission(
        self,
        *,
        mission_id: str,
        repository: str,
        lease_owner: str | None = None,
        lease_seconds: int = 900,
        resume_existing: bool = False,
    ) -> CodeChangeResult:
        runner = self.runner_factory(repository)

        developer_delivery = None

        if resume_existing:
            try:
                developer_delivery = (
                    self.delivery_service
                    .get_delivery(mission_id)
                )
            except KeyError:
                developer_delivery = None

        if developer_delivery is None:
            self._renew_worker_lease(
                mission_id=mission_id,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )

            runner.run_developer(
                mission_id=mission_id,
            )

            developer_delivery = (
                self.delivery_service
                .get_delivery(mission_id)
            )

        if (
            developer_delivery.stage
            is DeliveryStage.QA
            and developer_delivery.qa_result
            is None
        ):
            self._renew_worker_lease(
                mission_id=mission_id,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )

            runner.run_qa(
                developer_delivery
            )

        return self._result_for_mission(
            mission_id=mission_id,
            repository=repository,
        )

    def _renew_worker_lease(
        self,
        *,
        mission_id: str,
        lease_owner: str | None,
        lease_seconds: int,
    ) -> None:
        if lease_owner is None:
            return

        renewed = (
            self.mission_service
            .renew_code_change_lease(
                mission_id,
                worker_id=lease_owner,
                lease_seconds=lease_seconds,
            )
        )

        if not renewed:
            raise RuntimeError(
                "code-change lease was lost"
            )

    def _result_for_mission(
        self,
        *,
        mission_id: str,
        repository: str,
    ) -> CodeChangeResult:
        final_delivery = (
            self.delivery_service.get_delivery(
                mission_id
            )
        )

        changed_files = tuple(
            final_delivery.changed_files or []
        )

        ready = (
            final_delivery.qa_result is QAResult.PASSED
            and bool(
                final_delivery.approval_reference
            )
        )
        publication = (
            getattr(final_delivery, "published_branch", None),
            getattr(final_delivery, "published_commit", None),
            getattr(final_delivery, "published_tree", None),
        )
        published = all(value is not None for value in publication)
        deployment = (
            getattr(final_delivery, "deployment_release_id", None),
            getattr(final_delivery, "deployment_prior_release_id", None),
        )
        deployed = deployment[0] is not None

        return CodeChangeResult(
            mission_id=mission_id,
            repository=repository,
            summary=final_delivery.summary,
            change_ref=final_delivery.change_ref,
            changed_files=changed_files,
            developer_evidence=dict(
                final_delivery.developer_evidence
                or {}
            ),
            qa_result=final_delivery.qa_result,
            qa_evidence=dict(
                final_delivery.qa_evidence or {}
            ),
            approval_reference=(
                final_delivery.approval_reference
            ),
            ready_for_approval=ready,
            high_risk=self._high_risk(
                repository=repository,
                changed_files=changed_files,
            ),
            published=published,
            deployed=deployed,
            deployment_release_id=deployment[0],
            deployment_prior_release_id=deployment[1],
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
