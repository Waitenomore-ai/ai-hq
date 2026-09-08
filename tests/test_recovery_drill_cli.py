import json

import pytest

from ai_hq.recovery.drill import main


class StubServiceResult:
    def __init__(self, result):
        self.result = result

    def run(self, *, settings):
        return dict(self.result)


def test_cli_rejects_all_control_surface_arguments():
    for argv in (
        ["--target", "dripvid"],
        ["--component", "app"],
        ["--url", "http://127.0.0.1/health"],
        ["--command", "restart"],
        ["--threshold", "2"],
        ["dripvid"],
        ["--unknown"],
    ):
        with pytest.raises(SystemExit) as exc:
            main(argv, service=StubServiceResult({"ok": False, "code": "unused"}), settings=object())
        assert exc.value.code != 0


def test_cli_json_outputs_only_bounded_service_result(capsys):
    result = {
        "ok": True,
        "target": "dripvid",
        "component": "app",
        "incident_id": "incident-123",
        "incident_state": "suspect",
        "consecutive_failures": 3,
        "status": "unhealthy",
        "observe_only": True,
    }

    exit_code = main(
        ["--json"],
        service=StubServiceResult(result),
        settings=object(),
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == result


def test_cli_failure_is_bounded_and_nonzero(capsys):
    exit_code = main(
        ["--json"],
        service=StubServiceResult({"ok": False, "code": "observe_only_required"}),
        settings=object(),
    )

    assert exit_code != 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "code": "observe_only_required",
    }
