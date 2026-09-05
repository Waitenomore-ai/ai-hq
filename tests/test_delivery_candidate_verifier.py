import pytest

from ai_hq.delivery.candidate_verifier import (
    CandidateVerifier,
    VerifiedCandidate,
)


def proposal():
    return {
        "change_ref": "MODEL-INVENTED-REF-MUST-NOT-BE-TRUSTED",
        "summary": "Add safe Developer and QA orchestration",
        "changed_files": [
            "src/ai_hq/delivery/example.py",
            "tests/test_delivery_example.py",
        ],
        "evidence": {
            "model_claim": "tests passed",
        },
    }


def test_verifier_returns_verified_candidate():
    verifier = CandidateVerifier()

    result = verifier.verify(
        mission_id="mission-1",
        proposal=proposal(),
    )

    assert isinstance(result, VerifiedCandidate)


def test_verifier_does_not_trust_model_change_ref():
    verifier = CandidateVerifier()

    result = verifier.verify(
        mission_id="mission-2",
        proposal=proposal(),
    )

    assert result.change_ref
    assert result.change_ref != (
        "MODEL-INVENTED-REF-MUST-NOT-BE-TRUSTED"
    )


def test_change_ref_is_deterministic_for_exact_candidate():
    verifier = CandidateVerifier()

    first = verifier.verify(
        mission_id="mission-3",
        proposal=proposal(),
    )

    second = verifier.verify(
        mission_id="mission-3",
        proposal=proposal(),
    )

    assert first.change_ref == second.change_ref


def test_change_ref_changes_when_candidate_changes():
    verifier = CandidateVerifier()

    first_proposal = proposal()
    second_proposal = proposal()

    second_proposal["summary"] = (
        "A materially different implementation"
    )

    first = verifier.verify(
        mission_id="mission-4",
        proposal=first_proposal,
    )

    second = verifier.verify(
        mission_id="mission-4",
        proposal=second_proposal,
    )

    assert first.change_ref != second.change_ref


def test_model_evidence_is_not_promoted_to_verified_evidence():
    verifier = CandidateVerifier()

    result = verifier.verify(
        mission_id="mission-5",
        proposal=proposal(),
    )

    assert "model_claim" not in result.evidence


def test_verifier_records_machine_generated_identity_evidence():
    verifier = CandidateVerifier()

    result = verifier.verify(
        mission_id="mission-6",
        proposal=proposal(),
    )

    assert result.evidence["verification"] == (
        "candidate_identity_verified"
    )

    assert (
        result.evidence["change_ref"]
        == result.change_ref
    )


def test_verified_candidate_preserves_summary_and_files():
    verifier = CandidateVerifier()

    result = verifier.verify(
        mission_id="mission-7",
        proposal=proposal(),
    )

    assert result.summary == proposal()["summary"]
    assert result.changed_files == proposal()["changed_files"]


def test_verifier_rejects_missing_summary():
    verifier = CandidateVerifier()

    bad = proposal()
    bad["summary"] = ""

    with pytest.raises(ValueError, match="summary"):
        verifier.verify(
            mission_id="mission-8",
            proposal=bad,
        )


def test_verifier_rejects_invalid_changed_files():
    verifier = CandidateVerifier()

    bad = proposal()
    bad["changed_files"] = "src/example.py"

    with pytest.raises(
        ValueError,
        match="changed_files",
    ):
        verifier.verify(
            mission_id="mission-9",
            proposal=bad,
        )


def test_verifier_rejects_non_mapping_proposal():
    verifier = CandidateVerifier()

    with pytest.raises(ValueError, match="proposal"):
        verifier.verify(
            mission_id="mission-10",
            proposal="not-a-mapping",
        )


def test_identity_is_bound_to_mission():
    verifier = CandidateVerifier()

    first = verifier.verify(
        mission_id="mission-A",
        proposal=proposal(),
    )

    second = verifier.verify(
        mission_id="mission-B",
        proposal=proposal(),
    )

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
