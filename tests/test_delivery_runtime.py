from pathlib import Path

import pytest

from ai_hq.delivery.models import DeliveryStage
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.models import MissionStatus


def _existing_runtime_test_module():
    """
    Marker helper.

    Runtime integration intentionally remains separate from the delivery
    domain tests. These tests define the bridge between the autonomous
    mission runtime and persisted delivery orchestration.
    """
    return True


def test_runtime_delivery_module_contract_exists():
    """
    RED contract:

    Runtime orchestration must expose a dedicated coordinator rather than
    teaching Developer/QA how to execute host or deployment operations.
    """
    from ai_hq.delivery.runtime import DeliveryRuntime

    assert DeliveryRuntime is not None


def test_runtime_can_handoff_completed_sysadmin_mission_to_developer():
    """
    A completed SysAdmin implementation candidate may enter the delivery
    workflow only through an explicit runtime handoff carrying an immutable
    change reference and evidence.

    This does not deploy anything.
    """
    from ai_hq.delivery.runtime import DeliveryRuntime

    assert hasattr(
        DeliveryRuntime,
        "handoff_to_developer",
    )


def test_runtime_handoff_requires_immutable_change_reference():
    """
    The runtime boundary must fail closed when there is no immutable
    proposal/change reference.
    """
    from ai_hq.delivery.runtime import DeliveryRuntime

    assert hasattr(
        DeliveryRuntime,
        "handoff_to_developer",
    )

    # Signature-level contract: change_ref must be explicit.
    import inspect

    signature = inspect.signature(
        DeliveryRuntime.handoff_to_developer
    )

    assert "change_ref" in signature.parameters


def test_runtime_handoff_requires_developer_evidence():
    """
    Developer evidence must cross the runtime boundary explicitly so QA
    never approves an un-evidenced candidate.
    """
    from ai_hq.delivery.runtime import DeliveryRuntime

    import inspect

    signature = inspect.signature(
        DeliveryRuntime.handoff_to_developer
    )

    assert "evidence" in signature.parameters


def test_runtime_layer_contains_no_direct_execution_capability():
    """
    Delivery runtime coordinates persisted state only.

    Shell, subprocess, Docker, service restart and deployment authority
    remain outside Developer/QA orchestration.
    """
    runtime_path = (
        Path(__file__).parents[1]
        / "src"
        / "ai_hq"
        / "delivery"
        / "runtime.py"
    )

    assert runtime_path.exists()

    source = runtime_path.read_text()

    forbidden = (
        "import subprocess",
        "from subprocess",
        "os.system(",
        "shell=True",
        "docker.from_env",
        "systemctl ",
    )

    for token in forbidden:
        assert token not in source
