from __future__ import annotations

import json
from typing import Any

from ai_hq.chat.model_client import ChatModelClient
from ai_hq.delivery.models import QAResult


_DEVELOPER_SYSTEM_PROMPT = """
You are the AI HQ Developer agent.

Produce a proposed implementation candidate for the supplied mission.

You are a planning and reasoning boundary only. You do not have deployment,
production, shell, host-helper, service-management, Docker, or infrastructure
authority.

Return ONLY a valid JSON object with exactly these fields:

{
  "change_ref": "immutable reference for the proposed candidate",
  "summary": "concise implementation summary",
  "changed_files": ["path/example.py"],
  "evidence": {
    "key": "supporting evidence"
  }
}

Requirements:
- change_ref is required and must be non-empty.
- change_ref represents the immutable candidate reference supplied by the
  controlled delivery workflow.
- summary is required and must be non-empty.
- changed_files must be a JSON array of strings.
- evidence is required and must be a non-empty JSON object.
- Do not include Markdown fences.
- Do not include prose outside the JSON object.
""".strip()


_QA_SYSTEM_PROMPT = """
You are the AI HQ QA agent.

Independently review the exact Developer candidate supplied to you.

You are a review boundary only. You do not have deployment, production,
shell, host-helper, service-management, Docker, or infrastructure authority.

The Developer change_ref is immutable. Review only that exact reference.

Return ONLY a valid JSON object with exactly these fields:

{
  "result": "PASSED or FAILED",
  "evidence": {
    "key": "QA review evidence"
  }
}

Requirements:
- result must be exactly PASSED or FAILED.
- evidence is required and must be a non-empty JSON object.
- Do not invent or replace the Developer change_ref.
- Do not include Markdown fences.
- Do not include prose outside the JSON object.
""".strip()


def _parse_json_object(
    raw: str,
    *,
    source: str,
) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError(
            f"{source} must return JSON text"
        )

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(
            f"{source} must return valid JSON"
        ) from None

    if not isinstance(parsed, dict):
        raise ValueError(
            f"{source} JSON must be an object"
        )

    return parsed


class ModelBackedDeveloperAgent:
    """
    Model-backed Developer reasoning boundary.

    The model proposes structured candidate metadata only.
    This class does not execute code or grant production authority.
    """

    def __init__(
        self,
        model_client: ChatModelClient,
    ) -> None:
        self.model_client = model_client

    def execute(
        self,
        *,
        mission_id: str,
    ) -> dict[str, Any]:
        raw = self.model_client.reply(
            _DEVELOPER_SYSTEM_PROMPT,
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "mission_id": mission_id,
                            "instruction": (
                                "Produce the structured Developer "
                                "candidate for this mission."
                            ),
                        },
                        sort_keys=True,
                    ),
                }
            ],
        )

        candidate = _parse_json_object(
            raw,
            source="Developer",
        )

        change_ref = candidate.get("change_ref")

        if (
            not isinstance(change_ref, str)
            or not change_ref.strip()
        ):
            raise ValueError(
                "Developer JSON requires change_ref"
            )

        summary = candidate.get("summary")

        if (
            not isinstance(summary, str)
            or not summary.strip()
        ):
            raise ValueError(
                "Developer JSON requires summary"
            )

        changed_files = candidate.get(
            "changed_files",
            [],
        )

        if not isinstance(changed_files, list):
            raise ValueError(
                "Developer changed_files must be a list"
            )

        if not all(
            isinstance(path, str)
            for path in changed_files
        ):
            raise ValueError(
                "Developer changed_files must contain strings"
            )

        evidence = candidate.get("evidence")

        if (
            not isinstance(evidence, dict)
            or not evidence
        ):
            raise ValueError(
                "Developer JSON requires evidence"
            )

        return {
            "change_ref": change_ref.strip(),
            "summary": summary.strip(),
            "changed_files": list(changed_files),
            "evidence": dict(evidence),
        }


class ModelBackedQAAgent:
    """
    Model-backed QA reasoning boundary.

    QA receives the exact persisted Developer candidate and can only
    return PASSED or FAILED plus review evidence.
    """

    def __init__(
        self,
        model_client: ChatModelClient,
    ) -> None:
        self.model_client = model_client

    def review(
        self,
        *,
        mission_id: str,
        change_ref: str,
        summary: str,
        changed_files: list[str],
        developer_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        raw = self.model_client.reply(
            _QA_SYSTEM_PROMPT,
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "mission_id": mission_id,
                            "change_ref": change_ref,
                            "summary": summary,
                            "changed_files": list(
                                changed_files
                            ),
                            "developer_evidence": dict(
                                developer_evidence
                            ),
                        },
                        sort_keys=True,
                    ),
                }
            ],
        )

        review = _parse_json_object(
            raw,
            source="QA",
        )

        raw_result = review.get("result")

        try:
            qa_result = QAResult(raw_result)
        except (TypeError, ValueError):
            raise ValueError(
                "QA result must be PASSED or FAILED"
            ) from None

        evidence = review.get("evidence")

        if (
            not isinstance(evidence, dict)
            or not evidence
        ):
            raise ValueError(
                "QA JSON requires evidence"
            )

        return {
            "result": qa_result,
            "evidence": dict(evidence),
        }
