from pathlib import Path

from ai_hq.code_changes.context import RepositoryContextProvider


def test_context_returns_bounded_relevant_text_files(tmp_path: Path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "nav.css").write_text(
        ".toolbar { height: 80px; }\n",
        encoding="utf-8",
    )
    (tmp_path / "public" / "other.css").write_text(
        ".card { width: 100%; }\n",
        encoding="utf-8",
    )
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")

    provider = RepositoryContextProvider(
        repository="dripvid",
        source_path=tmp_path,
        max_files=5,
        max_chars_per_file=2000,
        max_total_chars=5000,
    )

    context = provider.build(
        instruction="Make the DripVid toolbar smaller"
    )

    assert context["repository"] == "dripvid"
    assert context["instruction"] == (
        "Make the DripVid toolbar smaller"
    )
    assert context["files"]
    assert any(
        item["path"] == "public/nav.css"
        for item in context["files"]
    )
    assert all(
        "content" in item
        for item in context["files"]
    )


def test_context_never_reads_git_or_secret_files(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(
        "SECRET",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TOKEN=secret",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "toolbar = True\n",
        encoding="utf-8",
    )

    provider = RepositoryContextProvider(
        repository="ai-hq",
        source_path=tmp_path,
    )

    context = provider.build(
        instruction="change toolbar"
    )

    paths = {item["path"] for item in context["files"]}

    assert ".env" not in paths
    assert ".git/config" not in paths
    assert "app.py" in paths


def test_context_is_size_bounded(tmp_path: Path):
    for index in range(30):
        (tmp_path / f"toolbar-{index}.py").write_text(
            "x" * 5000,
            encoding="utf-8",
        )

    provider = RepositoryContextProvider(
        repository="ai-hq",
        source_path=tmp_path,
        max_files=3,
        max_chars_per_file=100,
        max_total_chars=250,
    )

    context = provider.build(
        instruction="change toolbar"
    )

    assert len(context["files"]) <= 3
    assert sum(
        len(item["content"])
        for item in context["files"]
    ) <= 250
