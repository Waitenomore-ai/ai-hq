from pathlib import Path

SMOKE = Path(__file__).resolve().parents[1] / "deploy" / "check-production.sh"


def test_production_smoke_validates_restart_safe_read_only_runtime_mount():
    text = SMOKE.read_text()

    assert "{{.Source}}|{{.Destination}}|{{.RW}}" in text
    assert "/run/ai-hq|/run/ai-hq|false" in text
    assert 'fail "worker does not have read-only Host Helper runtime mount"' in text
    assert 'fail "web container must not have Host Helper runtime mount"' in text
    assert "host-helper.sock' <<<\"$worker_mounts\"" not in text
