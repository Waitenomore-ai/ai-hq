"""
SysAdmin Chat v1 HTTP API contract.

Task 5 is deliberately test-first.

The API must:
- use AI HQ's authenticated session;
- bind conversations to that session;
- protect writes with existing Origin + CSRF checks;
- expose only natural-language SysAdmin chat;
- route operational work through ChatController;
- never expose arbitrary tools, targets, shell, or Host Helper;
- support polling persisted operational mission results.
"""

from pathlib import Path


API_PATH = Path("src/ai_hq/chat/api.py")
APP_PATH = Path("src/ai_hq/app.py")


def api_source() -> str:
    return API_PATH.read_text()


def test_chat_api_module_exists():
    from ai_hq.chat import api

    assert api is not None


def test_chat_api_exports_route_installer():
    from ai_hq.chat.api import install_chat_routes

    assert callable(install_chat_routes)


def test_application_installs_chat_routes():
    source = APP_PATH.read_text()

    assert "install_chat_routes" in source


def test_chat_api_reuses_existing_authenticated_session_resolution():
    source = api_source()

    assert "resolve_request_session" in source


def test_chat_api_reuses_existing_origin_protection():
    source = api_source()

    assert "_origin_is_allowed" in source


def test_chat_api_enforces_csrf_on_writes():
    source = api_source().lower()

    assert "csrf" in source
    assert "compare_digest" in source


def test_chat_api_creates_only_sysadmin_conversations():
    source = api_source()

    assert "/api/chat/conversations" in source
    assert "create_conversation" in source
    assert 'agent_key="sysadmin"' in source


def test_chat_api_lists_owned_conversation_messages():
    source = api_source()

    assert "/messages" in source
    assert "chat_service.messages" in source
    assert "owner_session_id" in source
    assert "conversation_id" in source


def test_chat_api_submits_natural_language_to_controller():
    source = api_source()

    assert "ChatController" in source
    assert ".submit(" in source
    assert '"text"' in source or "'text'" in source


def test_chat_api_exposes_mission_refresh_polling():
    source = api_source()

    assert "/missions/" in source
    assert ".refresh(" in source


def test_chat_api_response_exposes_controller_contract():
    source = api_source()

    assert '"state"' in source
    assert '"message"' in source
    assert '"mission_id"' in source


def test_chat_api_does_not_create_missions_directly():
    source = api_source()

    # Mission creation and hard-allowlisted planning belong to
    # ChatController, never the HTTP boundary.
    assert ".create_mission(" not in source
    assert ".create_plan(" not in source


def test_chat_api_does_not_execute_infrastructure_directly():
    source = api_source()

    forbidden = (
        "HostHelper",
        "host_helper.client",
        "host_helper.executor",
        "ToolGateway(",
        ".execute(",
    )

    for item in forbidden:
        assert item not in source


def test_chat_api_does_not_expose_client_selected_execution_fields():
    source = api_source()

    # Client input is natural-language text. It must not become an
    # arbitrary execution API.
    forbidden = (
        '"tool_name"',
        "'tool_name'",
        '"tool_arguments"',
        "'tool_arguments'",
        '"capability"',
        "'capability'",
        '"command"',
        "'command'",
    )

    for item in forbidden:
        assert item not in source


def test_chat_api_has_no_mutation_routes():
    source = api_source().lower()

    forbidden = (
        "/restart",
        "/deploy",
        "/rollback",
        "/shell",
        "/command",
        "/execute",
        "/stop",
        "/start",
    )

    for item in forbidden:
        assert item not in source

def test_chat_api_app_construction_does_not_require_operational_transport():
    source = api_source()
    assert "build_operational_tool_registry" not in source
    assert "transport=" not in source
    assert "ValidationToolRegistry" in source


def test_chat_api_validation_registry_is_exactly_read_only():
    source = api_source()

    for tool in (
        "system.health.read",
        "service.status.read",
        "service.logs.read",
    ):
        assert tool in source

    for forbidden in (
        "service.restart",
        "service.stop",
        "service.start",
        "shell.execute",
    ):
        assert forbidden not in source
