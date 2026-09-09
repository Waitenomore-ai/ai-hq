from __future__ import annotations

import stat
import sys
from pathlib import Path

import httpx

from ai_hq.code_changes.candidate_store import CandidateStore
from ai_hq.code_changes.context import RepositoryContextProvider
from ai_hq.code_changes.publisher import (
    GitHubCandidatePublisher,
    build_default_publish_targets,
)
from ai_hq.code_changes.service import CodeChangeService
from ai_hq.repository_source_policy import validate_production_repository_paths
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent, ModelBackedQAAgent
from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
    build_dripvid_repository_profile,
)
from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox
from ai_hq.delivery.runtime import DeliveryRuntime
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.service import MissionService


_MAX_GITHUB_TOKEN_BYTES = 4096


def load_github_publish_token(path: Path) -> str:
    token_path = Path(path).expanduser()
    try:
        metadata = token_path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("GitHub publisher token must be a regular file") from exc

    if token_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("GitHub publisher token must be a regular non-symlink file")
    if sys.platform != "win32":
        if metadata.st_mode & 0o077:
            raise ValueError("GitHub publisher token file permissions are too broad")
        if not metadata.st_mode & stat.S_IRUSR:
            raise ValueError("GitHub publisher token file must be owner-readable")
    if metadata.st_size > _MAX_GITHUB_TOKEN_BYTES:
        raise ValueError("GitHub publisher token file is too large")

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("GitHub publisher token file is empty")
    if any(character.isspace() for character in token):
        raise ValueError("GitHub publisher token contains invalid whitespace")
    return token


def build_code_change_service(
    *,
    settings,
    session_factory,
    model_client,
    enable_publishing: bool = False,
) -> CodeChangeService | None:
    """Build the trusted code-change service; publication is worker opt-in."""
    sandbox_root = settings.repository_sandbox_root_path
    ai_hq_source = settings.ai_hq_repository_source_path
    dripvid_source = settings.dripvid_repository_source_path
    mirror_root = getattr(settings, "repository_mirror_root_path", None)

    validate_production_repository_paths(
        is_production=bool(getattr(settings, "is_production", False)),
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
            build_ai_hq_repository_profile(source_path=ai_hq_source, base_ref="main"),
            build_dripvid_repository_profile(source_path=dripvid_source, base_ref="main"),
        )
    )

    mission_service = MissionService(session_factory)
    delivery_service = DeliveryService(session_factory)
    runtime = DeliveryRuntime(delivery_service)

    def mission_instruction(mission_id: str) -> str:
        with session_factory() as db:
            from ai_hq.missions.models import Mission

            mission = db.get(Mission, mission_id)
            if mission is None:
                raise KeyError(f"mission not found: {mission_id}")
            return mission.description

    sources = {
        "ai-hq": Path(ai_hq_source),
        "dripvid": Path(dripvid_source),
    }

    def runner_factory(repository: str) -> DeliveryAgentRunner:
        source = sources.get(repository)
        if source is None:
            raise ValueError("unknown trusted repository")

        context = RepositoryContextProvider(repository=repository, source_path=source)

        def provide_context(mission_id: str):
            return context.build(instruction=mission_instruction(mission_id))

        developer = ModelBackedDeveloperAgent(
            model_client,
            context_provider=provide_context,
        )
        qa = ModelBackedQAAgent(model_client)
        sandbox = IsolatedRepositorySandbox(
            profile_registry=profiles,
            repository_key=repository,
            sandbox_root=sandbox_root / repository,
        )

        return DeliveryAgentRunner(
            runtime=runtime,
            developer=developer,
            qa=qa,
            candidate_verifier=CandidateVerifier(),
            workspace_service=sandbox,
        )

    candidate_store = None
    publisher = None
    token_file = getattr(settings, "github_publish_token_file", None)
    if enable_publishing and token_file:
        token = load_github_publish_token(Path(token_file))
        candidate_store = CandidateStore(sandbox_root)
        publisher = GitHubCandidatePublisher(
            http_client=httpx.Client(timeout=10.0),
            token=token,
            candidate_store=candidate_store,
            targets=build_default_publish_targets(),
        )

    return CodeChangeService(
        mission_service=mission_service,
        delivery_service=delivery_service,
        runner_factory=runner_factory,
        candidate_store=candidate_store,
        publisher=publisher,
        repository_descriptions={
            profile.key: profile.description
            for profile in (
                build_ai_hq_repository_profile(source_path=ai_hq_source, base_ref="main"),
                build_dripvid_repository_profile(source_path=dripvid_source, base_ref="main"),
            )
        },
    )
