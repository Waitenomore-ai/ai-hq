from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()


def test_soup_is_pinned_in_worker_stage_only():
    assert "FROM base AS web" in DOCKERFILE
    assert "FROM base AS worker" in DOCKERFILE
    web_stage, worker_stage = DOCKERFILE.split("FROM base AS worker", 1)
    assert "soup-cli" not in web_stage
    assert 'pip install --no-cache-dir "soup-cli==0.74.0"' in worker_stage
    assert "soup-cli[" not in DOCKERFILE


def test_compose_selects_explicit_web_and_worker_targets():
    assert "target: web" in COMPOSE
    assert "target: worker" in COMPOSE
    assert COMPOSE.index("target: web") < COMPOSE.index("worker:")
    assert COMPOSE.index("target: worker") > COMPOSE.index("worker:")


def test_soup_install_does_not_add_runtime_authority():
    lowered = (DOCKERFILE + "\n" + COMPOSE).lower()
    assert "soup mcp" not in lowered
    assert "--allow-execute" not in lowered
    assert "soup-cli[train" not in lowered
    assert "soup-cli[all" not in lowered
