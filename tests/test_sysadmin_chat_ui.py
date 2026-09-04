from pathlib import Path


TEMPLATE = Path("src/ai_hq/templates/home.html")
JS = Path("src/ai_hq/static/hq.js")
CSS = Path("src/ai_hq/static/hq.css")


def test_sysadmin_room_contains_chat_interface():
    html = TEMPLATE.read_text()

    assert 'id="sysadmin-chat"' in html
    assert 'id="sysadmin-chat-messages"' in html
    assert 'id="sysadmin-chat-form"' in html
    assert 'id="sysadmin-chat-input"' in html
    assert 'id="sysadmin-chat-send"' in html


def test_chat_is_natural_language_only():
    html = TEMPLATE.read_text().lower()

    assert "tool_name" not in html
    assert "tool_arguments" not in html
    assert "command input" not in html
    assert "shell input" not in html


def test_client_uses_authenticated_chat_api():
    js = JS.read_text()

    assert "/api/chat/conversations" in js
    assert "/messages" in js
    assert "/missions/" in js


def test_client_sends_csrf_on_chat_writes():
    js = JS.read_text().lower()

    assert "x-csrf-token" in js
    assert "csrf" in js


def test_client_polls_pending_missions():
    js = JS.read_text()

    assert "setTimeout" in js
    assert "mission_id" in js
    assert "pending" in js


def test_client_exposes_no_execution_controls():
    combined = (
        TEMPLATE.read_text()
        + JS.read_text()
    ).lower()

    for forbidden in (
        "restart server",
        "deploy button",
        "rollback button",
        "shell command",
        "execute command",
    ):
        assert forbidden not in combined


def test_chat_has_mobile_layout():
    css = CSS.read_text()

    assert ".sysadmin-chat" in css
    assert ".sysadmin-chat-messages" in css
    assert "@media" in css


def test_chat_has_accessible_status_and_labels():
    html = TEMPLATE.read_text()

    assert 'aria-live="polite"' in html
    assert 'aria-label="Message SysAdmin"' in html
