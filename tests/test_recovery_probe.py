from dataclasses import FrozenInstanceError

import httpx
import pytest

from ai_hq.recovery.probe import (
    MAX_READINESS_BYTES,
    DripVidReadinessProbe,
    recovery_diagnostic_targets,
)


HEALTHY = {
    "ok": True,
    "database": True,
    "jellyfin": True,
    "radarr": True,
    "sonarr": True,
    "qbittorrent": True,
    "requestSync": True,
    "storage": {
        "available": True,
        "writable": True,
        "belowReserve": False,
        "freeBytes": 250 * 1024**3,
        "reserveBytes": 50 * 1024**3,
    },
    "version": "2.90.0",
    "ignored": "must not be copied",
}


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_200_valid_json_returns_bounded_normalized_snapshot():
    client = client_for(lambda _request: httpx.Response(200, json=HEALTHY))
    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client,
    )

    result = probe.probe()

    assert result == {
        "reachable": True,
        "status_code": 200,
        "ok": True,
        "database": True,
        "jellyfin": True,
        "radarr": True,
        "sonarr": True,
        "qbittorrent": True,
        "requestSync": True,
        "storage": {
            "available": True,
            "writable": True,
            "belowReserve": False,
            "freeBytes": 250 * 1024**3,
            "reserveBytes": 50 * 1024**3,
        },
        "error": None,
    }
    assert "version" not in result
    assert "ignored" not in result


def test_http_503_valid_json_is_reachable_unhealthy_not_exception():
    payload = {
        **HEALTHY,
        "ok": False,
        "jellyfin": False,
    }
    client = client_for(lambda _request: httpx.Response(503, json=payload))
    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client,
    )

    result = probe.probe()

    assert result["reachable"] is True
    assert result["status_code"] == 503
    assert result["ok"] is False
    assert result["jellyfin"] is False
    assert result["error"] is None


def test_timeout_is_normalized_without_raw_exception_text():
    def handler(request):
        raise httpx.ReadTimeout("private timeout detail", request=request)

    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(handler),
    )

    assert probe.probe() == {
        "reachable": False,
        "status_code": None,
        "ok": False,
        "error": "timeout",
    }


def test_connection_failure_is_normalized_without_raw_exception_text():
    def handler(request):
        raise httpx.ConnectError("private socket detail", request=request)

    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(handler),
    )

    assert probe.probe() == {
        "reachable": False,
        "status_code": None,
        "ok": False,
        "error": "connection_error",
    }


def test_invalid_json_is_bounded_failure():
    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(
            lambda _request: httpx.Response(200, content=b"not-json-secret-body")
        ),
    )

    result = probe.probe()

    assert result == {
        "reachable": True,
        "status_code": 200,
        "ok": False,
        "error": "invalid_json",
    }
    assert "secret" not in str(result)


def test_oversized_response_is_rejected_before_json_persistence():
    body = b"{" + (b"x" * MAX_READINESS_BYTES) + b"}"
    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(lambda _request: httpx.Response(200, content=body)),
    )

    assert probe.probe() == {
        "reachable": True,
        "status_code": 200,
        "ok": False,
        "error": "response_too_large",
    }


def test_storage_unavailable_remains_structured_signal():
    payload = {
        **HEALTHY,
        "ok": False,
        "storage": {
            **HEALTHY["storage"],
            "available": False,
            "writable": False,
        },
    }
    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(lambda _request: httpx.Response(503, json=payload)),
    )

    result = probe.probe()

    assert result["storage"]["available"] is False
    assert result["storage"]["writable"] is False
    assert result["ok"] is False


def test_probe_never_returns_headers_cookies_or_unrecognized_fields():
    def handler(_request):
        return httpx.Response(
            200,
            json={**HEALTHY, "secret": "do-not-copy"},
            headers={
                "set-cookie": "private-session=abc",
                "authorization": "Bearer private",
            },
        )

    probe = DripVidReadinessProbe(
        "http://127.0.0.1:3000/health/ready",
        client=client_for(handler),
    )
    serialized = repr(probe.probe())

    assert "private-session" not in serialized
    assert "Bearer private" not in serialized
    assert "do-not-copy" not in serialized
    assert "headers" not in serialized
    assert "cookies" not in serialized


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:3000/health/ready",
        "http://192.168.0.24:3000/health/ready",
        "http://example.com/health/ready",
        "file:///etc/passwd",
    ],
)
def test_probe_rejects_non_loopback_http_url(url):
    with pytest.raises(ValueError, match="loopback HTTP"):
        DripVidReadinessProbe(url)


def test_diagnostic_targets_are_fixed_server_side_and_read_only():
    targets = recovery_diagnostic_targets()

    expected = {
        "dripvid-app": ("dripvid", "dripvid"),
        "dripvid-mcp": ("dripvid-mcp", "dripvid-mcp"),
        "dripvid-proxy": ("nginx", "nginx"),
        "dripvid-tunnel": ("cloudflared", "cloudflared"),
        "dripvid-database": ("postgresql", "postgresql"),
    }

    for key, (service_target, log_target) in expected.items():
        target = targets.require(key)
        assert target.host_helper_service_target == service_target
        assert target.host_helper_log_target == log_target
        assert target.allowed_capabilities == frozenset(
            {"service.status.read", "service.logs.read"}
        )
        assert not target.allows("service.recover")
        assert not target.allows("service.restart")


def test_diagnostic_target_mapping_is_frozen_after_construction():
    target = recovery_diagnostic_targets().require("dripvid-app")

    with pytest.raises(FrozenInstanceError):
        target.host_helper_service_target = "nginx"
