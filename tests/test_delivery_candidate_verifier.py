import pytest

from ai_hq.delivery.candidate_verifier import (
    CandidateVerifier,
    VerifiedCandidate,
)
from ai_hq.delivery.repository_workspace import CandidateSnapshot
from ai_hq.delivery.repository_workspace import (
    TestEvidence as WorkspaceTestEvidence,
)


def proposal():
    return {
        "change_ref": "MODEL-INVENTED-REF-MUST-NOT-BE-TRUSTED",
        "summary": "Add safe Developer and QA orchestration",
        "changed_files": ["model/claimed.py"],
        "evidence": {"model_claim": "tests passed"},
    }


def snapshot(*, diff_char="a", content_char="b", files=None):
    return CandidateSnapshot(
        workspace_id="workspace-1",
        repository="Waitenomore-ai/ai-hq",
        base_ref="abc123",
        changed_files=tuple(files or ("src/real.py", "tests/test_real.py")),
        diff_digest="sha256:" + (diff_char * 64),
        content_digest="sha256:" + (content_char * 64),
    )


def machine_test_evidence(*, passed=True, exit_code=0):
    return WorkspaceTestEvidence(
        passed=passed,
        exit_code=exit_code,
        summary="42 passed" if passed else "1 failed",
        evidence_digest="sha256:" + ("c" * 64),
    )


def verify(*, mission_id="mission-1", candidate=None, snap=None, tests=None):
    return CandidateVerifier().verify(
        mission_id=mission_id,
        proposal=candidate or proposal(),
        snapshot=snap or snapshot(),
        test_evidence=tests or machine_test_evidence(),
    )


def test_verifier_returns_verified_candidate():
    assert isinstance(verify(), VerifiedCandidate)


def test_verifier_ignores_model_change_ref_and_claimed_files():
    result = verify()

    assert result.change_ref.startswith("sha256:")
    assert result.change_ref != proposal()["change_ref"]
    assert result.changed_files == ["src/real.py", "tests/test_real.py"]
    assert "model/claimed.py" not in result.changed_files


def test_change_ref_is_deterministic_for_exact_machine_snapshot():
    first = verify(mission_id="mission-2")
    second = verify(mission_id="mission-2")

    assert first.change_ref == second.change_ref


def test_change_ref_changes_when_snapshot_changes():
    first = verify(
        mission_id="mission-3",
        snap=snapshot(diff_char="a"),
    )
    second = verify(
        mission_id="mission-3",
        snap=snapshot(diff_char="d"),
    )

    assert first.change_ref != second.change_ref


def test_human_readable_summary_does_not_define_candidate_identity():
    first_candidate = proposal()
    second_candidate = proposal()
    second_candidate["summary"] = "Different descriptive wording"

    first = verify(mission_id="mission-4", candidate=first_candidate)
    second = verify(mission_id="mission-4", candidate=second_candidate)

    assert first.change_ref == second.change_ref
    assert first.summary != second.summary


def test_model_evidence_is_not_promoted_to_verified_evidence():
    result = verify(mission_id="mission-5")

    assert "model_claim" not in result.evidence
    assert "MODEL-INVENTED" not in str(result.evidence)


def test_verifier_records_machine_generated_repository_and_test_evidence():
    result = verify(mission_id="mission-6")

    assert result.evidence == {
        "verification": "candidate_identity_verified",
        "algorithm": "sha256",
        "change_ref": result.change_ref,
        "workspace_id": "workspace-1",
        "repository": "Waitenomore-ai/ai-hq",
        "base_ref": "abc123",
        "diff_digest": "sha256:" + ("a" * 64),
        "content_digest": "sha256:" + ("b" * 64),
        "tests": {
            "passed": True,
            "exit_code": 0,
            "summary": "42 passed",
            "evidence_digest": "sha256:" + ("c" * 64),
        },
    }


def test_verifier_rejects_missing_summary():
    bad = proposal()
    bad["summary"] = ""

    with pytest.raises(ValueError, match="summary"):
        verify(mission_id="mission-7", candidate=bad)


def test_verifier_rejects_non_mapping_proposal():
    with pytest.raises(TypeError, match="proposal"):
        CandidateVerifier().verify(
            mission_id="mission-8",
            proposal="not-a-mapping",
            snapshot=snapshot(),
            test_evidence=machine_test_evidence(),
        )


def test_identity_is_bound_to_mission():
    first = verify(mission_id="mission-A")
    second = verify(mission_id="mission-B")

    assert first.change_ref != second.change_ref


def test_verifier_has_no_execution_or_production_authority():
    import inspect

    import ai_hq.delivery.candidate_verifier as module

    source = inspect.getsource(module)

    prohibited = (
        "subprocess.run(",
        "subprocess.Popen(",
        "os.system(",
        ".deploy(",
        ".rollback(",
        ".restart(",
        "HostHelperClient(",
        "ToolGateway(",
    )

    for token in prohibited:
        assert token not in source
