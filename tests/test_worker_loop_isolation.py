"""Worker loop isolation: a code-change failure must not kill the worker.

A malformed model response must fail the code-change mission safely without
terminating the worker process. Only the code-change stage is isolated here;
other worker-stage failures keep their existing propagation semantics.
"""

import pytest

from ai_hq.worker import run_worker_iteration


class StubAutonomousRunner:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error

    def run_once(self):
        if self.error is not None:
            raise self.error
        return self.result


class StubCodeChangeRunner:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error

    def run_once(self):
        if self.error is not None:
            raise self.error
        return self.result


class StubDepartmentRunner:
    def __init__(self, *, worked=False, error=None):
        self.worked = worked
        self.error = error
        self.calls = 0

    def run_once(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.worked


def test_code_change_failure_does_not_kill_worker_iteration():
    department = StubDepartmentRunner(worked=True)
    worked = run_worker_iteration(
        autonomous_runner=StubAutonomousRunner(),
        department_runner=department,
        code_change_runner=StubCodeChangeRunner(
            error=ValueError("Developer must return valid JSON"),
        ),
    )
    assert worked is True
    assert department.calls == 1


def test_code_change_failure_with_no_other_work_returns_false():
    worked = run_worker_iteration(
        autonomous_runner=StubAutonomousRunner(),
        department_runner=StubDepartmentRunner(worked=False),
        code_change_runner=StubCodeChangeRunner(
            error=ValueError("Developer must return valid JSON"),
        ),
    )
    assert worked is False


def test_code_change_success_still_reports_work():
    worked = run_worker_iteration(
        autonomous_runner=StubAutonomousRunner(),
        department_runner=StubDepartmentRunner(worked=False),
        code_change_runner=StubCodeChangeRunner(result="candidate"),
    )
    assert worked is True


def test_autonomous_failure_keeps_propagating():
    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_worker_iteration(
            autonomous_runner=StubAutonomousRunner(
                error=RuntimeError("provider unavailable"),
            ),
            department_runner=StubDepartmentRunner(worked=False),
            code_change_runner=StubCodeChangeRunner(),
        )


def test_department_failure_keeps_propagating():
    with pytest.raises(RuntimeError, match="template rendering failed"):
        run_worker_iteration(
            autonomous_runner=StubAutonomousRunner(),
            department_runner=StubDepartmentRunner(
                error=RuntimeError("template rendering failed"),
            ),
            code_change_runner=StubCodeChangeRunner(),
        )


def test_recovery_result_still_reported_when_no_other_work():
    class StubRecoveryCoordinator:
        def run_if_due(self, settings):
            return True

        def handle_execution_result(self, result):
            raise AssertionError("must not be called")

    worked = run_worker_iteration(
        autonomous_runner=StubAutonomousRunner(),
        department_runner=StubDepartmentRunner(worked=False),
        code_change_runner=StubCodeChangeRunner(),
        recovery_coordinator=StubRecoveryCoordinator(),
        settings=object(),
    )
    assert worked is True
