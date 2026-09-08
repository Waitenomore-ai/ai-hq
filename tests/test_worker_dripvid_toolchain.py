from pathlib import Path


def _dockerfile_stages() -> tuple[str, str]:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    web_marker = "FROM base AS web"
    worker_marker = "FROM base AS worker"
    assert web_marker in dockerfile
    assert worker_marker in dockerfile
    web_start = dockerfile.index(web_marker)
    worker_start = dockerfile.index(worker_marker)
    return dockerfile[web_start:worker_start], dockerfile[worker_start:]


def test_worker_image_installs_dripvid_verification_toolchain():
    _, worker_stage = _dockerfile_stages()

    assert "apt-get install" in worker_stage
    assert "git" in worker_stage
    assert "nodejs" in worker_stage
    assert "npm" in worker_stage


def test_web_image_does_not_install_dripvid_verification_toolchain():
    web_stage, _ = _dockerfile_stages()

    assert "apt-get install" not in web_stage
