from __future__ import annotations

from pathlib import Path

from ai_hq.code_changes.context import (
    RepositoryContextProvider,
)
from ai_hq.code_changes.service import CodeChangeService
from ai_hq.repository_source_policy import (
    validate_production_repository_paths,
)
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.model_agents import (
    ModelBackedDeveloperAgent,
    ModelBackedQAAgent,
)
from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
    build_dripvid_repository_profile,
)
from ai_hq.delivery.repository_sandbox import (
    IsolatedRepositorySandbox,
)
from ai_hq.delivery.runtime import DeliveryRuntime
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.service import MissionService


def build_code_change_service(
    *,
    settings,
    session_factory,
    model_client,
) -> CodeChangeService | None:
    """
    Build Phase A code-change preparation only when all trusted
    repository/sandbox inputs are explicitly configured.

    Missing configuration fails closed by returning None.
    """

    sandbox_root = (
        settings.repository_sandbox_root_path
    )
    ai_hq_source = (
        settings.ai_hq_repository_source_path
    )
    dripvid_source = (
        settings.dripvid_repository_source_path
    )

    mirror_root = getattr(
        settings,
        "repository_mirror_root_path",
        None,
    )

    validate_production_repository_paths(
        is_production=bool(
            getattr(
                settings,
                "is_production",
                False,
            )
        ),
        mirror_root=mirror_root,
        sandbox_root=sandbox_root,
        ai_hq_source=ai_hq_source,
        dripvid_source=dripvid_source,
    )

    if (
        sandbox_root is None
        or ai_hq_source is None
        or dripvid_source is None
        or model_client is None
    ):
        return None

    profiles = RepositoryProfileRegistry(
        (
            build_ai_hq_repository_profile(
                source_path=ai_hq_source,
                base_ref="main",
            ),
            build_dripvid_repository_profile(
                source_path=dripvid_source,
                base_ref="main",
            ),
        )
    )

    mission_service = MissionService(
        session_factory
    )
    delivery_service = DeliveryService(
        session_factory
    )
    runtime = DeliveryRuntime(
        delivery_service
    )

    def mission_instruction(
        mission_id: str,
    ) -> str:
        with session_factory() as db:
            from ai_hq.missions.models import Mission

            mission = db.get(
                Mission,
                mission_id,
            )

            if mission is None:
                raise KeyError(
                    f"mission not found: {mission_id}"
                )

            return mission.description

    sources = {
        "ai-hq": Path(ai_hq_source),
        "dripvid": Path(dripvid_source),
    }

    def runner_factory(
        repository: str,
    ) -> DeliveryAgentRunner:
        source = sources.get(repository)

        if source is None:
            raise ValueError(
                "unknown trusted repository"
            )

        context = RepositoryContextProvider(
            repository=repository,
            source_path=source,
        )

        def provide_context(
            mission_id: str,
        ):
            return context.build(
                instruction=mission_instruction(
                    mission_id
                )
            )

        developer = ModelBackedDeveloperAgent(
            model_client,
            context_provider=provide_context,
        )

        qa = ModelBackedQAAgent(
            model_client
        )

        sandbox = IsolatedRepositorySandbox(
            profile_registry=profiles,
            repository_key=repository,
            sandbox_root=(
                sandbox_root / repository
            ),
        )

        return DeliveryAgentRunner(
            runtime=runtime,
            developer=developer,
            qa=qa,
            candidate_verifier=CandidateVerifier(),
            workspace_service=sandbox,
        )

    return CodeChangeService(
        mission_service=mission_service,
        delivery_service=delivery_service,
        runner_factory=runner_factory,
    )
