from pathlib import Path

from ai_hq.code_changes.context import RepositoryContextProvider


def build_context(
    root: Path,
    instruction: str = "update toolbar styling",
):
    provider = RepositoryContextProvider(
        repository="dripvid",
        source_path=root,
    )

    return provider.build(
        instruction=instruction,
    )


def context_paths(context: dict) -> set[str]:
    return {
        item["path"]
        for item in context["files"]
    }


def context_text(context: dict) -> str:
    return "\n".join(
        item["content"]
        for item in context["files"]
    )


def test_env_variants_are_never_exposed(
    tmp_path: Path,
):
    (tmp_path / ".env.staging").write_text(
        "TOOLBAR_API_KEY=super-secret-value\n",
        encoding="utf-8",
    )

    css = tmp_path / "toolbar.css"
    css.write_text(
        ".toolbar { padding: 1rem; }\n",
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert ".env.staging" not in context_paths(context)
    assert "super-secret-value" not in context_text(context)


def test_shell_file_with_api_key_is_not_exposed(
    tmp_path: Path,
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()

    secret_file = scripts / "toolbar.sh"
    secret_file.write_text(
        (
            "#!/bin/sh\n"
            "export OPENROUTER_API_KEY="
            "\"sk-or-v1-1234567890abcdefghijklmnop\"\n"
            "echo toolbar\n"
        ),
        encoding="utf-8",
    )

    safe_file = tmp_path / "toolbar.css"
    safe_file.write_text(
        ".toolbar { min-height: 56px; }\n",
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    paths = context_paths(context)

    assert "toolbar.css" in paths
    assert "scripts/toolbar.sh" not in paths
    assert "sk-or-v1-" not in context_text(context)


def test_json_file_with_password_is_not_exposed(
    tmp_path: Path,
):
    secret_file = tmp_path / "toolbar-config.json"
    secret_file.write_text(
        (
            '{\n'
            '  "toolbar": true,\n'
            '  "password": '
            '"CorrectHorseBatteryStaple123"\n'
            '}\n'
        ),
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert (
        "toolbar-config.json"
        not in context_paths(context)
    )

    assert (
        "CorrectHorseBatteryStaple123"
        not in context_text(context)
    )


def test_private_key_material_is_not_exposed(
    tmp_path: Path,
):
    secret_file = tmp_path / "toolbar-notes.md"
    secret_file.write_text(
        (
            "# Toolbar\n\n"
            "-----BEGIN PRIVATE KEY-----\n"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n"
            "-----END PRIVATE KEY-----\n"
        ),
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert (
        "toolbar-notes.md"
        not in context_paths(context)
    )

    assert (
        "BEGIN PRIVATE KEY"
        not in context_text(context)
    )


def test_known_token_formats_are_not_exposed(
    tmp_path: Path,
):
    secret_file = tmp_path / "toolbar-debug.md"
    secret_file.write_text(
        (
            "# Toolbar debug\n\n"
            "Temporary token:\n"
            "github_pat_11ABCDEFG_"
            "abcdefghijklmnopqrstuvwxyz0123456789\n"
        ),
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert (
        "toolbar-debug.md"
        not in context_paths(context)
    )

    assert (
        "github_pat_"
        not in context_text(context)
    )


def test_placeholder_credentials_do_not_hide_safe_docs(
    tmp_path: Path,
):
    safe_file = tmp_path / "toolbar-setup.md"
    safe_file.write_text(
        (
            "# Toolbar setup\n\n"
            "Set API_KEY=your-api-key-here before running "
            "the local development example.\n"
        ),
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert (
        "toolbar-setup.md"
        in context_paths(context)
    )


def test_normal_source_with_security_words_is_allowed(
    tmp_path: Path,
):
    safe_file = tmp_path / "toolbar.py"
    safe_file.write_text(
        (
            "def validate_password(password: str) -> bool:\n"
            "    return len(password) >= 12\n\n"
            "def toolbar_size() -> int:\n"
            "    return 56\n"
        ),
        encoding="utf-8",
    )

    context = build_context(tmp_path)

    assert "toolbar.py" in context_paths(context)
