from pathlib import Path


HOST_HELPER_UNIT = Path("deploy/ai-hq-host-helper.service")


def test_host_helper_network_sandbox_allows_only_unix_and_ipv4_loopback():
    unit = HOST_HELPER_UNIT.read_text(encoding="utf-8")

    assert "RestrictAddressFamilies=AF_UNIX AF_INET" in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=127.0.0.1" in unit
    assert "AF_INET6" not in unit
    assert "IPAddressAllow=any" not in unit
